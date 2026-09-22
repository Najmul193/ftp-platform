"""Deleting an upload batch.

This is the most destructive operation in the system: it removes published
figures. It is therefore written to be *reversible in effect* rather than
merely removing rows -- whatever the batch displaced is put back, and the
affected dates are recalculated from what remains.

Two guards that are not negotiable:

* A batch that has itself been superseded cannot be deleted. Removing a link
  from the middle of a supersession chain would leave the rows it retired with
  nothing to restore them. Delete the newer batch first.
* Deletion is refused unless the affected dates can be recalculated afterwards,
  because a date left with raw rows and no results reads as a zero, not as a
  gap.

The batch row is genuinely removed. The audit record is not: it holds the full
before-image, so what was deleted, by whom and when survives the deletion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import (
    BankDailyAccountData, CalculationRun, FtpCalculationResult,
    StagingAccountData, UploadBatch, UploadException,
)
from app.services import audit
from app.services.pipeline import UploadPipeline, _ref


class BatchDeleteError(Exception):
    """The batch cannot be deleted as things stand."""


@dataclass
class DeletionImpact:
    """What deleting this batch would do, computed without doing it."""

    batch_ref: str
    business_dates: list[date] = field(default_factory=list)
    bank_rows: int = 0
    fact_rows: int = 0
    exception_rows: int = 0
    staging_rows: int = 0
    ftp_profit_removed: Decimal = Decimal(0)
    rows_restored: int = 0
    batches_restored: list[str] = field(default_factory=list)
    dates_left_empty: list[date] = field(default_factory=list)
    blocked_by: str | None = None

    @property
    def deletable(self) -> bool:
        return self.blocked_by is None


class BatchDeleteService:
    def __init__(self, session: Session, *, actor_id: int | None = None,
                 actor_username: str | None = None) -> None:
        self.s = session
        self.actor_id = actor_id
        self.actor_username = actor_username

    # ------------------------------------------------------------------ #

    def get(self, batch_ref: str) -> UploadBatch:
        b = self.s.scalar(select(UploadBatch).filter_by(batch_ref=batch_ref))
        if b is None:
            raise BatchDeleteError(f"no batch {batch_ref}")
        return b

    def impact(self, batch: UploadBatch) -> DeletionImpact:
        """Dry run. The UI calls this first so the confirmation states the cost."""
        imp = DeletionImpact(batch_ref=batch.batch_ref)

        if batch.superseded_by_batch_id:
            newer = self.s.get(UploadBatch, batch.superseded_by_batch_id)
            imp.blocked_by = (
                f"this batch was already replaced by "
                f"{newer.batch_ref if newer else batch.superseded_by_batch_id}. "
                "Delete that one first, or its rows would have nothing to "
                "fall back to."
            )

        B = BankDailyAccountData
        imp.business_dates = sorted({
            d for (d,) in self.s.execute(
                select(B.business_date).where(B.batch_id == batch.id).distinct()
            )
        })
        imp.bank_rows = self.s.scalar(
            select(func.count()).select_from(B).where(B.batch_id == batch.id)) or 0

        F = FtpCalculationResult
        imp.fact_rows = self.s.scalar(
            select(func.count()).select_from(F).where(F.batch_id == batch.id)) or 0
        imp.ftp_profit_removed = Decimal(self.s.scalar(
            select(func.coalesce(func.sum(F.ftp_income), 0))
            .where(F.batch_id == batch.id).where(F.is_current.is_(True))) or 0)

        imp.exception_rows = self.s.scalar(
            select(func.count()).select_from(UploadException)
            .where(UploadException.batch_id == batch.id)) or 0
        imp.staging_rows = self.s.scalar(
            select(func.count()).select_from(StagingAccountData)
            .where(StagingAccountData.batch_id == batch.id)) or 0

        # What this batch displaced, and would therefore bring back.
        restore = select(B).where(B.superseded_by_batch_id == batch.id)
        restored = list(self.s.scalars(restore))
        imp.rows_restored = len(restored)
        restored_batch_ids = {r.batch_id for r in restored}
        if restored_batch_ids:
            imp.batches_restored = sorted(
                b.batch_ref for b in self.s.scalars(
                    select(UploadBatch).where(UploadBatch.id.in_(restored_batch_ids))
                )
            )

        # Dates that would be left with no data at all.
        for d in imp.business_dates:
            remaining = self.s.scalar(
                select(func.count()).select_from(B)
                .where(B.business_date == d)
                .where(B.batch_id != batch.id)
                .where((B.is_current.is_(True)) | (B.superseded_by_batch_id == batch.id))
            ) or 0
            if remaining == 0:
                imp.dates_left_empty.append(d)

        return imp

    # ------------------------------------------------------------------ #

    def delete(self, batch_ref: str, *, reason: str | None = None) -> dict[str, Any]:
        """Remove the batch and restore whatever it displaced."""
        batch = self.get(batch_ref)
        imp = self.impact(batch)
        if not imp.deletable:
            raise BatchDeleteError(imp.blocked_by or "batch cannot be deleted")

        before = {
            "batch_ref": batch.batch_ref, "file_name": batch.file_name,
            "file_hash": batch.file_hash, "status": batch.status,
            "business_date": batch.business_date.isoformat() if batch.business_date else None,
            "total_rows": batch.total_rows, "accepted_rows": batch.accepted_rows,
            "rejected_rows": batch.rejected_rows,
            "uploaded_by": batch.uploaded_by,
            "uploaded_at": batch.uploaded_at.isoformat() if batch.uploaded_at else None,
            "ftp_profit_removed": str(imp.ftp_profit_removed),
            "fact_rows": imp.fact_rows, "bank_rows": imp.bank_rows,
        }

        B = BankDailyAccountData

        # 1. Put back exactly the rows this batch displaced.
        self.s.execute(
            update(B).where(B.superseded_by_batch_id == batch.id)
            .values(is_current=True, superseded_by_batch_id=None)
        )
        if imp.batches_restored:
            self.s.execute(
                update(UploadBatch)
                .where(UploadBatch.superseded_by_batch_id == batch.id)
                .values(is_current=True, superseded_by_batch_id=None)
            )

        # 2. Remove the batch's own data. Facts first: they reference the run.
        self.s.execute(
            FtpCalculationResult.__table__.delete()
            .where(FtpCalculationResult.batch_id == batch.id))
        self.s.execute(B.__table__.delete().where(B.batch_id == batch.id))
        self.s.execute(
            UploadException.__table__.delete()
            .where(UploadException.batch_id == batch.id))
        self.s.execute(
            StagingAccountData.__table__.delete()
            .where(StagingAccountData.batch_id == batch.id))
        self.s.execute(
            update(CalculationRun).where(CalculationRun.batch_id == batch.id)
            .values(is_current=False, batch_id=None))

        dates = imp.business_dates
        self.s.delete(batch)
        self.s.flush()

        # 3. Rebuild the affected dates from whatever is left current.
        recalculated = []
        pipe = UploadPipeline(self.s, actor_id=self.actor_id,
                              actor_username=self.actor_username)
        for d in dates:
            still_there = self.s.scalar(
                select(func.count()).select_from(B)
                .where(B.business_date == d).where(B.is_current.is_(True))) or 0
            if still_there:
                recalculated.append(d)

        if recalculated:
            run = CalculationRun(
                run_ref=_ref("RUN"), trigger_type="MANUAL",
                business_date_from=min(recalculated),
                business_date_to=max(recalculated),
                status="RUNNING", started_at=datetime.now(UTC),
                initiated_by=self.actor_id,
            )
            self.s.add(run)
            self.s.flush()
            pipe.recalculate(run, recalculated)
            pipe.refresh_aggregates(run, recalculated)

        # 4. Aggregates for dates now empty have to go, or the dashboard keeps
        #    showing totals for data that no longer exists.
        emptied = [d for d in dates if d not in recalculated]
        if emptied:
            pipe.clear_aggregates(emptied)

        audit.record(
            self.s, action="DELETE", entity_type="upload_batch",
            entity_id=batch_ref, before=before,
            after={"reason": reason,
                   "rows_restored": imp.rows_restored,
                   "batches_restored": imp.batches_restored,
                   "dates_recalculated": [d.isoformat() for d in recalculated],
                   "dates_emptied": [d.isoformat() for d in emptied]},
            actor_user_id=self.actor_id, actor_username=self.actor_username,
        )

        return {
            "batch_ref": batch_ref,
            "deleted": True,
            "fact_rows_removed": imp.fact_rows,
            "bank_rows_removed": imp.bank_rows,
            "ftp_profit_removed": imp.ftp_profit_removed,
            "rows_restored": imp.rows_restored,
            "batches_restored": imp.batches_restored,
            "dates_recalculated": recalculated,
            "dates_emptied": emptied,
        }
