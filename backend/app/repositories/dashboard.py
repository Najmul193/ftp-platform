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

from sqlalchemy import Select, and_, case, func, select
from sqlalchemy.orm import Session

from app.domain.scope import ScopeFilter, intersect_requested
from app.domain.types import Side
from app.repositories.cache import cached
from app.models import (
    AggDailyBranch, AggDailyBranchProduct, AggDailyCategory, Branch,
    FtpCalculationResult, Product,
)

ZERO = Decimal(0)


def _d_or_zero(v: Any) -> Decimal:
    return Decimal(v) if v is not None else ZERO


def _plain_key(v: Any) -> Any:
    """A group key the response model can carry.

    Grouping on a date or an enum yields a Python object; SeriesPoint.key is a
    string or an int. The aggregate paths stringified these at each call site
    and the fact paths did not, which surfaced as a response-validation error
    rather than as anything a reader could act on.
    """
    if isinstance(v, date):
        return v.isoformat()
    return v.value if hasattr(v, "value") else v
#: Presentation scale for derived ratios. Division yields the full Decimal
#: context precision, which is meaningless noise on a percentage.
RATE_Q = Decimal("0.0001")


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

    @property
    def needs_fact_grain(self) -> bool:
        """True when only the fact table can answer.

        `ftp_sign` and `account_no` are predicates on individual accounts.
        No aggregate carries an account, so these cannot be expressed at any
        pre-aggregated grain -- and a filter that cannot be applied must not be
        quietly dropped, or the page shows a chip saying NEGATIVE FTP above
        totals covering the whole book.
        """
        return bool(self.account_no) or self.ftp_sign in ("POSITIVE", "NEGATIVE")


def _apply_scope(stmt: Select, model: Any, scope: ScopeFilter) -> Select:
    """The mandatory predicate. HO adds none; anything else is an explicit set."""
    if scope.unrestricted:
        return stmt
    if not scope.branch_ids:
        # An empty non-unrestricted scope must match nothing, not everything.
        return stmt.where(model.branch_id.in_([-1]))
    return stmt.where(model.branch_id.in_(scope.branch_ids))


def _apply_filters(stmt: Select, model: Any, f: Filters) -> Select:
    """Non-branch predicates only.

    Branch, division, district and category are deliberately NOT applied here.
    They are resolved into the effective scope by `DashboardRepo._scope_for`, so
    that asking for a branch outside your scope is a 403 rather than a silently
    empty result. Applying them here as well would restore the leak.
    """
    if f.date_from:
        stmt = stmt.where(model.business_date >= f.date_from)
    if f.date_to:
        stmt = stmt.where(model.business_date <= f.date_to)
    if f.product_codes and hasattr(model, "product_code"):
        stmt = stmt.where(model.product_code.in_(f.product_codes))
    if f.side is not None and hasattr(model, "side"):
        stmt = stmt.where(model.side == f.side)
    return stmt


#: Additive measures. Weighted-average components are summed then divided at the
#: very end -- never averaged from pre-averaged values.
_MEASURES = (
    "asset_balance", "liability_balance", "interest_receivable", "interest_payable",
    "asset_ftp_profit", "liability_ftp_profit", "net_ftp_profit",
    "roi_x_balance", "ftp_rate_x_balance",
    "benchmark_contrib", "roi_contrib", "liquidity_contrib", "other_contrib",
    "total_balance",
)


#: Per-day measures: each source measure divided by that day's income divisor
#: (36,500 for ACT/365, 36,000 for ACT/360) *before* summing. A `x_balance` or
#: `contrib` measure becomes income; a balance becomes the base that annualises
#: an income into a percentage (rate = income / balance_pd). Dividing each day
#: by its own divisor is what keeps a window spanning a basis change exact; on
#: a single basis they reduce to the familiar `SUM(x) / 36500`.
_PER_DAY = (
    "ftp_rate_x_balance", "roi_x_balance",
    "benchmark_contrib", "roi_contrib", "liquidity_contrib", "other_contrib",
    "asset_balance", "liability_balance", "total_balance",
)
PER_DAY_MEASURES = tuple(f"{m}_pd" for m in _PER_DAY)
#: Every additive measure the helpers below return.
ALL_MEASURES = _MEASURES + PER_DAY_MEASURES


