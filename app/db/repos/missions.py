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


def create_for_assignment(incident_id: str, team_id: str, pending_action_id: str | None = None) -> dict:
    import time
    import uuid

    item = {
        "id": f"mis_{uuid.uuid4().hex[:12]}",
        "incident_id": incident_id,
        "team_id": team_id,
        "status": "ACTIVE",
        "started_at": int(time.time() * 1000),
        "pending_action_id": pending_action_id,
    }
    return create_mission(item)
