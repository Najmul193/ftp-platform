"""Analytics routes -- the analytical surface of the product.

Every endpoint takes the same filter block as the dashboard routes and is
scope-filtered through the same guard, so an analysis can never show a user
more than the plain dashboard would.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbDep, ScopeDep, require
from app.api.v1.dashboard import FiltersDep
from app.repositories.analytics import AnalyticsRepo

router = APIRouter(prefix="/analytics", tags=["analytics"])

_view = Depends(require("DASH_VIEW"))
Dim = Literal["branch", "product", "category", "division", "district"]


@router.get("/summary", dependencies=[_view])
def summary(db: DbDep, scope: ScopeDep, f: FiltersDep):
    """Headline KPIs with the change against the preceding window of equal length."""
    return AnalyticsRepo(db, scope).kpis_with_comparison(f)


@router.get("/trend", dependencies=[_view])
def trend(db: DbDep, scope: ScopeDep, f: FiltersDep,
          ma_window: int = Query(7, ge=2, le=90)):
    """Daily series with moving average, cumulative total and volatility."""
    return AnalyticsRepo(db, scope).trend_enriched(f, ma_window=ma_window)


@router.get("/variance-bridge", dependencies=[_view])
def variance_bridge(db: DbDep, scope: ScopeDep, f: FiltersDep,
                    by: Dim = "product"):
    """Why profit moved: volume effect vs rate effect vs interaction.

    The three effects sum to the total change with no residual, and the residual
    is returned so that can be checked rather than assumed.
    """
    return AnalyticsRepo(db, scope).variance_bridge(f, by=by)


@router.get("/spread-waterfall", dependencies=[_view])
def spread_waterfall(db: DbDep, scope: ScopeDep, f: FiltersDep,
                     by: Dim | None = None):
    """Where the margin comes from: benchmark, customer rate, liquidity, other."""
    return AnalyticsRepo(db, scope).spread_waterfall(f, by=by)


@router.get("/concentration", dependencies=[_view])
def concentration(db: DbDep, scope: ScopeDep, f: FiltersDep, by: Dim = "branch"):
    """Pareto curve and Herfindahl-Hirschman index for the chosen dimension."""
    return AnalyticsRepo(db, scope).concentration(f, by=by)


@router.get("/movers", dependencies=[_view])
def movers(db: DbDep, scope: ScopeDep, f: FiltersDep, by: Dim = "branch",
           limit: int = Query(5, ge=1, le=25)):
    """Biggest improvers and deteriorators against the prior window."""
    return AnalyticsRepo(db, scope).movers(f, by=by, limit=limit)


@router.get("/rankings", dependencies=[_view])
def rankings(db: DbDep, scope: ScopeDep, f: FiltersDep, by: Dim = "branch"):
    """League table on annualised yield, with quartiles and percentiles."""
    return AnalyticsRepo(db, scope).rankings(f, by=by)


@router.get("/rate-distribution", dependencies=[_view])
def rate_distribution(db: DbDep, scope: ScopeDep, f: FiltersDep,
                      buckets: int = Query(12, ge=4, le=40)):
    """Balance-weighted histogram of account-level FTP rate."""
    return AnalyticsRepo(db, scope).rate_distribution(f, buckets=buckets)


@router.get("/outliers", dependencies=[Depends(require("ACCOUNT_DRILLDOWN"))])
def outliers(db: DbDep, scope: ScopeDep, f: FiltersDep,
             z: float = Query(3.0, ge=1.0, le=10.0),
             limit: int = Query(25, ge=1, le=200)):
    """Accounts priced unusually relative to others of the same product."""
    return AnalyticsRepo(db, scope).outliers(f, z_threshold=z, limit=limit)


@router.get("/leakage", dependencies=[_view])
def leakage(db: DbDep, scope: ScopeDep, f: FiltersDep,
            limit: int = Query(20, ge=1, le=200)):
    """Negative-FTP analysis: where the book loses, and the size of the prize."""
    return AnalyticsRepo(db, scope).leakage(f, limit=limit)


@router.get("/scatter", dependencies=[_view])
def scatter(db: DbDep, scope: ScopeDep, f: FiltersDep, by: Dim = "branch"):
    """Balance against yield, quadranted on the medians."""
    return AnalyticsRepo(db, scope).scatter(f, by=by)


@router.get("/balance-sheet", dependencies=[_view])
def balance_sheet(db: DbDep, scope: ScopeDep, f: FiltersDep):
    """Asset and liability structure, funding gap and FTP spread."""
    return AnalyticsRepo(db, scope).balance_sheet_structure(f)


@router.get("/headline-performers", dependencies=[_view])
def headline_performers(db: DbDep, scope: ScopeDep, f: FiltersDep):
    """Best and worst on every dimension at once.

    Reports the profit leader and the yield leader separately, because they are
    frequently different segments -- a large book priced thinly tops profit
    while earning a poor spread.
    """
    return AnalyticsRepo(db, scope).headline_performers(f)


@router.get("/leaderboard", dependencies=[_view])
def leaderboard(
    db: DbDep, scope: ScopeDep, f: FiltersDep,
    group: Dim = "division",
    of: Dim = "branch",
    top: int = Query(3, ge=1, le=20),
    metric: Literal["profit", "yield"] = "profit",
):
    """Top performers of one dimension within each group of another.

    For example `group=division&of=branch` gives the best branches in each
    division; `group=category&of=product` gives the best products in each
    branch category.
    """
    return AnalyticsRepo(db, scope).leaderboard(f, group=group, of=of, top=top, metric=metric)


@router.get("/product-leadership", dependencies=[_view])
def product_leadership(db: DbDep, scope: ScopeDep, f: FiltersDep,
                       area: Dim = "district"):
    """Which product leads in each area, its dominance, and its margin."""
    return AnalyticsRepo(db, scope).product_leadership(f, area=area)


@router.get("/nii-reconciliation", dependencies=[_view])
def nii_reconciliation(db: DbDep, scope: ScopeDep, f: FiltersDep):
    """Net interest income split between business units and treasury.

    The canonical FTP output: of the margin earned from customers, how much
    belongs to the units that wrote the business and how much to the book that
    funded it.
    """
    return AnalyticsRepo(db, scope).nii_reconciliation(f)


@router.get("/banking-ratios", dependencies=[_view])
def banking_ratios(db: DbDep, scope: ScopeDep, f: FiltersDep):
    """Yield on advances, cost of deposits, NIM, CASA and CD ratio."""
    return AnalyticsRepo(db, scope).banking_ratios(f)


@router.get("/repricing", dependencies=[_view])
def repricing(db: DbDep, scope: ScopeDep, f: FiltersDep,
              limit: int = Query(25, ge=1, le=200)):
    """What the book would earn if underpriced accounts moved to product median."""
    return AnalyticsRepo(db, scope).repricing_opportunity(f, limit=limit)


@router.get("/watchlist", dependencies=[_view])
def watchlist(db: DbDep, scope: ScopeDep, f: FiltersDep):
    """What needs attention today, ordered by money at stake."""
    return AnalyticsRepo(db, scope).watchlist(f)


@router.get("/period-summary", dependencies=[_view])
def period_summary(db: DbDep, scope: ScopeDep, f: FiltersDep):
    """Month-, quarter- and year-to-date totals."""
    return AnalyticsRepo(db, scope).period_summary(f)
