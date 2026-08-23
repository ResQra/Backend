import time
import uuid

from boto3.dynamodb.conditions import Key

from app.db.client import table

TABLE = "GovReports"
FEED = "GOV_REPORTS"


def create_report(
    title: str,
    body: str,
    severity: str = "INFO",
    source: str = "",
    area_text: str | None = None,
    link: str | None = None,
    created_by: str | None = None,
) -> dict:
    """Official advisories/notices: posted by coordinators, read by residents."""
    item = {
        "id": f"rpt_{uuid.uuid4().hex[:10]}",
        "feed": FEED,
        "title": title,
        "body": body,
        "severity": severity,  # INFO | WARNING | CRITICAL
        "source": source,
        "area_text": area_text,
        "link": link,
        "created_by": created_by,
        "published_at": int(time.time() * 1000),
    }
    table(TABLE).put_item(Item=item)
    return item


def get_report(report_id: str) -> dict | None:
    resp = table(TABLE).get_item(Key={"id": report_id})
    return resp.get("Item")


def list_reports(limit: int = 50) -> list[dict]:
    """Newest-first."""
    resp = table(TABLE).query(
        IndexName="feed-published-index",
        KeyConditionExpression=Key("feed").eq(FEED),
        ScanIndexForward=False,
        Limit=limit,
    )
    return resp.get("Items", [])


def delete_report(report_id: str) -> bool:
    resp = table(TABLE).delete_item(Key={"id": report_id}, ReturnValues="ALL_OLD")
    return "Attributes" in resp
