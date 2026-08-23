from fastapi import APIRouter, Depends, HTTPException

from app.auth import otp
from app.auth.deps import CurrentUser, get_current_user
from app.auth.jwt_utils import create_token
from app.auth.security import hash_password, verify_password
from app.config import settings
from app.db.repos import users
from app.models import (
    AdminLogin,
    MeResponse,
    OtpRequest,
    OtpVerify,
    PasswordChange,
    PhoneChange,
    TokenResponse,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/otp/request")
async def request_otp(body: OtpRequest):
    """Resident login step 1: phone + name → 6-digit OTP (5 min expiry).

    Dev mode returns the code in the response so the flow is testable
    without an SMS provider; production wires send_sms() to SNS/Twilio.
    """
    code = otp.issue(body.phone.strip())
    await otp.send_sms(body.phone.strip(), code)
    resp = {"sent": True, "expires_in": 300}
    if settings.otp_dev_mode:
        resp["dev_code"] = code
    return resp


@router.post("/otp/verify", response_model=TokenResponse)
def verify_otp(body: OtpVerify):
    """Resident login step 2: verify code → JWT. Registers on first login."""
    phone = body.phone.strip()
    if not otp.verify(phone, body.code.strip()):
        raise HTTPException(status_code=401, detail="Invalid or expired code")
    user = users.login_or_create_resident(phone, name=(body.name or "").strip())
    token = create_token(user["id"], user.get("name") or "Resident", "resident", phone=phone)
    return TokenResponse(
        token=token, user_id=user["id"], role="resident", name=user.get("name")
    )


@router.post("/admin/login", response_model=TokenResponse)
def admin_login(body: AdminLogin):
    """Coordinator login: unique username + per-admin password (hashed).
    Multiple admins are just multiple rows with role=coordinator."""
    admin = users.find_by_username(body.username)
    if admin is None or not verify_password(body.password, admin.get("password_hash")):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_token(
        admin["id"], admin.get("name") or body.username, "coordinator", phone=admin.get("phone")
    )
    return TokenResponse(
        token=token,
        user_id=admin["id"],
        role="coordinator",
        name=admin.get("name") or body.username,
    )


@router.patch("/password")
def change_password(body: PasswordChange, user: CurrentUser = Depends(get_current_user)):
    """Change own password (admins). Requires the old password."""
    record = users.get_user(user.id)
    if record is None or not verify_password(body.old_password, record.get("password_hash")):
        raise HTTPException(status_code=401, detail="Old password is incorrect")
    users.set_password(user.id, body.new_password)
    return {"changed": True}


@router.patch("/phone")
def change_phone(body: PhoneChange, user: CurrentUser = Depends(get_current_user)):
    """Change own phone number. Safe: user ids are stable UUIDs, so chats,
    incidents and history survive the change. (Future: OTP-verify the new
    number before accepting it.)"""
    try:
        users.set_phone(user.id, body.new_phone)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"changed": True}


@router.get("/me", response_model=MeResponse)
def me(user: CurrentUser = Depends(get_current_user)):
    return MeResponse(
        id=user.id, phone=user.phone or "", name=user.name, role=user.role
    )
