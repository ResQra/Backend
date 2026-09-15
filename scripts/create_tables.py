"""Create all DynamoDB tables from app/db/tables.py.

Usage:
    python scripts/create_tables.py

Against DynamoDB Local: set DYNAMODB_ENDPOINT_URL=http://localhost:8000
in backend/.env first.
"""

import pathlib
import sys

import boto3

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.db.tables import TABLES  # noqa: E402


def main() -> None:
    kwargs = {"region_name": settings.aws_region}
    has_credentials = bool(
        settings.aws_access_key_id and settings.aws_secret_access_key
    )
    if settings.dynamodb_endpoint_url:
        kwargs["endpoint_url"] = settings.dynamodb_endpoint_url
        if not has_credentials:
            kwargs["aws_access_key_id"] = "local"
            kwargs["aws_secret_access_key"] = "local"
    elif not has_credentials:
        raise RuntimeError(
            "DynamoDB is not configured. Start DynamoDB Local and set "
            "DYNAMODB_ENDPOINT_URL in Backend/.env, or provide AWS credentials."
        )
    client = boto3.client("dynamodb", **kwargs)

    existing = set(client.list_tables().get("TableNames", []))
    for name, spec in TABLES.items():
        if name in existing:
            print(f"= {name} (exists, skipping)")
            continue
        client.create_table(TableName=name, BillingMode="PAY_PER_REQUEST", **spec)
        client.get_waiter("table_exists").wait(TableName=name)
        print(f"+ {name} created")


if __name__ == "__main__":
    main()
