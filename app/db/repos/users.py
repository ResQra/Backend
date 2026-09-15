import time
import uuid

from boto3.dynamodb.conditions import Key

from app.db.client import table

TABLE = "Users"

# In-memory fallback dictionary mirroring app/auth/otp.py and app/agents_gateway/memory.py
_fallback_users: dict[str, dict] = {}


def _init_fallback():
    if not _fallback_users:
        from app.auth.security import hash_password

        admin = {
            "id": "u_admin_default",
            "name": "Control Room",
            "role": "coordinator",
            "username": "resqra-admin",
            "password_hash": hash_password("ResQra123"),
            "status": "AVAILABLE",
            "updated_at": int(time.time() * 1000),
        }
        _fallback_users[admin["id"]] = admin


_init_fallback()


def _stable_fallback_id(phone: str) -> str:
    import hashlib

    return "u_" + hashlib.sha256(phone.strip().encode()).hexdigest()[:12]


def find_by_phone(phone: str) -> dict | None:
    clean = phone.strip()
    try:
        resp = table(TABLE).query(
            IndexName="phone-index",
            KeyConditionExpression=Key("phone").eq(clean),
            Limit=1,
        )
        items = resp.get("Items", [])
        if items:
            _fallback_users[items[0]["id"]] = items[0]
            return items[0]
    except Exception:
        pass
    for u in _fallback_users.values():
        if (u.get("phone") or "").strip() == clean:
            return u
    return None


def find_by_username(username: str) -> dict | None:
    clean = username.strip().lower()
    try:
        resp = table(TABLE).query(
            IndexName="username-index",
            KeyConditionExpression=Key("username").eq(clean),
            Limit=1,
        )
        items = resp.get("Items", [])
        if items:
            _fallback_users[items[0]["id"]] = items[0]
            return items[0]
    except Exception:
        pass
    for u in _fallback_users.values():
        if (u.get("username") or "").strip().lower() == clean:
            return u
    return None


def get_user(user_id: str) -> dict | None:
    try:
        resp = table(TABLE).get_item(Key={"id": user_id})
        item = resp.get("Item")
        if item:
            _fallback_users[user_id] = item
            return item
    except Exception:
        pass
    return _fallback_users.get(user_id)


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
    try:
        table(TABLE).put_item(Item=item)
    except Exception:
        pass
    _fallback_users[item["id"]] = item
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
        fallback_item = {
            "id": _stable_fallback_id(phone),
            "phone": phone.strip(),
            "name": name,
            "role": "resident",
        }
        _fallback_users[fallback_item["id"]] = fallback_item
        return fallback_item


def update_user_info(user_id: str, **fields) -> dict | None:
    updates = {k: v for k, v in fields.items() if v is not None}
    if not updates:
        return get_user(user_id)
    updates["updated_at"] = int(time.time() * 1000)
    if user_id in _fallback_users:
        _fallback_users[user_id].update(updates)
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
        return resp.get("Attributes")
    except Exception as exc:
        # Missing user -> None (callers map to 404); never ghost-create.
        if "ConditionalCheckFailed" in str(exc):
            return None
        return _fallback_users.get(user_id)


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
