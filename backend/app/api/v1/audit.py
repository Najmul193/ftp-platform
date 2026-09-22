"""The audit trail, readable (plan §6.1).

Every service already writes here inside the transaction that made the change,
so the log has been complete since the first migration -- it simply had no way
out of the database. These routes are that way out: the activity log behind the
configuration and master-data screens.

The table is append-only and hash-chained (`prev_hash`/`row_hash`, computed by a
database trigger), and the application role holds INSERT and SELECT only. There
is deliberately no write route here: an audit entry is a side effect of a change,
never something a caller can post.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import DbDep, UserDep, require
from app.api.schemas import ORMModel
from app.models import AuditLog

router = APIRouter(prefix="/audit", tags=["governance"])

_view = Depends(require("AUDIT_VIEW"))

#: A cap the caller cannot raise. The log is unbounded and grows with use.
MAX_LIMIT = 200


class AuditEntry(ORMModel):
    id: int
    occurred_at: datetime
    actor_username: str | None
    actor_scope: str | None
    action: str
    entity_type: str
    entity_id: str | None
    #: Changed keys only, as {field: {"from": x, "to": y}} -- what a reviewer
    #: actually reads. NULL on a create or a delete, where one side is absent.
    diff: dict[str, Any] | None


class AuditEntryDetail(AuditEntry):
    before: dict[str, Any] | None
    after: dict[str, Any] | None


class AuditPage(BaseModel):
    items: list[AuditEntry]
    total: int
    limit: int
    offset: int


@router.get("", response_model=AuditPage, dependencies=[_view])
def list_audit(
    db: DbDep,
    _user: UserDep,
    entity_type: Annotated[list[str] | None, Query()] = None,
    entity_id: str | None = None,
    action: Annotated[list[str] | None, Query()] = None,
    actor: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    """Newest first, filtered. `total` is the count before paging."""
    where = []
    if entity_type:
        where.append(AuditLog.entity_type.in_(entity_type))
    if entity_id:
        where.append(AuditLog.entity_id == entity_id)
    if action:
        where.append(AuditLog.action.in_(action))
    if actor:
        where.append(AuditLog.actor_username == actor)
    if date_from:
        where.append(AuditLog.occurred_at >= datetime.combine(date_from, time.min))
    if date_to:
        # Inclusive of the whole end day: a user filtering "to today" means it.
        where.append(AuditLog.occurred_at < datetime.combine(date_to, time.max))

    total = db.scalar(
        select(func.count()).select_from(AuditLog).where(*where)
    ) or 0
    rows = db.scalars(
        select(AuditLog).where(*where)
        .order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
        .limit(limit).offset(offset)
    )
    return AuditPage(items=list(rows), total=total, limit=limit, offset=offset)


@router.get("/{entry_id}", response_model=AuditEntryDetail, dependencies=[_view])
def audit_entry(entry_id: int, db: DbDep, _user: UserDep):
    """One entry with both sides of the change.

    Kept off the list route on purpose: `before`/`after` on an ingestion event
    can be large, and the list is what a screen polls.
    """
    entry = db.get(AuditLog, entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"Audit entry {entry_id} does not exist.")
    return entry
