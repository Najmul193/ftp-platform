"""System routes: health, and the data-version signal the UI watches."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.api.deps import DbDep, ScopeDep, UserDep, require
from app.models import (
    AggDailyBranch, BankDailyAccountData, CalculationRun, FtpCalculationResult,
    UploadBatch,
)
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


@router.get("/reconciliation", dependencies=[Depends(require("UPLOAD_VIEW"))])
def reconciliation(db: DbDep, _user: UserDep, limit: int = Query(400, ge=1, le=2000)):
    """Check the three layers against each other, per business date.

    Committed bank rows should produce exactly one current fact each, and the
    aggregates should carry the same count and the same profit. Nothing in the
    pipeline guarantees that from the outside -- it is an invariant maintained
    by code, which means it is worth testing rather than assuming.

    Returns only the dates that disagree, so a healthy system answers with an
    empty list.
    """
    B, F, A = BankDailyAccountData, FtpCalculationResult, AggDailyBranch

    bank = dict(db.execute(
        select(B.business_date, func.count())
        .where(B.is_current.is_(True)).group_by(B.business_date)
    ).all())
    facts = {
        d: (n, p) for d, n, p in db.execute(
            select(F.business_date, func.count(), func.coalesce(func.sum(F.ftp_income), 0))
            .where(F.is_current.is_(True)).group_by(F.business_date)
        ).all()
    }
    agg = {
        d: (n or 0, p or 0) for d, n, p in db.execute(
            select(A.business_date, func.sum(A.account_count),
                   func.coalesce(func.sum(A.net_ftp_profit), 0))
            .group_by(A.business_date)
        ).all()
    }

    problems = []
    for d in sorted(set(bank) | set(facts) | set(agg), reverse=True)[:limit]:
        b = bank.get(d, 0)
        fn, fp = facts.get(d, (0, 0))
        an, ap = agg.get(d, (0, 0))
        issues = []
        if b != fn:
            issues.append(f"{b} committed rows but {fn} calculated")
        if fn != an:
            issues.append(f"{fn} calculated rows but aggregates count {an}")
        # Aggregates sum per-row income, so they agree to the cent or not at all.
        if abs((fp or 0) - (ap or 0)) > 0.01:
            issues.append(f"profit {fp} in facts against {ap} in aggregates")
        if issues:
            problems.append({
                "business_date": d, "bank_rows": b, "fact_rows": fn,
                "aggregate_rows": an, "fact_profit": fp, "aggregate_profit": ap,
                "issues": issues,
            })

    return {
        "dates_checked": len(set(bank) | set(facts) | set(agg)),
        "consistent": not problems,
        "problem_count": len(problems),
        "problems": problems,
    }
