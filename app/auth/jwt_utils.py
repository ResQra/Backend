import hashlib
from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings


def fallback_user_id(phone: str) -> str:
    """Deterministic id for DB-less operation (same phone → same session)."""
    return "u_" + hashlib.sha256(phone.strip().encode()).hexdigest()[:12]


def create_token(user_id: str, name: str, role: str, phone: str | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "phone": phone,
        "name": name,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
