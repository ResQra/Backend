from app.db.client import table, to_dynamo_friendly
from app.services.snapshot_cache import get as _cached, invalidate as _invalidate

TABLE = "Teams"
_TEAMS_KEY = "teams_all"
_TEAMS_TTL_S = 8.0

TEAM_STATUSES = ["AVAILABLE", "SOFT_RESERVED", "ON_MISSION", "RETURNING", "UNAVAILABLE", "OFFLINE"]


def put_team(item: dict) -> dict:
    table(TABLE).put_item(Item=item)
    _invalidate(_TEAMS_KEY)
    return item


def get_team(team_id: str) -> dict | None:
    resp = table(TABLE).get_item(Key={"id": team_id})
    return resp.get("Item")


def list_teams() -> list[dict]:
    return _cached(_TEAMS_KEY, _TEAMS_TTL_S,
                   lambda: table(TABLE).scan().get("Items", []))


def update_team(team_id: str, **fields) -> dict | None:
    if not fields:
        return get_team(team_id)
    expr = "SET " + ", ".join(f"#{k} = :{k}" for k in fields)
    try:
        resp = table(TABLE).update_item(
            Key={"id": team_id},
            UpdateExpression=expr,
            ConditionExpression="attribute_exists(id)",
            ExpressionAttributeNames={f"#{k}": k for k in fields},
            ExpressionAttributeValues=to_dynamo_friendly(
                {f":{k}": v for k, v in fields.items()}),
            ReturnValues="ALL_NEW",
        )
    except Exception as exc:
        if "ConditionalCheckFailed" in str(exc):
            return None
        raise
    _invalidate(_TEAMS_KEY)
    return resp.get("Attributes")


def update_location(team_id: str, location: dict, source: str = "team") -> dict | None:
    return update_team(
        team_id,
        location=location,
        location_source=source,
        updated_at=location.get("updated_at"),
    )
