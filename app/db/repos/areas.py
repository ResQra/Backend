from app.db.client import table
from app.services.snapshot_cache import get as _cached, invalidate as _invalidate

TABLE = "AreaRisk"
_AREAS_KEY = "areas_all"
_AREAS_TTL_S = 10.0


def put_area_risk(item: dict) -> dict:
    table(TABLE).put_item(Item=item)
    _invalidate(_AREAS_KEY)
    return item


def list_areas() -> list[dict]:
    return _cached(_AREAS_KEY, _AREAS_TTL_S,
                   lambda: table(TABLE).scan().get("Items", []))


def get_area(geohash: str) -> dict | None:
    resp = table(TABLE).get_item(Key={"geohash": geohash})
    return resp.get("Item")
