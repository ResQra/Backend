from app.db.client import table

TABLE = "Teams"

TEAM_STATUSES = ["AVAILABLE", "ON_MISSION", "RETURNING", "OFFLINE"]


def put_team(item: dict) -> dict:
    table(TABLE).put_item(Item=item)
    return item


def get_team(team_id: str) -> dict | None:
    resp = table(TABLE).get_item(Key={"id": team_id})
    return resp.get("Item")


def list_teams() -> list[dict]:
    return table(TABLE).scan().get("Items", [])


def update_team(team_id: str, **fields) -> dict | None:
    if not fields:
        return get_team(team_id)
    expr = "SET " + ", ".join(f"#{k} = :{k}" for k in fields)
    resp = table(TABLE).update_item(
        Key={"id": team_id},
        UpdateExpression=expr,
        ExpressionAttributeNames={f"#{k}": k for k in fields},
        ExpressionAttributeValues={f":{k}": v for k, v in fields.items()},
        ReturnValues="ALL_NEW",
    )
    return resp.get("Attributes")
