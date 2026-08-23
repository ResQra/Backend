from decimal import Decimal

from boto3.dynamodb.conditions import Key

from app.db.client import table

TABLE = "ChatHistory"


def append_message(user_id: str, role: str, content: str) -> dict:
    import time

    item = {
        "user_id": user_id,
        "ts": Decimal(str(time.time())),
        "role": role,  # "user" | "agent"
        "content": content,
    }
    table(TABLE).put_item(Item=item)
    return item


def get_history(user_id: str, limit: int = 50) -> list[dict]:
    """Oldest-first, most recent `limit` messages."""
    resp = table(TABLE).query(
        KeyConditionExpression=Key("user_id").eq(user_id),
        ScanIndexForward=False,
        Limit=limit,
    )
    return list(reversed(resp.get("Items", [])))
