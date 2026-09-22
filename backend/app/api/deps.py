"""Request dependencies: the authenticated user, permissions, and scope.

Scope enforcement is structural. `ScopeDep` resolves the caller's visible
branch set once per request, and every data route takes it as a *required*
argument -- there is no route that can forget it, and a contract test walks the
router to prove it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.permissions import permissions_for_roles
from app.core.security import decode_token
from app.domain.scope import ScopeFilter, ScopeViolation, UserScope, resolve_scope
from app.domain.scope import Branch as ScopeBranch
from app.domain.types import ScopeLevel
from app.models import Branch, User

DbDep = Annotated[Session, Depends(get_db)]


@dataclass(frozen=True, slots=True)
class CurrentUser:
    id: int
    username: str
    full_name: str
    scope_level: ScopeLevel
    scope_id: int | None
    roles: frozenset[str]
    permissions: frozenset[str]

    def has(self, permission: str) -> bool:
        return permission in self.permissions

    @property
    def scope(self) -> UserScope:
        return UserScope(self.scope_level, self.scope_id)


def _unauthorised(detail: str = "not authenticated") -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    db: DbDep,
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauthorised()
    try:
        payload = decode_token(authorization.split(" ", 1)[1])
    except Exception as exc:  # noqa: BLE001 - any JWT failure is the same answer
        raise _unauthorised(f"invalid token: {exc}") from exc

    if payload.get("typ") != "access":
        raise _unauthorised("wrong token type")

    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise _unauthorised("user is inactive")

    roles = frozenset(ur.role.code for ur in user.roles)
    return _build(user, roles)


def _build(user: User, roles: frozenset[str]) -> CurrentUser:
    return CurrentUser(
        id=user.id, username=user.username, full_name=user.full_name,
        scope_level=user.scope_level, scope_id=user.scope_id,
        roles=roles, permissions=permissions_for_roles(set(roles)),
    )


UserDep = Annotated[CurrentUser, Depends(get_current_user)]


def get_active_user(
    db: DbDep,
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    """A caller who has completed account setup.

    When `ENFORCE_PASSWORD_CHANGE` is on, this is where the forced change is
    applied -- not in the UI. Gating client-side alone would leave the API
    serving a user still on the seeded password to anyone holding a token,
    which is exactly what the flag exists to prevent. The switch is off by
    default so it stays out of the way during development.
    """
    user = get_current_user(db, authorization)
    if not settings.ENFORCE_PASSWORD_CHANGE:
        return user
    row = db.get(User, user.id)
    if row is not None and row.must_change_password:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "this account is still on its initial password; set a new one at "
            "POST /auth/password/change before using the API",
        )
    return user


def require(*permissions: str):
    """Route guard. All listed permissions must be held."""

    def _guard(user: Annotated[CurrentUser, Depends(get_active_user)]) -> CurrentUser:
        missing = [p for p in permissions if not user.has(p)]
        if missing:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"missing permission(s): {', '.join(missing)}",
            )
        return user

    return _guard


def get_scope(
    db: DbDep, user: Annotated[CurrentUser, Depends(get_active_user)]
) -> ScopeFilter:
    """Resolve the caller's visible branches once per request."""
    branches = [
        ScopeBranch(b.id, b.branch_code, b.district_id, b.division_id or 0)
        for b in db.scalars(select(Branch))
    ]
    return resolve_scope(user.scope, branches)


ScopeDep = Annotated[ScopeFilter, Depends(get_scope)]


def scope_violation_to_403(exc: ScopeViolation) -> HTTPException:
    """A cross-scope request is 403, never 200-with-nothing.

    Returning an empty result would confirm the requested filter was valid and
    let a branch user map the hierarchy by watching totals change.
    """
    return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
