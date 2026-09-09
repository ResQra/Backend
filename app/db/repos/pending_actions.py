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
    run_id: str = "",
    sim_min: float | None = None,
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
    if run_id:
        item["run_id"] = run_id
    if sim_min is not None:
        from decimal import Decimal

        item["sim_min"] = Decimal(str(sim_min))
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


def scan_pending_all() -> list[dict]:
    """All PENDING cards via paginated scan (dev-scale). Prefer this over
    list_pending(limit) wherever truncation would starve work — e.g. the
    autonomous gate approving a burst backlog."""
    items: list[dict] = []
    kwargs: dict = {"FilterExpression": Key("state").eq(PENDING)}
    while True:
        resp = table(TABLE).scan(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return items


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
    try:
        resp = table(TABLE).update_item(
            Key={"id": action_id},
            UpdateExpression=(
                "SET #state = :state, decided_at = :decided_at, "
                "decided_by = :actor, decision_note = :note"
            ),
            ConditionExpression="#state = :pending",
            ExpressionAttributeNames={"#state": "state"},
            ExpressionAttributeValues={
                ":state": state,
                ":pending": PENDING,
                ":decided_at": int(time.time() * 1000),
                ":actor": actor_id,
                ":note": note,
            },
            ReturnValues="ALL_NEW",
        )
    except Exception as exc:
        # Lost the race: another decider won. Return current (idempotent).
        if "ConditionalCheckFailed" in str(exc):
            return get_action(action_id)
        raise
    return resp.get("Attributes")


def supersede(action_id: str, note: str = "") -> dict | None:
    """Retire a PENDING card replaced by a newer recommendation.

    Keeps the audit trail (SUPERSEDED) without executing anything.
    Idempotent: non-pending cards are returned untouched.
    """
    current = get_action(action_id)
    if current is None or current.get("state") != PENDING:
        return current
    try:
        resp = table(TABLE).update_item(
            Key={"id": action_id},
            UpdateExpression="SET #state = :state, decision_note = :note",
            ConditionExpression="#state = :pending",
            ExpressionAttributeNames={"#state": "state"},
            ExpressionAttributeValues={":state": SUPERSEDED, ":note": note, ":pending": PENDING},
            ReturnValues="ALL_NEW",
        )
    except Exception as exc:
        if "ConditionalCheckFailed" in str(exc):
            return get_action(action_id)
        raise
    return resp.get("Attributes")


def update_action(action_id: str, **fields) -> dict | None:
    """Phase F: attach deferred debate verdicts (payload) to a live card."""
    if not fields:
        return get_action(action_id)
    from app.db.client import to_dynamo_friendly

    try:
        resp = table(TABLE).update_item(
            Key={"id": action_id},
            UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in fields),
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
