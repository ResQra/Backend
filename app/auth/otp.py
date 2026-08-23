"""OTP issue/verify for resident phone login.

Storage: OtpCodes table in DynamoDB (hashed code + expiry + attempt
counter) with an in-memory fallback when the DB is unreachable, mirroring
the chat-memory pattern. Delivery: dev mode returns the code in the API
response and logs it; swap `send_sms` for SNS/Twilio to go live.
"""

import hashlib
import hmac
import secrets
import time
from collections import defaultdict

from app.db.client import table

_OTP_TABLE = "OtpCodes"
_TTL_SECONDS = 300
_MAX_ATTEMPTS = 5

# memory fallback: phone -> {code_hash, expires_at, attempts}
_pending: dict[str, dict] = {}


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


async def send_sms(phone: str, code: str) -> None:
    """Delivery seam — replace with AWS SNS / Twilio / MSG91 for real SMS."""
    print(f"[OTP] dev delivery to {phone}: code {code}")


def issue(phone: str) -> str:
    """Create a new 6-digit OTP for this phone, replacing any old one."""
    code = f"{secrets.randbelow(1000000):06d}"
    record = {
        "code_hash": _hash(code),
        "expires_at": int(time.time()) + _TTL_SECONDS,
        "attempts": 0,
    }
    try:
        table(_OTP_TABLE).put_item(Item={"phone": phone, **record})
    except Exception:
        pass
    _pending[phone] = record
    return code


def verify(phone: str, code: str) -> bool:
    """True + consume on success; rate-limited, expiry-checked."""
    record = None
    try:
        resp = table(_OTP_TABLE).get_item(Key={"phone": phone})
        record = resp.get("Item")
    except Exception:
        record = None
    if record is None:
        record = _pending.get(phone)
    if record is None:
        return False

    now = int(time.time())
    if now > int(record.get("expires_at", 0)):
        _consume(phone)
        return False
    if int(record.get("attempts", 0)) >= _MAX_ATTEMPTS:
        _consume(phone)
        return False

    ok = hmac.compare_digest(_hash(code), str(record.get("code_hash")))
    if ok:
        _consume(phone)
        return True

    record["attempts"] = int(record.get("attempts", 0)) + 1
    try:
        table(_OTP_TABLE).update_item(
            Key={"phone": phone},
            UpdateExpression="SET attempts = :a",
            ExpressionAttributeValues={":a": record["attempts"]},
        )
    except Exception:
        pass
    return False


def _consume(phone: str) -> None:
    _pending.pop(phone, None)
    try:
        table(_OTP_TABLE).delete_item(Key={"phone": phone})
    except Exception:
        pass
