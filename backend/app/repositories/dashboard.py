"""Dashboard queries.

Every read here goes against the aggregate tables, never the fact table. That is
what keeps dashboard latency flat as history grows: cost is bounded by aggregate
cardinality rather than by the number of account-days ever loaded.

Account drilldown is the one path that touches facts, and it is always bounded
by a date range, the caller's scope, and mandatory pagination.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Sequence

from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session

from app.domain.scope import ScopeFilter
from app.domain.types import Side
from app.models import (
    AggDailyBranch, AggDailyBranchProduct, AggDailyCategory, Branch,
    FtpCalculationResult, Product,
)

ZERO = Decimal(0)


@dataclass(slots=True)
class Filters:
    """The shared filter block every dashboard endpoint accepts."""

    date_from: date | None = None
    date_to: date | None = None
    branch_ids: list[int] = field(default_factory=list)
    division_id: int | None = None
    district_id: int | None = None
    branch_category: str | None = None
    product_codes: list[str] = field(default_factory=list)
    side: Side | None = None
    account_no: str | None = None
    ftp_sign: str | None = None          # POSITIVE | NEGATIVE

    @property
    def needs_product_grain(self) -> bool:
        return bool(self.product_codes) or self.side is not None


def _apply_scope(stmt: Select, model: Any, scope: ScopeFilter) -> Select:
    """The mandatory predicate. HO adds none; anything else is an explicit set."""
    if scope.unrestricted:
        return stmt
    if not scope.branch_ids:
        # An empty non-unrestricted scope must match nothing, not everything.
        return stmt.where(model.branch_id.in_([-1]))
    return stmt.where(model.branch_id.in_(scope.branch_ids))


def _apply_filters(stmt: Select, model: Any, f: Filters) -> Select:
    if f.date_from:
        stmt = stmt.where(model.business_date >= f.date_from)
    if f.date_to:
        stmt = stmt.where(model.business_date <= f.date_to)
    if f.branch_ids and hasattr(model, "branch_id"):
        stmt = stmt.where(model.branch_id.in_(f.branch_ids))
    if f.division_id and hasattr(model, "division_id"):
        stmt = stmt.where(model.division_id == f.division_id)
    if f.district_id and hasattr(model, "district_id"):
        stmt = stmt.where(model.district_id == f.district_id)
    if f.branch_category and hasattr(model, "branch_category"):
        stmt = stmt.where(model.branch_category == f.branch_category)
    if f.product_codes and hasattr(model, "product_code"):
        stmt = stmt.where(model.product_code.in_(f.product_codes))
    return stmt


#: Additive measures. Weighted-average components are summed then divided at the
#: very end -- never averaged from pre-averaged values.
_MEASURES = (
    "asset_balance", "liability_balance", "interest_receivable", "interest_payable",
    "asset_ftp_profit", "liability_ftp_profit", "net_ftp_profit",
    "roi_x_balance", "ftp_rate_x_balance", "total_balance",
)


def _sums(model: Any) -> list:
    return [func.coalesce(func.sum(getattr(model, m)), 0).label(m) for m in _MEASURES] + [
        func.coalesce(func.sum(model.account_count), 0).label("account_count"),
        func.coalesce(func.sum(model.negative_ftp_count), 0).label("negative_ftp_count"),
    ]


def _grain(f: Filters):
    """Pick the coarsest aggregate that can answer the question.

    Branch grain is smaller; the product grain is only needed when the filter or
    the breakdown mentions a product. At large volume this is the difference
    between scanning branches-per-day and branches x products-per-day.
    """
    return AggDailyBranchProduct if f.needs_product_grain else AggDailyBranch


class DashboardRepo:
    def __init__(self, session: Session, scope: ScopeFilter) -> None:
        self.s = session
        self.scope = scope

    # ------------------------------------------------------------------ #

    def kpis(self, f: Filters) -> dict[str, Any]:
        model = _grain(f)
        stmt = _apply_filters(_apply_scope(select(*_sums(model)), model, self.scope), model, f)
        row = self.s.execute(stmt).one()
        data = {m: (getattr(row, m) or ZERO) for m in _MEASURES}
        data["account_count"] = row.account_count or 0
        data["negative_ftp_count"] = row.negative_ftp_count or 0

        # Distinct counts need their own pass -- they are not additive.
        dstmt = _apply_filters(
            _apply_scope(
                select(
                    func.count(func.distinct(model.branch_id)),
                    func.count(func.distinct(model.business_date)),
                ),
                model, self.scope,
            ),
            model, f,
        )
        branches, days = self.s.execute(dstmt).one()

        pmodel = AggDailyBranchProduct
        pstmt = _apply_filters(
            _apply_scope(select(func.count(func.distinct(pmodel.product_id))),
                         pmodel, self.scope),
            pmodel, f,
        )
        products = self.s.scalar(pstmt) or 0

        total_balance = data["total_balance"] or ZERO
        net = data["net_ftp_profit"] or ZERO
        # Annualised. Numerator and denominator accumulate over the same days,
        # so the ratio is the average daily rate; x365 annualises it. It must
        # NOT additionally be divided by day_count.
        ratio = (net / total_balance * Decimal(365) * Decimal(100)) if total_balance else ZERO

        return {
            **data,
            "branch_count": branches or 0,
            "product_count": products,
            "day_count": days or 0,
            "ftp_over_balance_pct": ratio,
        }

    # ------------------------------------------------------------------ #

    def _breakdown(self, f: Filters, model: Any, keys: Sequence, labels) -> list[dict]:
        stmt = _apply_filters(
            _apply_scope(select(*keys, *_sums(model)), model, self.scope), model, f
        )
        stmt = stmt.group_by(*keys).order_by(func.sum(model.net_ftp_profit).desc())
        out = []
        for r in self.s.execute(stmt):
            bal = r.total_balance or ZERO
            out.append({
                "key": r[0],
                "label": labels(r),
                "asset_ftp_profit": r.asset_ftp_profit or ZERO,
                "liability_ftp_profit": r.liability_ftp_profit or ZERO,
                "net_ftp_profit": r.net_ftp_profit or ZERO,
                "asset_balance": r.asset_balance or ZERO,
                "liability_balance": r.liability_balance or ZERO,
                "total_balance": bal,
                "account_count": r.account_count or 0,
                "negative_ftp_count": r.negative_ftp_count or 0,
                "avg_ftp_rate": ((r.ftp_rate_x_balance or ZERO) / bal) if bal else ZERO,
            })
        return out

    def by_branch(self, f: Filters) -> list[dict]:
        m = _grain(f)
        return self._breakdown(f, m, [m.branch_id, m.branch_code], lambda r: r[1])

    def by_product(self, f: Filters) -> list[dict]:
        m = AggDailyBranchProduct
        return self._breakdown(f, m, [m.product_id, m.product_code], lambda r: r[1])

    def by_category(self, f: Filters) -> list[dict]:
        m = AggDailyCategory if not f.needs_product_grain else AggDailyBranch
        key = m.branch_category
        stmt = _apply_filters(select(key, *_sums(m)), m, f)
        if m is not AggDailyCategory:
            stmt = _apply_scope(stmt, m, self.scope)
        stmt = stmt.group_by(key).order_by(func.sum(m.net_ftp_profit).desc())
        out = []
        for r in self.s.execute(stmt):
            bal = r.total_balance or ZERO
            cat = r[0].value if hasattr(r[0], "value") else str(r[0])
            out.append({
                "key": cat, "label": cat.replace("_", " ").title(),
                "asset_ftp_profit": r.asset_ftp_profit or ZERO,
                "liability_ftp_profit": r.liability_ftp_profit or ZERO,
                "net_ftp_profit": r.net_ftp_profit or ZERO,
                "asset_balance": r.asset_balance or ZERO,
                "liability_balance": r.liability_balance or ZERO,
                "total_balance": bal,
                "account_count": r.account_count or 0,
                "negative_ftp_count": r.negative_ftp_count or 0,
                "avg_ftp_rate": ((r.ftp_rate_x_balance or ZERO) / bal) if bal else ZERO,
            })
        return out

    def trend(self, f: Filters) -> list[dict]:
        m = _grain(f)
        stmt = _apply_filters(
            _apply_scope(select(m.business_date, *_sums(m)), m, self.scope), m, f
        ).group_by(m.business_date).order_by(m.business_date)
        out = []
        for r in self.s.execute(stmt):
            bal = r.total_balance or ZERO
            out.append({
                "key": r[0].isoformat(), "label": r[0].isoformat(),
                "asset_ftp_profit": r.asset_ftp_profit or ZERO,
                "liability_ftp_profit": r.liability_ftp_profit or ZERO,
                "net_ftp_profit": r.net_ftp_profit or ZERO,
                "asset_balance": r.asset_balance or ZERO,
                "liability_balance": r.liability_balance or ZERO,
                "total_balance": bal,
                "account_count": r.account_count or 0,
                "negative_ftp_count": r.negative_ftp_count or 0,
                "avg_ftp_rate": ((r.ftp_rate_x_balance or ZERO) / bal) if bal else ZERO,
            })
        return out

    def heatmap(self, f: Filters) -> list[dict]:
        m = AggDailyBranchProduct
        stmt = _apply_filters(
            _apply_scope(
                select(m.branch_code, m.product_code,
                       func.coalesce(func.sum(m.net_ftp_profit), 0),
                       func.coalesce(func.sum(m.total_balance), 0)),
                m, self.scope,
            ), m, f
        ).group_by(m.branch_code, m.product_code)
        return [
            {"branch_code": r[0], "product_code": r[1],
             "net_ftp_profit": r[2] or ZERO, "total_balance": r[3] or ZERO}
            for r in self.s.execute(stmt)
        ]

    # ------------------------------------------------------------------ #

    def accounts(self, f: Filters, *, limit: int = 50, offset: int = 0,
                 order: str = "ftp_income", desc: bool = True) -> tuple[list, int]:
        """The one path that reads facts. Always bounded and paginated."""
        F = FtpCalculationResult
        conds = [F.is_current.is_(True)]
        if f.date_from:
            conds.append(F.business_date >= f.date_from)
        if f.date_to:
            conds.append(F.business_date <= f.date_to)
        if f.branch_ids:
            conds.append(F.branch_id.in_(f.branch_ids))
        if f.division_id:
            conds.append(F.division_id == f.division_id)
        if f.district_id:
            conds.append(F.district_id == f.district_id)
        if f.branch_category:
            conds.append(F.branch_category == f.branch_category)
        if f.product_codes:
            conds.append(F.product_code.in_(f.product_codes))
        if f.side:
            conds.append(F.side == f.side)
        if f.account_no:
            conds.append(F.account_no.like(f"%{f.account_no}%"))
        if f.ftp_sign == "NEGATIVE":
            conds.append(F.negative_ftp_flag.is_(True))
        elif f.ftp_sign == "POSITIVE":
            conds.append(F.negative_ftp_flag.is_(False))
        if not self.scope.unrestricted:
            conds.append(F.branch_id.in_(self.scope.branch_ids or [-1]))

        where = and_(*conds)
        total = self.s.scalar(select(func.count()).select_from(F).where(where)) or 0

        col = getattr(F, order, F.ftp_income)
        rows = self.s.scalars(
            select(F).where(where)
            .order_by(col.desc() if desc else col.asc(), F.account_no)
            .limit(min(limit, 500)).offset(offset)
        ).all()
        return list(rows), total

    def latest_business_date(self) -> date | None:
        stmt = _apply_scope(
            select(func.max(AggDailyBranch.business_date)), AggDailyBranch, self.scope
        )
        return self.s.scalar(stmt)
