import logging
import socket
import urllib.parse
from functools import lru_cache

import boto3
from botocore.config import Config

from app.config import settings

logger = logging.getLogger(__name__)

_BOTO_CONFIG = Config(
    connect_timeout=1.0,
    read_timeout=2.0,
    retries={"max_attempts": 1, "mode": "standard"},
)

_mock_context = None


def _is_endpoint_alive(url: str, timeout: float = 0.3) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        err = sock.connect_ex((host, port))
        sock.close()
        return err == 0
    except Exception:
        return False


def _ensure_tables_and_seed(resource):
    from app.db.tables import TABLES
    from app.auth.security import hash_password
    try:
        existing = {t.name for t in resource.tables.all()}
    except Exception:
        existing = set()
    for name, spec in TABLES.items():
        if name not in existing:
            try:
                resource.create_table(TableName=name, BillingMode="PAY_PER_REQUEST", **spec)
            except Exception:
                pass
    try:
        from app.db.seed_defaults import seed_defaults_if_empty
        seed_defaults_if_empty(resource)
    except Exception as exc:
        logger.warning("[DB] Could not seed default operations data: %s", exc)


_cached_resource = None


def _init_mock_resource():
    global _mock_context, _cached_resource
    try:
        import moto
        _mock_context = moto.mock_aws()
        _mock_context.start()
        resource = boto3.resource("dynamodb", region_name=settings.aws_region or "ap-south-1")
        _cached_resource = resource
        _ensure_tables_and_seed(resource)
        return resource
    except Exception as exc:
        logger.error("[DB] Failed to initialize moto mock: %s", exc)
        return boto3.resource("dynamodb", **dynamo_kwargs(), config=_BOTO_CONFIG)


def dynamo_kwargs() -> dict:
    """Shared boto3 config: keys from .env if present, else the standard
    AWS chain (~/.aws/credentials or env vars)."""
    kwargs = {"region_name": settings.aws_region}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    if settings.dynamodb_endpoint_url:
        kwargs["endpoint_url"] = settings.dynamodb_endpoint_url
        if "aws_access_key_id" not in kwargs:
            kwargs["aws_access_key_id"] = "local"
            kwargs["aws_secret_access_key"] = "local"
    return kwargs


def get_dynamo_resource():
    global _cached_resource
    if _cached_resource is not None:
        return _cached_resource

    endpoint = settings.dynamodb_endpoint_url
    has_creds = bool(settings.aws_access_key_id and settings.aws_secret_access_key)

    if endpoint:
        if not _is_endpoint_alive(endpoint):
            logger.warning(
                "[DB] DynamoDB endpoint '%s' is offline/unreachable. Activating local in-memory fallback.",
                endpoint,
            )
            return _init_mock_resource()
        kwargs = dynamo_kwargs()
        kwargs["config"] = _BOTO_CONFIG
        _cached_resource = boto3.resource("dynamodb", **kwargs)
        return _cached_resource

    if not has_creds:
        logger.info("[DB] No AWS credentials or local endpoint provided. Activating in-memory mock.")
        return _init_mock_resource()

    kwargs = dynamo_kwargs()
    kwargs["config"] = _BOTO_CONFIG
    _cached_resource = boto3.resource("dynamodb", **kwargs)
    return _cached_resource


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

