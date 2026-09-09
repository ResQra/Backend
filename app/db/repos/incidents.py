from boto3.dynamodb.conditions import Key

from app.db.client import table, to_dynamo_friendly
from app.services.snapshot_cache import get as _cached, invalidate as _invalidate

TABLE = "Incidents"
_OPEN_KEY = "open_incidents"
_OPEN_TTL_S = 8.0

# F04 lifecycle; "open" = the statuses that still need rescue work.
# UNVERIFIED needs coordinator location review (F02); AWAITING_ASSIGNMENT
# is a scored incident waiting for dispatch — both must stay visible.
OPEN_STATUSES = ["NEW", "UNVERIFIED", "VERIFIED", "PRIORITIZED",
                 "AWAITING_ASSIGNMENT", "ASSIGNED", "IN_PROGRESS"]
ALL_STATUSES = OPEN_STATUSES + ["RESCUED", "RESOLVED"]


def create_incident(item: dict) -> dict:
    table(TABLE).put_item(Item=item)
    _invalidate(_OPEN_KEY)
    return item


def get_incident(incident_id: str) -> dict | None:
    resp = table(TABLE).get_item(Key={"id": incident_id})
    return resp.get("Item")


def update_incident(incident_id: str, **fields) -> dict | None:
    if not fields:
        return get_incident(incident_id)
    expr = "SET " + ", ".join(f"#{k} = :{k}" for k in fields)
    try:
        from botocore.exceptions import ClientError

        resp = table(TABLE).update_item(
            Key={"id": incident_id},
            UpdateExpression=expr,
            ConditionExpression="attribute_exists(id)",
            ExpressionAttributeNames={f"#{k}": k for k in fields},
            ExpressionAttributeValues=to_dynamo_friendly(
                {f":{k}": v for k, v in fields.items()}),
            ReturnValues="ALL_NEW",
        )
    except Exception as exc:
        # Missing item -> None (callers map to 404); never ghost-create.
        if exc.__class__.__name__ == "ClientError" and "ConditionalCheckFailed" in str(exc):
            return None
        raise
    _invalidate(_OPEN_KEY)
    return resp.get("Attributes")


def list_user_incidents(user_id: str) -> list[dict]:
    resp = table(TABLE).query(
        IndexName="user-created-index",
        KeyConditionExpression=Key("user_id").eq(user_id),
        ScanIndexForward=False,
        Limit=20,
    )
    return resp.get("Items", [])


def list_open_incidents() -> list[dict]:
    """The rescue queue: all open incidents, priority desc then oldest first.

    Out-of-area reports are excluded — they score 0 and live for review,
    never competing with district emergencies. Cached 8s (writes
    invalidate); the console polls on the same cadence.
    """
    return _cached(_OPEN_KEY, _OPEN_TTL_S, _load_open_incidents)


def _load_open_incidents() -> list[dict]:
    items: list[dict] = []
    t = table(TABLE)
    for status in OPEN_STATUSES:
        resp = t.query(
            IndexName="status-created-index",
            KeyConditionExpression=Key("status").eq(status),
        )
        items.extend(resp.get("Items", []))
    items = [i for i in items if not i.get("out_of_area")]
    items.sort(
        key=lambda i: (
            -float((i.get("priority") or {}).get("score") or 0),
            float(i.get("created_at") or 0),
        )
    )
    return items
