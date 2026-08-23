from boto3.dynamodb.conditions import Key

from app.db.client import table

TABLE = "Incidents"

# F04 lifecycle; "open" = the statuses that still need rescue work
OPEN_STATUSES = ["NEW", "VERIFIED", "PRIORITIZED", "ASSIGNED", "IN_PROGRESS"]
ALL_STATUSES = OPEN_STATUSES + ["RESCUED", "RESOLVED"]


def create_incident(item: dict) -> dict:
    table(TABLE).put_item(Item=item)
    return item


def get_incident(incident_id: str) -> dict | None:
    resp = table(TABLE).get_item(Key={"id": incident_id})
    return resp.get("Item")


def update_incident(incident_id: str, **fields) -> dict | None:
    if not fields:
        return get_incident(incident_id)
    expr = "SET " + ", ".join(f"#{k} = :{k}" for k in fields)
    resp = table(TABLE).update_item(
        Key={"id": incident_id},
        UpdateExpression=expr,
        ExpressionAttributeNames={f"#{k}": k for k in fields},
        ExpressionAttributeValues={f":{k}": v for k, v in fields.items()},
        ReturnValues="ALL_NEW",
    )
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
    """The rescue queue: all open incidents, priority desc then oldest first."""
    items: list[dict] = []
    t = table(TABLE)
    for status in OPEN_STATUSES:
        resp = t.query(
            IndexName="status-created-index",
            KeyConditionExpression=Key("status").eq(status),
        )
        items.extend(resp.get("Items", []))
    items.sort(
        key=lambda i: (
            -float((i.get("priority") or {}).get("score") or 0),
            float(i.get("created_at") or 0),
        )
    )
    return items
