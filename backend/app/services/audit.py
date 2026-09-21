"""Audit emission (plan §6.1, layer 1).

Every call writes inside the caller's transaction. The service layer never
commits on its own, so a change and its audit row succeed or fail together --
which is what makes "a committed change without an audit record" impossible
rather than merely unlikely.

The hash chain (layer 3) is computed by a database trigger, so a client cannot
supply a forged hash.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog


def _diff(before: dict | None, after: dict | None) -> dict | None:
    """Changed keys only -- what a reviewer actually reads."""
    if before is None or after is None:
        return None
    keys = set(before) | set(after)
    changed = {
        k: {"from": before.get(k), "to": after.get(k)}
        for k in keys
        if before.get(k) != after.get(k)
    }
    return changed or None


def record(
    session: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: str | int | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    actor_user_id: int | None = None,
    actor_username: str | None = None,
    actor_scope: str | None = None,
    request_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    """Append one semantic audit event."""
    entry = AuditLog(
        action=action,
        entity_type=entity_type,
        entity_id=None if entity_id is None else str(entity_id),
        before=before,
        after=after,
        diff=_diff(before, after),
        actor_user_id=actor_user_id,
        actor_username=actor_username,
        actor_scope=actor_scope,
        request_id=request_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    session.add(entry)
    return entry
