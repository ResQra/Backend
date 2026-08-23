from boto3.dynamodb.conditions import Key

from app.db.client import table

TABLE = "Guides"


def put_guide(item: dict) -> dict:
    table(TABLE).put_item(Item=item)
    return item


def get_guide(guide_id: str) -> dict | None:
    resp = table(TABLE).get_item(Key={"id": guide_id})
    return resp.get("Item")


def list_guides(category: str | None = None) -> list[dict]:
    if category:
        items = table(TABLE).query(
            IndexName="category-index",
            KeyConditionExpression=Key("category").eq(category),
        ).get("Items", [])
    else:
        items = table(TABLE).scan().get("Items", [])
    items.sort(key=lambda g: (g.get("order", 99), g.get("id", "")))
    return items
