"""Dashboard routes. Every one is scope-filtered by a required dependency."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbDep, ScopeDep, require
from app.api.schemas import (
    AccountRow, HeatCell, KpiResponse, Page, SeriesPoint,
)
from app.domain.types import Side
from app.repositories.dashboard import DashboardRepo, Filters

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_view = Depends(require("DASH_VIEW"))


def filters(
    date_from: date | None = None,
    date_to: date | None = None,
    branch_id: Annotated[list[int] | None, Query()] = None,
    division_id: int | None = None,
    district_id: int | None = None,
    branch_category: str | None = None,
    product_code: Annotated[list[str] | None, Query()] = None,
    side: Side | None = None,
    account_no: str | None = None,
    ftp_sign: str | None = None,
) -> Filters:
    """The shared filter block, identical across every dashboard endpoint.

    That uniformity is what lets the UI keep filters when moving between tabs
    without per-screen wiring.
    """
    return Filters(
        date_from=date_from, date_to=date_to,
        branch_ids=branch_id or [], division_id=division_id,
        district_id=district_id, branch_category=branch_category,
        product_codes=product_code or [], side=side,
        account_no=account_no, ftp_sign=ftp_sign,
    )


FiltersDep = Annotated[Filters, Depends(filters)]


@router.get("/kpis", response_model=KpiResponse, dependencies=[_view])
def kpis(db: DbDep, scope: ScopeDep, f: FiltersDep) -> KpiResponse:
    repo = DashboardRepo(db, scope)
    data = repo.kpis(f)
    return KpiResponse(**data, as_of=repo.latest_business_date())


@router.get("/trend", response_model=list[SeriesPoint], dependencies=[_view])
def trend(db: DbDep, scope: ScopeDep, f: FiltersDep):
    return DashboardRepo(db, scope).trend(f)


@router.get("/by-branch", response_model=list[SeriesPoint], dependencies=[_view])
def by_branch(db: DbDep, scope: ScopeDep, f: FiltersDep):
    return DashboardRepo(db, scope).by_branch(f)


@router.get("/by-product", response_model=list[SeriesPoint], dependencies=[_view])
def by_product(db: DbDep, scope: ScopeDep, f: FiltersDep):
    return DashboardRepo(db, scope).by_product(f)


@router.get("/by-division", response_model=list[SeriesPoint], dependencies=[_view])
def by_division(db: DbDep, scope: ScopeDep, f: FiltersDep):
    """Division rollup. Few enough rows to chart directly."""
    return DashboardRepo(db, scope).by_division(f)


@router.get("/by-district", response_model=list[SeriesPoint], dependencies=[_view])
def by_district(db: DbDep, scope: ScopeDep, f: FiltersDep):
    """District rollup, each row carrying its division."""
    return DashboardRepo(db, scope).by_district(f)


@router.get("/by-category", response_model=list[SeriesPoint], dependencies=[_view])
def by_category(db: DbDep, scope: ScopeDep, f: FiltersDep):
    return DashboardRepo(db, scope).by_category(f)


@router.get("/heatmap", response_model=list[HeatCell], dependencies=[_view])
def heatmap(db: DbDep, scope: ScopeDep, f: FiltersDep):
    return DashboardRepo(db, scope).heatmap(f)


@router.get("/accounts", response_model=Page,
            dependencies=[Depends(require("ACCOUNT_DRILLDOWN"))])
def accounts(
    db: DbDep, scope: ScopeDep, f: FiltersDep,
    limit: int = Query(50, le=500), offset: int = 0,
    order: str = "ftp_income", desc: bool = True,
) -> Page:
    """Facts, always bounded by scope, a date range and pagination."""
    rows, total = DashboardRepo(db, scope).accounts(
        f, limit=limit, offset=offset, order=order, desc=desc
    )
    return Page(
        items=[
            AccountRow(
                business_date=r.business_date, branch_code=r.branch_code,
                account_no=r.account_no, product_code=r.product_code, side=r.side,
                balance=r.balance, normalized_roi=r.normalized_roi,
                roi_source=r.roi_source.value, benchmark_rate=r.benchmark_rate,
                liquidity_cost=r.liquidity_cost, other_cost=r.other_cost,
                ftp_rate=r.ftp_rate, ftp_income=r.ftp_income,
                customer_interest=r.customer_interest,
                asset_ftp_profit=r.asset_ftp_profit,
                liability_ftp_profit=r.liability_ftp_profit,
                negative_ftp_flag=r.negative_ftp_flag,
            ).model_dump()
            for r in rows
        ],
        total=total, limit=limit, offset=offset,
    )
