"""System routes: health, and the data-version signal the UI watches."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import DbDep, ScopeDep, UserDep
from app.models import AggDailyBranch, CalculationRun, UploadBatch
from app.repositories.dashboard import DashboardRepo

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/data-version")
def data_version(db: DbDep, scope: ScopeDep, _user: UserDep):
    """A cheap fingerprint of the current state of the data.

    The UI polls this and refetches everything when the fingerprint moves, so a
    dashboard left open picks up an upload made elsewhere without a manual
    reload. It is deliberately a few scalar lookups rather than a digest of the
    facts: it has to stay cheap enough to poll.

    `version` changes whenever a calculation run completes or a batch is
    committed, which between them cover every way the numbers can move --
    a new upload, a restatement, or a recalculation after a rate change.
    """
    run = db.execute(
        select(CalculationRun.id, CalculationRun.run_ref, CalculationRun.finished_at)
        .where(CalculationRun.status == "COMPLETED")
        .order_by(CalculationRun.id.desc()).limit(1)
    ).first()

    batch = db.execute(
        select(UploadBatch.id, UploadBatch.batch_ref, UploadBatch.business_date,
               UploadBatch.completed_at, UploadBatch.status)
        .order_by(UploadBatch.id.desc()).limit(1)
    ).first()

    agg_rows = db.scalar(select(func.count()).select_from(AggDailyBranch)) or 0
    latest = DashboardRepo(db, scope).latest_business_date()

    return {
        # Monotonic and cheap: any new run or batch moves it.
        "version": f"{run.id if run else 0}:{batch.id if batch else 0}:{agg_rows}",
        "last_run_id": run.id if run else None,
        "last_run_ref": run.run_ref if run else None,
        "last_run_at": run.finished_at if run else None,
        "last_batch_ref": batch.batch_ref if batch else None,
        "last_batch_status": batch.status if batch else None,
        "last_batch_at": batch.completed_at if batch else None,
        "latest_business_date": latest,
        "server_time": datetime.now(UTC),
    }
