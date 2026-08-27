from functools import lru_cache

import boto3

from app.config import settings


def dynamo_kwargs() -> dict:
    """Shared boto3 config: keys from .env if present, else the standard
    AWS chain (~/.aws/credentials or env vars)."""
    kwargs = {"region_name": settings.aws_region}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    if settings.dynamodb_endpoint_url:
        kwargs["endpoint_url"] = settings.dynamodb_endpoint_url
    return kwargs


@lru_cache(maxsize=1)
def get_dynamo_resource():
    return boto3.resource("dynamodb", **dynamo_kwargs())


def table(name: str):
    return get_dynamo_resource().Table(name)


def to_dynamo_friendly(obj):
    """Converts any floats in nested dicts/lists to Decimal for safe DynamoDB persistence."""
    import json
    from decimal import Decimal
    if obj is None:
        return None
    return json.loads(json.dumps(obj, default=str), parse_float=Decimal)

