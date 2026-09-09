import time
import uuid

from boto3.dynamodb.conditions import Key

from app.db.client import table

TABLE = "Users"


def _stable_fallback_id(phone: str) -> str:
    import hashlib

    return "u_" + hashlib.sha256(phone.strip().encode()).hexdigest()[:12]


def find_by_phone(phone: str) -> dict | None:
    try:
        resp = table(TABLE).query(
            IndexName="phone-index",
            KeyConditionExpression=Key("phone").eq(phone.strip()),
            Limit=1,
        )
        items = resp.get("Items", [])
        return items[0] if items else None
    except Exception:
        return None


def find_by_username(username: str) -> dict | None:
    try:
        resp = table(TABLE).query(
            IndexName="username-index",
            KeyConditionExpression=Key("username").eq(username.strip().lower()),
            Limit=1,
        )
        items = resp.get("Items", [])
        return items[0] if items else None
    except Exception:
        return None


def get_user(user_id: str) -> dict | None:
    resp = table(TABLE).get_item(Key={"id": user_id})
    return resp.get("Item")


def create_user(
    *,
    phone: str | None = None,
    name: str,
    role: str,
    username: str | None = None,
    password_hash: str | None = None,
    user_id: str | None = None,
) -> dict:
    item = {
        "id": user_id or f"u_{uuid.uuid4().hex[:12]}",
        "name": name,
        "role": role,
        "location": None,
        "people_with": None,
        "vulnerabilities": [],
        "status": "UNKNOWN",
        "updated_at": int(time.time() * 1000),
    }
    if phone:
        item["phone"] = phone.strip()
    if username:
        item["username"] = username.strip().lower()
    if password_hash:
        item["password_hash"] = password_hash
    table(TABLE).put_item(Item=item)
    return item


def login_or_create_resident(phone: str, name: str) -> dict:
    existing = find_by_phone(phone)
    if existing:
        if name and name != existing.get("name"):
            update_user_info(existing["id"], name=name)
            existing["name"] = name
        return existing
    try:
        return create_user(phone=phone, name=name, role="resident")
    except Exception:
        return {
            "id": _stable_fallback_id(phone),
            "phone": phone,
            "name": name,
            "role": "resident",
        }


def update_user_info(user_id: str, **fields) -> dict | None:
    updates = {k: v for k, v in fields.items() if v is not None}
    if not updates:
        return get_user(user_id)
    updates["updated_at"] = int(time.time() * 1000)
    expr = "SET " + ", ".join(f"#{k} = :{k}" for k in updates)
    try:
        resp = table(TABLE).update_item(
            Key={"id": user_id},
            UpdateExpression=expr,
            ConditionExpression="attribute_exists(id)",
            ExpressionAttributeNames={f"#{k}": k for k in updates},
            ExpressionAttributeValues={f":{k}": v for k, v in updates.items()},
            ReturnValues="ALL_NEW",
        )
    except Exception as exc:
        # Missing user -> None (callers map to 404); never ghost-create.
        if "ConditionalCheckFailed" in str(exc):
            return None
        raise
    return resp.get("Attributes")


def set_password(user_id: str, password: str) -> None:
    from app.auth.security import hash_password

    update_user_info(user_id, password_hash=hash_password(password))


def set_phone(user_id: str, new_phone: str) -> dict | None:
    if find_by_phone(new_phone):
        raise ValueError("Phone number already in use by another account")
    return update_user_info(user_id, phone=new_phone.strip())


def update_device_location(user_id: str, lat, lng, label: str = "") -> dict | None:
    from decimal import Decimal

    return update_user_info(
        user_id,
        device_location={
            "lat": Decimal(str(lat)),
            "lng": Decimal(str(lng)),
            "label": label,
        },
    )


def clear_resolved_location(user_id: str) -> None:
    table(TABLE).update_item(
        Key={"id": user_id},
        UpdateExpression="REMOVE #loc",
        ExpressionAttributeNames={"#loc": "location"},
    )


def list_residents_with_location() -> list[dict]:
    """Return residents with stated location or device GPS for ops mapping."""
    try:
        items = (
            table(TABLE)
            .scan(
                FilterExpression="#role = :r",
                ExpressionAttributeNames={"#role": "role"},
                ExpressionAttributeValues={":r": "resident"},
            )
            .get("Items", [])
        )
    except Exception:
        return []

    out = []
    for user in items:
        stated = user.get("location_text")
        loc = user.get("location")
        dev = user.get("device_location")
        resolved = isinstance(loc, dict) and loc.get("lat") is not None
        has_device = isinstance(dev, dict) and dev.get("lat") is not None
        if not stated and not resolved and not has_device:
            continue

        entry = dict(user)
        entry["plot_source"] = "stated_geocoded" if resolved else None
        if not resolved and has_device:
            entry["location"] = dict(dev)
            entry["plot_source"] = "device_gps_fallback" if stated else "device_gps"
        if entry.get("location") is None:
            continue
        out.append(entry)
    return out
