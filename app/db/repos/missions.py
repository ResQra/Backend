from app.db.client import table

TABLE = "Missions"


def create_mission(item: dict) -> dict:
    table(TABLE).put_item(Item=item)
    return item


def get_mission(mission_id: str) -> dict | None:
    resp = table(TABLE).get_item(Key={"id": mission_id})
    return resp.get("Item")


def list_missions() -> list[dict]:
    return table(TABLE).scan().get("Items", [])
