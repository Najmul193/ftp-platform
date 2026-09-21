"""Audit, approvals and download tracking (plan §6).

The audit log is append-only and hash-chained. The application role holds
INSERT and SELECT only -- UPDATE and DELETE are revoked in the migration, so
even a compromised application cannot rewrite history.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, CheckConstraint, DateTime, Index, Integer, LargeBinary,
    String, Text, text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditLog(Base):
    """Layer 1: semantic application audit.

    Written inside the same transaction as the change it records, so a committed
    change without its audit row is impossible.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_entity", "entity_type", "entity_id"),
        Index("ix_audit_actor_time", "actor_user_id", "occurred_at"),
        Index("ix_audit_action_time", "action", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), index=True
    )
    actor_user_id: Mapped[int | None] = mapped_column(BigInteger)
    #: Denormalised so the record survives the user row being removed.
    actor_username: Mapped[str | None] = mapped_column(String(80))
    actor_scope: Mapped[str | None] = mapped_column(String(40))

    action: Mapped[str] = mapped_column(String(60))
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(80))

    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    #: Changed keys only -- what a reviewer actually reads.
    diff: Mapped[dict | None] = mapped_column(JSONB)

    request_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)

    #: Layer 3: tamper evidence. row_hash = SHA256(canonical_row || prev_hash),
    #: so altering any historical row breaks every hash after it.
    prev_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    row_hash: Mapped[bytes | None] = mapped_column(LargeBinary)


class ApprovalRequest(Base):
    """Maker-checker staging (plan §6.4).

    The pending change lives in `payload` and is applied only on approval, so
    the live table never holds an unapproved value.
    """

    __tablename__ = "approval_requests"
    __table_args__ = (
        CheckConstraint(
            "checker_id IS NULL OR checker_id <> maker_id",
            name="maker_is_not_checker",
        ),
        Index("ix_approval_status", "status", "submitted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSONB)

    status: Mapped[str] = mapped_column(String(20), server_default=text("'PENDING'"))
    maker_id: Mapped[int] = mapped_column(BigInteger)
    maker_comment: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    checker_id: Mapped[int | None] = mapped_column(BigInteger)
    checker_comment: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReportDownload(Base):
    """Every export, with the filter set that produced it.

    Exports are scope-filtered identically to the screens, so a report can never
    widen a user's access; recording the filters is what makes that auditable.
    """

    __tablename__ = "report_downloads"
    __table_args__ = (Index("ix_report_downloads_time", "occurred_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    report_code: Mapped[str] = mapped_column(String(60))
    file_format: Mapped[str] = mapped_column(String(10))
    filters: Mapped[dict | None] = mapped_column(JSONB)
    row_count: Mapped[int | None] = mapped_column(Integer)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
