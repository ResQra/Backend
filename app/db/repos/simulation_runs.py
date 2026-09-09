"""Phase B run records — one row per simulation run (arch §67-68)."""

from __future__ import annotations

import time

from app.db.client import table, to_dynamo_friendly

TABLE = "SimulationRuns"


def _now_ms() -> int:
    return int(time.time() * 1000)


def create_run(item: dict) -> dict:
    item = to_dynamo_friendly({**item, "updated_at": _now_ms()})
    table(TABLE).put_item(Item=item)
    return item


def get_run(run_id: str) -> dict | None:
    resp = table(TABLE).get_item(Key={"id": run_id})
    return resp.get("Item")


def update_run(run_id: str, **fields) -> dict | None:
    if not fields:
        return get_run(run_id)
    fields["updated_at"] = _now_ms()
    expr = "SET " + ", ".join(f"#{k} = :{k}" for k in fields)
    try:
        from botocore.exceptions import ClientError

        resp = table(TABLE).update_item(
            Key={"id": run_id},
            UpdateExpression=expr,
            ConditionExpression="attribute_exists(id)",
            ExpressionAttributeNames={f"#{k}": k for k in fields},
            ExpressionAttributeValues=to_dynamo_friendly({f":{k}": v for k, v in fields.items()}),
            ReturnValues="ALL_NEW",
        )
    except Exception as exc:
        if exc.__class__.__name__ == "ClientError" and "ConditionalCheckFailed" in str(exc):
            return None
        raise
    return resp.get("Attributes")


def list_runs(limit: int = 20) -> list[dict]:
    items = table(TABLE).scan(Limit=limit).get("Items", [])
    items.sort(key=lambda r: -int(r.get("created_at") or 0))
    return items
