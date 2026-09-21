"""Authentication routes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.api.deps import DbDep, UserDep
from app.api.schemas import LoginRequest, MeResponse, TokenResponse
from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.models import Branch, District, Division, LoginAudit, User

router = APIRouter(prefix="/auth", tags=["auth"])


def _audit_login(db, username, success, reason, request):
    db.add(LoginAudit(
        username=username, success=success, reason=reason,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    ))


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: DbDep, request: Request) -> TokenResponse:
    user = db.scalar(select(User).filter_by(username=body.username))

    # The same answer for "no such user" and "wrong password": distinguishing
    # them tells an attacker which usernames exist.
    invalid = HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")

    if user is None:
        _audit_login(db, body.username, False, "unknown_user", request)
        raise invalid

    if user.locked_until and user.locked_until > datetime.now(UTC):
        _audit_login(db, body.username, False, "locked", request)
        raise HTTPException(
            status.HTTP_423_LOCKED,
            f"account locked until {user.locked_until:%H:%M}",
        )

    if not user.is_active:
        _audit_login(db, body.username, False, "inactive", request)
        raise invalid

    if not verify_password(body.password, user.password_hash):
        user.failed_attempts += 1
        if user.failed_attempts >= settings.MAX_FAILED_LOGINS:
            user.locked_until = datetime.now(UTC) + timedelta(
                minutes=settings.LOCKOUT_MINUTES
            )
        _audit_login(db, body.username, False, "bad_password", request)
        raise invalid

    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = datetime.now(UTC)
    _audit_login(db, body.username, True, None, request)

    roles = [ur.role.code for ur in user.roles]
    token = create_access_token(
        str(user.id),
        {"username": user.username, "scope": user.scope_level.value, "roles": roles},
    )
    return TokenResponse(
        access_token=token,
        expires_in=settings.ACCESS_TOKEN_MINUTES * 60,
        must_change_password=user.must_change_password,
    )


@router.get("/me", response_model=MeResponse)
def me(user: UserDep, db: DbDep) -> MeResponse:
    label = "Head Office"
    if user.scope_level.value == "DIVISION":
        d = db.get(Division, user.scope_id)
        label = d.name if d else "Division"
    elif user.scope_level.value == "DISTRICT":
        d = db.get(District, user.scope_id)
        label = d.name if d else "District"
    elif user.scope_level.value == "BRANCH":
        b = db.get(Branch, user.scope_id)
        label = f"{b.branch_code} {b.branch_name}" if b else "Branch"

    row = db.get(User, user.id)
    return MeResponse(
        id=user.id, username=user.username, full_name=user.full_name,
        scope_level=user.scope_level, scope_id=user.scope_id, scope_label=label,
        roles=sorted(user.roles), permissions=sorted(user.permissions),
        must_change_password=bool(row and row.must_change_password),
    )


@router.post("/password/change", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: dict, user: UserDep, db: DbDep
) -> None:
    current = body.get("current_password", "")
    new = body.get("new_password", "")
    row = db.get(User, user.id)

    if not verify_password(current, row.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "current password is incorrect")
    if len(new) < settings.PASSWORD_MIN_LENGTH:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"password must be at least {settings.PASSWORD_MIN_LENGTH} characters",
        )
    if verify_password(new, row.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "new password must differ")

    row.password_hash = hash_password(new)
    row.must_change_password = False
    row.password_changed_at = datetime.now(UTC)
