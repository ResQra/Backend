from app.db.client import table

TABLE = "Shelters"


def put_shelter(item: dict) -> dict:
    table(TABLE).put_item(Item=item)
    return item


def list_shelters() -> list[dict]:
    return table(TABLE).scan().get("Items", [])


def update_occupancy(shelter_id: str, current_occupancy: int) -> dict | None:
    resp = table(TABLE).update_item(
        Key={"id": shelter_id},
        UpdateExpression="SET current_occupancy = :occ",
        ExpressionAttributeValues={":occ": current_occupancy},
        ReturnValues="ALL_NEW",
    )
    return resp.get("Attributes")


def get_shelter(shelter_id: str) -> dict | None:
    resp = table(TABLE).get_item(Key={"id": shelter_id})
    return resp.get("Item")
