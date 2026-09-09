from app.db.client import table
from app.services.snapshot_cache import get as _cached, invalidate as _invalidate

TABLE = "Shelters"
_SHELTERS_KEY = "shelters_all"
_SHELTERS_TTL_S = 10.0


def put_shelter(item: dict) -> dict:
    table(TABLE).put_item(Item=item)
    _invalidate(_SHELTERS_KEY)
    return item


def list_shelters() -> list[dict]:
    return _cached(_SHELTERS_KEY, _SHELTERS_TTL_S,
                   lambda: table(TABLE).scan().get("Items", []))


def update_occupancy(shelter_id: str, current_occupancy: int,
                     source: str | None = None) -> dict | None:
    expr = "SET current_occupancy = :occ"
    values: dict = {":occ": current_occupancy}
    if source is not None:
        expr += ", occupancy_source = :src"
        values[":src"] = str(source).upper()
    try:
        resp = table(TABLE).update_item(
            Key={"id": shelter_id},
            UpdateExpression=expr,
            ConditionExpression="attribute_exists(id)",
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )
    except Exception as exc:
        # Missing shelter -> None (callers map to 404); never ghost-create.
        if "ConditionalCheckFailed" in str(exc):
            return None
        raise
    _invalidate(_SHELTERS_KEY)
    return resp.get("Attributes")


def get_shelter(shelter_id: str) -> dict | None:
    resp = table(TABLE).get_item(Key={"id": shelter_id})
    return resp.get("Item")
