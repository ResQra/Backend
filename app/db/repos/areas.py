from app.db.client import table

TABLE = "AreaRisk"


def put_area_risk(item: dict) -> dict:
    table(TABLE).put_item(Item=item)
    return item


def list_areas() -> list[dict]:
    return table(TABLE).scan().get("Items", [])


def get_area(geohash: str) -> dict | None:
    resp = table(TABLE).get_item(Key={"geohash": geohash})
    return resp.get("Item")
