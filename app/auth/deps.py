from dataclasses import dataclass

import jwt as pyjwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.jwt_utils import decode_token

bearer = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    id: str
    phone: str
    name: str
    role: str


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> CurrentUser:
    if creds is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_token(creds.credentials)
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return CurrentUser(
        id=payload["sub"],
        phone=payload["phone"],
        name=payload["name"],
        role=payload["role"],
    )


def require_role(*roles: str):
    """Dependency factory: require_role('coordinator') guards ops endpoints."""

    def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail=f"Requires role: {roles}")
        return user

    return checker
