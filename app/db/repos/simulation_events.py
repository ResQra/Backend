import time

from boto3.dynamodb.conditions import Key

from app.db.client import table

TABLE = "SimulationEvents"


def put_event(idempotency_key: str, event_type: str, payload: dict) -> dict:
    existing = get_event(idempotency_key)
    if existing is not None:
        return existing
    item = {
        "idempotency_key": idempotency_key,
        "event_type": event_type,
        "payload": payload,
        "created_at": int(time.time() * 1000),
        "source_priority": payload.get("source_priority", "SIMULATION"),
    }
    table(TABLE).put_item(Item=item)
    return item


def get_event(idempotency_key: str) -> dict | None:
    resp = table(TABLE).get_item(Key={"idempotency_key": idempotency_key})
    return resp.get("Item")


def list_by_type(event_type: str, limit: int = 50) -> list[dict]:
    resp = table(TABLE).query(
        IndexName="type-created-index",
        KeyConditionExpression=Key("event_type").eq(event_type),
        ScanIndexForward=False,
        Limit=limit,
    )
    return resp.get("Items", [])
