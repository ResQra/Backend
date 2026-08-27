import time
import uuid

from boto3.dynamodb.conditions import Key

from app.db.client import table, to_dynamo_friendly

TABLE = "PendingActions"
PENDING = "PENDING"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
SUPERSEDED = "SUPERSEDED"
EXPIRED = "EXPIRED"


def create_action(
    type_: str,
    incident_id: str,
    proposed_team_id: str | None,
    reasons: list[str],
    payload: dict | None = None,
) -> dict:
    item = {
        "id": f"pa_{uuid.uuid4().hex[:12]}",
        "type": type_,
        "incident_id": incident_id,
        "proposed_team_id": proposed_team_id,
        "reasons": reasons,
        "state": PENDING,
        "created_at": int(time.time() * 1000),
        "decided_at": None,
        "decided_by": None,
        "decision_note": "",
        "payload": payload or {},
    }
    table(TABLE).put_item(Item=to_dynamo_friendly(item))
    return item


def get_action(action_id: str) -> dict | None:
    resp = table(TABLE).get_item(Key={"id": action_id})
    return resp.get("Item")


def list_pending(limit: int = 50) -> list[dict]:
    resp = table(TABLE).query(
        IndexName="state-created-index",
        KeyConditionExpression=Key("state").eq(PENDING),
        ScanIndexForward=False,
        Limit=limit,
    )
    return resp.get("Items", [])


def list_for_incident(incident_id: str, limit: int = 20) -> list[dict]:
    resp = table(TABLE).query(
        IndexName="incident-created-index",
        KeyConditionExpression=Key("incident_id").eq(incident_id),
        ScanIndexForward=False,
        Limit=limit,
    )
    return resp.get("Items", [])


def decide(action_id: str, state: str, actor_id: str, note: str = "") -> dict | None:
    state = state.upper()
    if state not in {APPROVED, REJECTED}:
        raise ValueError("state must be APPROVED or REJECTED")
    current = get_action(action_id)
    if current is None:
        return None
    if current.get("state") != PENDING:
        return current
    resp = table(TABLE).update_item(
        Key={"id": action_id},
        UpdateExpression=(
            "SET #state = :state, decided_at = :decided_at, "
            "decided_by = :actor, decision_note = :note"
        ),
        ExpressionAttributeNames={"#state": "state"},
        ExpressionAttributeValues={
            ":state": state,
            ":decided_at": int(time.time() * 1000),
            ":actor": actor_id,
            ":note": note,
        },
        ReturnValues="ALL_NEW",
    )
    return resp.get("Attributes")
