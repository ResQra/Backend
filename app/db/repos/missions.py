from __future__ import annotations

import time
import uuid

from app.db.client import table, to_dynamo_friendly

TABLE = "Missions"


def create_mission(item: dict) -> dict:
    table(TABLE).put_item(Item=item)
    return item


def get_mission(mission_id: str) -> dict | None:
    resp = table(TABLE).get_item(Key={"id": mission_id})
    return resp.get("Item")


def list_missions() -> list[dict]:
    return table(TABLE).scan().get("Items", [])


def create_for_assignment(incident_id: str, team_id: str, pending_action_id: str | None = None,
                        route_id: str | None = None, reason_codes: list | None = None,
                        run_id: str = "", sim_min: float | None = None) -> dict:
    item = {
        "id": f"mis_{uuid.uuid4().hex[:12]}",
        "incident_id": incident_id,
        "team_id": team_id,
        "status": "DISPATCHED",  # Phase 8: approved dispatch (§53)
        "started_at": int(time.time() * 1000),
        "pending_action_id": pending_action_id,
        "route_id": route_id,
        "reason_codes": reason_codes or [],
    }
    if run_id:
        item["run_id"] = run_id
    if sim_min is not None:
        from decimal import Decimal

        item["sim_min"] = Decimal(str(sim_min))
    return create_mission(item)


def update_mission(mission_id: str, **fields) -> dict | None:
    """Phase D: mission lifecycle transitions (EN_ROUTE/ON_SCENE/COMPLETED)."""
    if not fields:
        return get_mission(mission_id)
    expr = "SET " + ", ".join(f"#{k} = :{k}" for k in fields)
    try:
        from botocore.exceptions import ClientError

        resp = table(TABLE).update_item(
            Key={"id": mission_id},
            UpdateExpression=expr,
            ConditionExpression="attribute_exists(id)",
            ExpressionAttributeNames={f"#{k}": k for k in fields},
            ExpressionAttributeValues=to_dynamo_friendly(
                {f":{k}": v for k, v in fields.items()}),
            ReturnValues="ALL_NEW",
        )
    except Exception as exc:
        if exc.__class__.__name__ == "ClientError" and "ConditionalCheckFailed" in str(exc):
            return None
        raise
    return resp.get("Attributes")
