"""Users, roles, permissions and session artefacts (plan §5).

Scope (which data) and role (which actions) are deliberately independent, which
is what lets one role definition serve all four hierarchy levels.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, text,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.types import ScopeLevel
from app.models.base import AuthorshipMixin, Base, TimestampMixin, pg_enum


class User(Base, TimestampMixin, AuthorshipMixin):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_scope", "scope_level", "scope_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    employee_id: Mapped[str | None] = mapped_column(String(40), unique=True)
    email: Mapped[str | None] = mapped_column(String(160))
    full_name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(Text)

    #: Where the user sits in the hierarchy. NULL scope_id means HO.
    scope_level: Mapped[ScopeLevel] = mapped_column(pg_enum(ScopeLevel, "scope_level"))
    scope_id: Mapped[int | None] = mapped_column(Integer)

    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    must_change_password: Mapped[bool] = mapped_column(server_default=text("true"))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mfa_secret: Mapped[str | None] = mapped_column(Text)
    mfa_enabled: Mapped[bool] = mapped_column(server_default=text("false"))
    failed_attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    roles: Mapped[list["UserRole"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    #: Marks the per-level administrator roles that drive the admin chain.
    is_admin: Mapped[bool] = mapped_column(server_default=text("false"))

    permissions: Mapped[list["RolePermission"]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    module: Mapped[str] = mapped_column(String(40))
    description: Mapped[str | None] = mapped_column(Text)


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), primary_key=True)
    permission_id: Mapped[int] = mapped_column(
        ForeignKey("permissions.id"), primary_key=True
    )

    role: Mapped[Role] = relationship(back_populates="permissions")
    permission: Mapped[Permission] = relationship()


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), primary_key=True)
    granted_by: Mapped[int | None] = mapped_column(BigInteger)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    user: Mapped[User] = relationship(back_populates="roles")
    role: Mapped[Role] = relationship()


class RefreshToken(Base):
    """Rotating refresh tokens with reuse detection.

    A replayed token revokes the whole `family_id`, which turns a stolen token
    into a detected incident rather than a silent persistent session.
    """

    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_family", "family_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    family_id: Mapped[str] = mapped_column(String(64))
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by: Mapped[str | None] = mapped_column(String(128))


class LoginAudit(Base):
    __tablename__ = "login_audit"
    __table_args__ = (Index("ix_login_audit_at", "occurred_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), index=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    success: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(String(80))
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
