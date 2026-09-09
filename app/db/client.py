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
    """Recursively convert floats to Decimal for safe DynamoDB persistence.

    Preserves Decimal (unlike a naive json round-trip, which would turn
    Decimals into strings and corrupt coordinate/number fields).
    """
    from decimal import Decimal
    if obj is None or isinstance(obj, (str, bool, int)):
        return obj
    if isinstance(obj, Decimal):
        return obj
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: to_dynamo_friendly(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_dynamo_friendly(v) for v in obj]
    return obj


def dynamo_to_json(obj):
    """Recursively converts DynamoDB Decimals to int/float for plain
    json.dumps (WebSocket paths don't get FastAPI's jsonable_encoder)."""
    from decimal import Decimal
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    if isinstance(obj, dict):
        return {k: dynamo_to_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [dynamo_to_json(v) for v in obj]
    return obj

