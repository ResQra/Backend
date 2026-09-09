import time
import uuid

from boto3.dynamodb.conditions import Key

from app.db.client import table, to_dynamo_friendly

TABLE = "ActivityEvent"


def log_event(actor: str, type_: str, summary: str, payload: dict | None = None,
             run_id: str = "") -> dict:
    """F09 append-only feed. actor: 'agent' | 'human' | 'system'.

    run_id (Phase A): simulation-run provenance. Stored top-level when
    truthy so timeline/score can filter by run without touching payloads.
    """
    item = {
        "id": f"evt_{uuid.uuid4().hex[:12]}",
        "feed": "GLOBAL",
        "ts": int(time.time() * 1000),
        "actor": actor,
        "type": type_,
        "summary": summary,
    }
    if run_id:
        item["run_id"] = run_id
    if payload:
        item["payload"] = payload
    table(TABLE).put_item(Item=to_dynamo_friendly(item))
    return item


def recent_events(limit: int = 50) -> list[dict]:
    """Newest-first timeline for the console."""
    resp = table(TABLE).query(
        IndexName="feed-ts-index",
        KeyConditionExpression=Key("feed").eq("GLOBAL"),
        ScanIndexForward=False,
        Limit=limit,
    )
    return resp.get("Items", [])
