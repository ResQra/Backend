"""Coordinator multi-session chat store (Phase 1).

Mirrors db/repos/chat.py shapes so the supervisor path stays identical;
only the key changes (session_id instead of user_id) plus a session
registry carrying title/area/incident context per conversation.
"""

import time
import uuid
from decimal import Decimal

from boto3.dynamodb.conditions import Key

from app.db.client import table

SESSIONS_TABLE = "CoordinatorSessions"
CHAT_TABLE = "CoordinatorChat"


def _now() -> int:
    return int(time.time() * 1000)


def create_session(coordinator_id: str, title: str = "New conversation",
                   area: str | None = None,
                   incident_id: str | None = None) -> dict:
    item = {
        "session_id": f"cs_{uuid.uuid4().hex[:12]}",
        "coordinator_id": coordinator_id,
        "title": title,
        "area": area,
        "incident_id": incident_id,
        "created_at": _now(),
        "updated_at": _now(),
    }
    table(SESSIONS_TABLE).put_item(Item=item)
    return item


def list_sessions(coordinator_id: str, limit: int = 30) -> list[dict]:
    resp = table(SESSIONS_TABLE).query(
        IndexName="coordinator-updated-index",
        KeyConditionExpression=Key("coordinator_id").eq(coordinator_id),
        ScanIndexForward=False,
        Limit=limit,
    )
    return resp.get("Items", [])


def get_session(session_id: str) -> dict | None:
    return table(SESSIONS_TABLE).get_item(Key={"session_id": session_id}).get("Item")


def touch_session(session_id: str, title: str | None = None) -> None:
    expr = "SET updated_at = :now"
    values: dict = {":now": _now()}
    if title:
        expr += ", title = :title"
        values[":title"] = title
    table(SESSIONS_TABLE).update_item(Key={"session_id": session_id},
                                      UpdateExpression=expr,
                                      ExpressionAttributeValues=values)


def delete_session(session_id: str) -> None:
    msgs = table(CHAT_TABLE).query(
        KeyConditionExpression=Key("session_id").eq(session_id)).get("Items", [])
    with table(CHAT_TABLE).batch_writer() as batch:
        for m in msgs:
            batch.delete_item(Key={"session_id": session_id, "ts": m["ts"]})
    table(SESSIONS_TABLE).delete_item(Key={"session_id": session_id})


def append_message(session_id: str, role: str, content: str) -> dict:
    item = {
        "session_id": session_id,
        "ts": Decimal(str(time.time())),
        "role": role,  # "user" | "agent"
        "content": content,
    }
    table(CHAT_TABLE).put_item(Item=item)
    touch_session(session_id)
    return item


def get_history(session_id: str, limit: int = 50) -> list[dict]:
    """Oldest-first, most recent `limit` messages."""
    resp = table(CHAT_TABLE).query(
        KeyConditionExpression=Key("session_id").eq(session_id),
        ScanIndexForward=False,
        Limit=limit,
    )
    return list(reversed(resp.get("Items", [])))