def _sums(model: Any) -> list:
    return [func.coalesce(func.sum(getattr(model, m)), 0).label(m) for m in _MEASURES] + [
        func.coalesce(func.sum(getattr(model, m) / model.day_divisor), 0).label(f"{m}_pd")
        for m in _PER_DAY
    ] + [
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


#: The same measures as `_MEASURES`, expressed against the fact table. Used
#: only when a filter cannot be answered from an aggregate; the aggregate path
#: stays the default because it is what keeps dashboard cost flat.
def _fact_sums() -> list:
    F = FtpCalculationResult
    asset, liab = Side.ASSET, Side.LIABILITY
    signed_bm = case((F.side == liab, F.benchmark_rate * F.balance),
                     else_=-F.benchmark_rate * F.balance)
    signed_roi = case((F.side == liab, -F.normalized_roi * F.balance),
                      else_=F.normalized_roi * F.balance)
    # (per-row value, row filter) for each measure that has a per-day form.
    per_row = {
        "roi_x_balance": (F.normalized_roi * F.balance, None),
        "ftp_rate_x_balance": (F.ftp_rate * F.balance, None),
        "benchmark_contrib": (signed_bm, None),
        "roi_contrib": (signed_roi, None),
        "liquidity_contrib": (-F.liquidity_cost * F.balance, None),
        "other_contrib": (-F.other_cost * F.balance, None),
        "asset_balance": (F.balance, F.side == asset),
        "liability_balance": (F.balance, F.side == liab),
        "total_balance": (F.balance, None),
    }

    def total(expr, where, label):
        agg = func.sum(expr)
        if where is not None:
            agg = agg.filter(where)
        return func.coalesce(agg, 0).label(label)

    return [
        total(F.balance, F.side == asset, "asset_balance"),
        total(F.balance, F.side == liab, "liability_balance"),
        total(F.customer_interest, F.side == asset, "interest_receivable"),
        total(F.customer_interest, F.side == liab, "interest_payable"),
        total(F.asset_ftp_profit, None, "asset_ftp_profit"),
        total(F.liability_ftp_profit, None, "liability_ftp_profit"),
        total(F.ftp_income, None, "net_ftp_profit"),
        *(total(e, w, m) for m, (e, w) in per_row.items()
          if m not in ("asset_balance", "liability_balance")),
        *(total(e / F.day_divisor, w, f"{m}_pd") for m, (e, w) in per_row.items()),
        func.count().label("account_count"),
        func.coalesce(func.count().filter(F.negative_ftp_flag.is_(True)), 0).label("negative_ftp_count"),
    ]


class DashboardRepo:
    def __init__(self, session: Session, scope: ScopeFilter) -> None:
        self.s = session
        self.scope = scope

    # ------------------------------------------------------------------ #

    def _scope_for(self, f: Filters) -> ScopeFilter:
        """Intersect the caller's scope with the requested branch selection.

        Every branch-shaped filter -- explicit branch ids, a division, a
        district, a category -- is resolved to a branch set and intersected
        here. Asking for something outside your scope raises `ScopeViolation`
        (403); it does not quietly return zeros, because a zero would confirm
        the requested filter was well-formed and let a branch user map the
        hierarchy by watching totals move.

        A filter that legitimately matches no branch is different: that is an
        honest empty result, not a violation.
        """
        requested: set[int] | None = set(f.branch_ids) if f.branch_ids else None

        if f.division_id or f.district_id or f.branch_category:
            stmt = select(Branch.id)
            if f.division_id:
                stmt = stmt.where(Branch.division_id == f.division_id)
            if f.district_id:
                stmt = stmt.where(Branch.district_id == f.district_id)
            if f.branch_category:
                stmt = stmt.where(Branch.category == f.branch_category)
            resolved = set(self.s.scalars(stmt))
            requested = resolved if requested is None else (requested & resolved)

        if requested is None:
            return self.scope
        if not requested:
            return ScopeFilter(unrestricted=False, branch_ids=frozenset())
        return intersect_requested(self.scope, requested)

    # ------------------------------------------------------------------ #

    @cached
    def kpis(self, f: Filters) -> dict[str, Any]:
        if f.needs_fact_grain:
            return self._fact_kpis(f)
        model = _grain(f)
        stmt = _apply_filters(_apply_scope(select(*_sums(model)), model, self._scope_for(f)), model, f)
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
                model, self._scope_for(f),
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
        ratio = (
            (net / total_balance * Decimal(365) * Decimal(100)).quantize(RATE_Q)
            if total_balance else ZERO
        )

        return {
            **data,
            "branch_count": branches or 0,
            "product_count": products,
            "day_count": days or 0,
            "ftp_over_balance_pct": ratio,
        }

    # ------------------------------------------------------------------ #

    def _names(self) -> dict[str, dict[int, str]]:
        """Readable names for the id-keyed levels, fetched once per call.

        At 8 divisions and 64 districts these are small enough to resolve in
        one pass rather than joining them onto an aggregate query.
        """
        from app.models import Branch, District, Division
        divisions = {d.id: d.name for d in self.s.scalars(select(Division))}
        districts = {d.id: d.name for d in self.s.scalars(select(District))}
        parent = {d.id: divisions.get(d.division_id, "")
                  for d in self.s.scalars(select(District))}
        branch_parent = {
            b.branch_code: (districts.get(b.district_id, ""), b.branch_name)
            for b in self.s.scalars(select(Branch))
        }
        return {"division": divisions, "district": districts,
                "district_parent": parent, "branch": branch_parent}

    def _fact_where(self, f: Filters):
        """Scope-and-filter predicate for the fact table."""
        F = FtpCalculationResult
        conds = [F.is_current.is_(True)]
        if f.date_from:
            conds.append(F.business_date >= f.date_from)
        if f.date_to:
            conds.append(F.business_date <= f.date_to)
        if f.product_codes:
            conds.append(F.product_code.in_(f.product_codes))
        if f.side is not None:
            conds.append(F.side == f.side)
        if f.account_no:
            conds.append(F.account_no.like(f"%{f.account_no}%"))
        if f.ftp_sign == "NEGATIVE":
            conds.append(F.negative_ftp_flag.is_(True))
        elif f.ftp_sign == "POSITIVE":
            conds.append(F.negative_ftp_flag.is_(False))
        scope = self._scope_for(f)
        if not scope.unrestricted:
            conds.append(F.branch_id.in_(scope.branch_ids or [-1]))
        return and_(*conds)

    def _row_to_measures(self, r) -> dict[str, Any]:
        bal = _d_or_zero(r.total_balance)
        return {
            **{m: _d_or_zero(getattr(r, m)) for m in _MEASURES},
            "account_count": r.account_count or 0,
            "negative_ftp_count": r.negative_ftp_count or 0,
            "avg_ftp_rate": ((_d_or_zero(r.ftp_rate_x_balance) / bal).quantize(RATE_Q)
                             if bal else ZERO),
        }

    def _fact_kpis(self, f: Filters) -> dict[str, Any]:
        F = FtpCalculationResult
        where = self._fact_where(f)
        r = self.s.execute(select(*_fact_sums()).where(where)).one()
        data = self._row_to_measures(r)
        data.pop("avg_ftp_rate", None)

        branches, days = self.s.execute(
            select(func.count(func.distinct(F.branch_id)),
                   func.count(func.distinct(F.business_date))).where(where)
        ).one()
        products = self.s.scalar(
            select(func.count(func.distinct(F.product_id))).where(where)) or 0

        total_balance = data["total_balance"] or ZERO
        net = data["net_ftp_profit"] or ZERO
        return {
            **data,
            "branch_count": branches or 0,
            "product_count": products,
            "day_count": days or 0,
            "ftp_over_balance_pct": (
                (net / total_balance * Decimal(365) * Decimal(100)).quantize(RATE_Q)
                if total_balance else ZERO
            ),
        }

    def _fact_breakdown(self, f: Filters, keys: Sequence, labels,
                        parents=None, order_by=None, codes=None) -> list[dict]:
        where = self._fact_where(f)
        stmt = (select(*keys, *_fact_sums()).where(where)
                .group_by(*keys)
                .order_by(order_by if order_by is not None
                          else func.sum(FtpCalculationResult.ftp_income).desc()))
        out = []
        for r in self.s.execute(stmt):
            out.append({
                "key": _plain_key(r[0]),
                "label": labels(r),
                "code": codes(r) if codes else None,
                "parent_label": parents(r) if parents else None,
                **self._row_to_measures(r),
            })
        return out

    def _breakdown(self, f: Filters, model: Any, keys: Sequence, labels,
                   parents=None, codes=None) -> list[dict]:
        stmt = _apply_filters(
            _apply_scope(select(*keys, *_sums(model)), model, self._scope_for(f)), model, f
        )
        stmt = stmt.group_by(*keys).order_by(func.sum(model.net_ftp_profit).desc())
        out = []
        for r in self.s.execute(stmt):
            bal = r.total_balance or ZERO
            out.append({
                "key": r[0],
                "label": labels(r),
                # The code on its own, for callers with no room for the name.
                "code": codes(r) if codes else None,
                # Which division a district sits in, or which district a branch
                # does. At 64 districts a bare name is ambiguous; the parent is
                # what makes a row identifiable in a long list.
                "parent_label": parents(r) if parents else None,
                "asset_ftp_profit": r.asset_ftp_profit or ZERO,
                "liability_ftp_profit": r.liability_ftp_profit or ZERO,
                "net_ftp_profit": r.net_ftp_profit or ZERO,
                "asset_balance": r.asset_balance or ZERO,
                "liability_balance": r.liability_balance or ZERO,
                "total_balance": bal,
                "account_count": r.account_count or 0,
                "negative_ftp_count": r.negative_ftp_count or 0,
                "avg_ftp_rate": (
                    ((r.ftp_rate_x_balance or ZERO) / bal).quantize(RATE_Q)
                    if bal else ZERO
                ),
            })
        return out

    @cached
    def by_branch(self, f: Filters) -> list[dict]:
        names = self._names()["branch"]
        label = lambda r: f"{r[1]} {names.get(r[1], ('', ''))[1]}".strip()  # noqa: E731
        parent = lambda r: names.get(r[1], ("", ""))[0] or None            # noqa: E731
        code = lambda r: r[1]                                              # noqa: E731
        if f.needs_fact_grain:
            F = FtpCalculationResult
            return self._fact_breakdown(
                f, [F.branch_id, F.branch_code], label, parent, codes=code)
        m = _grain(f)
        return self._breakdown(
            f, m, [m.branch_id, m.branch_code], label, parent, codes=code)

    @cached
    def by_division(self, f: Filters) -> list[dict]:
        """The coarsest rollup -- around eight rows, so it charts directly."""
        names = self._names()["division"]
        label = lambda r: names.get(r[0], f"Division {r[0]}")  # noqa: E731
        if f.needs_fact_grain:
            return self._fact_breakdown(
                f, [FtpCalculationResult.division_id], label)
        m = _grain(f)
        return self._breakdown(f, m, [m.division_id], label)

    @cached
    def by_district(self, f: Filters) -> list[dict]:
        """Around sixty rows: readable as a ranked table, not as a bar chart."""
        n = self._names()
        label = lambda r: n["district"].get(r[0], f"District {r[0]}")   # noqa: E731
        parent = lambda r: n["district_parent"].get(r[0]) or None       # noqa: E731
        if f.needs_fact_grain:
            return self._fact_breakdown(
                f, [FtpCalculationResult.district_id], label, parent)
        m = _grain(f)
        return self._breakdown(f, m, [m.district_id], label, parent)

    @cached
    def by_product(self, f: Filters) -> list[dict]:
        if f.needs_fact_grain:
            F = FtpCalculationResult
            return self._fact_breakdown(f, [F.product_id, F.product_code], lambda r: r[1])
        m = AggDailyBranchProduct
        return self._breakdown(f, m, [m.product_id, m.product_code], lambda r: r[1])

    @cached
    def by_category(self, f: Filters) -> list[dict]:
        if f.needs_fact_grain:
            return self._fact_breakdown(
                f, [FtpCalculationResult.branch_category],
                lambda r: (r[0].value if hasattr(r[0], "value") else str(r[0]))
                          .replace("_", " ").title(),
            )
        scope = self._scope_for(f)
        # AggDailyCategory has no branch_id and therefore cannot carry a scope
        # predicate. It is only safe when nothing needs scoping at all.
        unscoped_ok = (
            scope.unrestricted
            and not f.needs_product_grain
            and not (f.branch_ids or f.division_id or f.district_id or f.branch_category)
        )
        # A product or side filter needs the grain that carries product, side
        # AND category together -- neither of the coarser aggregates has all
        # three, so both used to drop the filter and answer for the whole book.
        m = (AggDailyCategory if unscoped_ok
             else AggDailyBranchProduct if f.needs_product_grain
             else AggDailyBranch)
        key = m.branch_category
        stmt = _apply_filters(select(key, *_sums(m)), m, f)
        if m is not AggDailyCategory:
            stmt = _apply_scope(stmt, m, scope)
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
                "avg_ftp_rate": (
                    ((r.ftp_rate_x_balance or ZERO) / bal).quantize(RATE_Q)
                    if bal else ZERO
                ),
            })
        return out

    @cached
    def trend(self, f: Filters) -> list[dict]:
        if f.needs_fact_grain:
            F = FtpCalculationResult
            return self._fact_breakdown(
                f, [F.business_date], lambda r: r[0].isoformat(),
                order_by=F.business_date,
            )
        m = _grain(f)
        stmt = _apply_filters(
            _apply_scope(select(m.business_date, *_sums(m)), m, self._scope_for(f)), m, f
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
                "avg_ftp_rate": (
                    ((r.ftp_rate_x_balance or ZERO) / bal).quantize(RATE_Q)
                    if bal else ZERO
                ),
            })
        return out

    @cached
    def heatmap(self, f: Filters) -> list[dict]:
        if f.needs_fact_grain:
            F = FtpCalculationResult
            rows = self.s.execute(
                select(F.branch_code, F.product_code,
                       func.coalesce(func.sum(F.ftp_income), 0),
                       func.coalesce(func.sum(F.balance), 0))
                .where(self._fact_where(f))
                .group_by(F.branch_code, F.product_code)
            ).all()
            return [{"branch_code": r[0], "product_code": r[1],
                     "net_ftp_profit": _d_or_zero(r[2]),
                     "total_balance": _d_or_zero(r[3])} for r in rows]
        m = AggDailyBranchProduct
        stmt = _apply_filters(
            _apply_scope(
                select(m.branch_code, m.product_code,
                       func.coalesce(func.sum(m.net_ftp_profit), 0),
                       func.coalesce(func.sum(m.total_balance), 0)),
                m, self._scope_for(f),
            ), m, f
        ).group_by(m.branch_code, m.product_code)
        return [
            {"branch_code": r[0], "product_code": r[1],
             "net_ftp_profit": r[2] or ZERO, "total_balance": r[3] or ZERO}
            for r in self.s.execute(stmt)
        ]

    # ------------------------------------------------------------------ #

    @cached
    def accounts(self, f: Filters, *, limit: int = 50, offset: int = 0,
                 order: str = "ftp_income", desc: bool = True) -> tuple[list, int]:
        """The one path that reads facts. Always bounded and paginated."""
        F = FtpCalculationResult
        conds = [F.is_current.is_(True)]
        if f.date_from:
            conds.append(F.business_date >= f.date_from)
        if f.date_to:
            conds.append(F.business_date <= f.date_to)
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
        scope = self._scope_for(f)
        if not scope.unrestricted:
            conds.append(F.branch_id.in_(scope.branch_ids or [-1]))

        where = and_(*conds)
        total = self.s.scalar(select(func.count()).select_from(F).where(where)) or 0

        col = getattr(F, order, F.ftp_income)
        rows = self.s.scalars(
            select(F).where(where)
            # A full key as tie-breaker: without the date and branch, equal
            # values on different days fall in arbitrary order and paging can
            # show a row twice while skipping another.
            .order_by(col.desc() if desc else col.asc(), F.business_date.desc(),
                      F.branch_code, F.account_no)
            .limit(min(limit, 500)).offset(offset)
        ).all()
        return list(rows), total

    def latest_business_date(self) -> date | None:
        stmt = _apply_scope(
            select(func.max(AggDailyBranch.business_date)), AggDailyBranch, self.scope
        )  # unfiltered: "latest data I can see", independent of the current view
        return self.s.scalar(stmt)
