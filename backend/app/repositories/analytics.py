"""Analytical queries -- the part of the product people buy.

Everything here is computed from the additive aggregate components, so each
analysis is exact rather than approximate, and correct at any rollup. The two
that carry the most weight:

* **Variance bridge** -- decomposes a change in FTP profit into volume, rate and
  interaction effects. This is the question treasury actually asks: profit moved,
  was it because balances grew or because spreads changed?

* **Spread waterfall** -- decomposes FTP profit into the four rate components
  that produced it. Exact at every grain, because the aggregates store each
  component *signed* for its side.

Both rest on one identity:

    ftp_income = SUM(balance x ftp_rate) / 36500
               = B x r / 36500          where r is the balance-weighted rate

which is not an approximation: r is defined as SUM(b*rate)/SUM(b), so B*r is
exactly SUM(b*rate).
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import Select, and_, case, func, select
from sqlalchemy.orm import Session

from app.domain.scope import ScopeFilter
from app.domain.types import Side
from app.models import (
    AggDailyBranch, AggDailyBranchProduct, AggDailyProduct,
    FtpCalculationResult,
)
from app.repositories.dashboard import (
    RATE_Q, ZERO, DashboardRepo, Filters, _apply_filters, _apply_scope,
    _fact_sums, _grain, _sums,
)

DAY_BASIS = Decimal(36500)
MONEY_Q = Decimal("0.01")

Dimension = Literal["branch", "product", "category", "division", "district"]


def _d(v: Any) -> Decimal:
    return Decimal(v) if v is not None else ZERO


def _pct(new: Decimal, old: Decimal) -> Decimal | None:
    """Percentage change. None when there is no base to compare against --
    reporting an infinite or 100% jump from zero would be misleading."""
    if not old:
        return None
    return ((new - old) / abs(old) * 100).quantize(RATE_Q)


@dataclass(frozen=True, slots=True)
class Period:
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def prior(self) -> "Period":
        """The immediately preceding window of equal length."""
        length = timedelta(days=self.days)
        return Period(self.start - length, self.start - timedelta(days=1))


class AnalyticsRepo:
    def __init__(self, session: Session, scope: ScopeFilter) -> None:
        self.s = session
        self.scope = scope
        self.dash = DashboardRepo(session, scope)

    # ------------------------------------------------------------------ #
    # Period helpers
    # ------------------------------------------------------------------ #

    def _totals(self, f: Filters):
        """Measures for the whole slice, from whichever grain can answer it.

        `ftp_sign` and `account_no` are predicates on individual accounts, so
        no aggregate can express them. Routing those to the fact table here is
        what stops the analytics answering for the whole book while the page
        displays a chip saying otherwise.
        """
        if f.needs_fact_grain:
            return self.s.execute(
                select(*_fact_sums()).where(self.dash._fact_where(f))
            ).one()
        model = _grain(f)
        return self.s.execute(
            _apply_filters(
                _apply_scope(select(*_sums(model)), model, self.dash._scope_for(f)),
                model, f,
            )
        ).one()

    def _fact_dimension(self, by: Dimension):
        """The fact-table column that stands for each rollup dimension."""
        F = FtpCalculationResult
        return {
            "branch": F.branch_code, "product": F.product_code,
            "category": F.branch_category, "division": F.division_id,
            "district": F.district_id,
        }[by]

    def resolve_period(self, f: Filters) -> Period | None:
        """The window actually covered, filling in open-ended filters."""
        m = _grain(f)
        stmt = _apply_filters(
            _apply_scope(
                select(func.min(m.business_date), func.max(m.business_date)),
                m, self.dash._scope_for(f),
            ), m, f,
        )
        lo, hi = self.s.execute(stmt).one()
        if lo is None:
            return None
        return Period(f.date_from or lo, f.date_to or hi)

    def _window(self, f: Filters, period: Period) -> Filters:
        """Same filters, different window. `Filters` is slotted, so use replace."""
        return replace(f, date_from=period.start, date_to=period.end)

    # ------------------------------------------------------------------ #
    # 1. KPIs with period-over-period comparison
    # ------------------------------------------------------------------ #

    def kpis_with_comparison(self, f: Filters) -> dict[str, Any]:
        """Headline figures plus the change against the preceding window.

        A number without a direction is not an insight, so every KPI carries its
        delta and the window that delta is measured against.
        """
        current = self.dash.kpis(f)
        period = self.resolve_period(f)
        out: dict[str, Any] = {**current, "as_of": self.dash.latest_business_date()}

        if period is None:
            out["comparison"] = None
            return out

        prior_period = period.prior()
        prior = self.dash.kpis(self._window(f, prior_period))

        tracked = (
            "net_ftp_profit", "asset_ftp_profit", "liability_ftp_profit",
            "asset_balance", "liability_balance", "total_balance",
            "interest_receivable", "interest_payable",
        )
        deltas = {}
        for k in tracked:
            now, was = _d(current.get(k)), _d(prior.get(k))
            deltas[k] = {
                "current": now, "prior": was,
                "change": (now - was).quantize(MONEY_Q),
                "change_pct": _pct(now, was),
            }

        out["comparison"] = {
            "current_period": {"start": period.start, "end": period.end,
                               "days": period.days},
            "prior_period": {"start": prior_period.start, "end": prior_period.end,
                             "days": prior_period.days},
            "prior_has_data": bool(prior.get("day_count")),
            "deltas": deltas,
        }
        return out

    # ------------------------------------------------------------------ #
    # 2. Enriched trend: moving average, cumulative, run rate
    # ------------------------------------------------------------------ #

    def trend_enriched(self, f: Filters, *, ma_window: int = 7) -> dict[str, Any]:
        points = self.dash.trend(f)
        if not points:
            return {"points": [], "summary": None}

        values = [_d(p["net_ftp_profit"]) for p in points]
        cumulative = ZERO
        enriched = []

        for i, p in enumerate(points):
            cumulative += values[i]
            lo = max(0, i - ma_window + 1)
            window = values[lo : i + 1]
            ma = (sum(window) / len(window)).quantize(MONEY_Q)
            prior = values[i - 1] if i else None
            enriched.append({
                **p,
                "moving_average": ma,
                "cumulative": cumulative.quantize(MONEY_Q),
                "day_over_day": (values[i] - prior).quantize(MONEY_Q) if prior is not None else None,
                "day_over_day_pct": _pct(values[i], prior) if prior is not None else None,
            })

        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        stdev = Decimal(math.sqrt(float(variance)))
        best = max(range(len(values)), key=lambda i: values[i])
        worst = min(range(len(values)), key=lambda i: values[i])

        return {
            "points": enriched,
            "summary": {
                "days": len(values),
                "total": sum(values).quantize(MONEY_Q),
                "mean_daily": mean.quantize(MONEY_Q),
                "stdev_daily": stdev.quantize(MONEY_Q),
                # Coefficient of variation: how volatile the daily book is,
                # independent of its size, so branches of different scale compare.
                "volatility_pct": ((stdev / mean * 100).quantize(RATE_Q)
                                   if mean else None),
                "best_day": {"date": points[best]["key"],
                             "value": values[best].quantize(MONEY_Q)},
                "worst_day": {"date": points[worst]["key"],
                              "value": values[worst].quantize(MONEY_Q)},
                "annualised_run_rate": (mean * 365).quantize(MONEY_Q),
            },
        }

    # ------------------------------------------------------------------ #
    # 3. Variance bridge -- volume vs rate vs interaction
    # ------------------------------------------------------------------ #

    def variance_bridge(self, f: Filters, *, by: Dimension = "product") -> dict[str, Any]:
        """Why did FTP profit change between this window and the last?

        For each segment, income is exactly ``B * r / 36500`` with ``B`` the
        balance-days and ``r`` the balance-weighted rate. So::

            dI = [ B0*dr  +  r0*dB  +  dB*dr ] / 36500
                   ^rate     ^volume   ^interaction

        The three effects sum to the total change with no residual. Segments
        that only exist in one period are reported as pure volume -- there is no
        prior rate to move.
        """
        period = self.resolve_period(f)
        if period is None:
            return {"available": False, "reason": "no data in the selected window"}

        prior_period = period.prior()
        current_period = period
        mode = "preceding_period"
        was = {r["label"]: r
               for r in self._segments(self._window(f, prior_period), by)}

        if not was and period.days >= 2:
            # Nothing loaded before this window -- which is the normal case on a
            # freshly seeded system. Rather than showing an empty flagship
            # analytic, split the window that *does* have data down the middle
            # and compare its halves. The mode is reported so the reader knows
            # which comparison they are looking at.
            half = period.days // 2
            prior_period = Period(period.start,
                                  period.start + timedelta(days=half - 1))
            current_period = Period(period.start + timedelta(days=half), period.end)
            mode = "split_window"
            was = {r["label"]: r
                   for r in self._segments(self._window(f, prior_period), by)}

        now = {r["label"]: r
               for r in self._segments(self._window(f, current_period), by)}

        if not was:
            return {
                "available": False,
                "reason": (
                    f"only {period.days} day(s) of data are available; a bridge "
                    "needs at least two so one period can be compared to another"
                ),
                "current_period": {"start": period.start, "end": period.end},
                "prior_period": {"start": prior_period.start, "end": prior_period.end},
            }

        rows = []
        tot_vol = tot_rate = tot_inter = ZERO
        opening = closing = ZERO

        for label in sorted(set(now) | set(was)):
            c, p = now.get(label), was.get(label)
            b1 = _d(c["total_balance"]) if c else ZERO
            b0 = _d(p["total_balance"]) if p else ZERO

            # Profit measured as B*r/36500 rather than as the sum of per-row
            # incomes. The two differ by sub-cent row rounding, and only this
            # form makes the decomposition algebraically exact:
            #     dI = (B1*r1 - B0*r0)/36500
            #        = [ r0*dB + B0*dr + dB*dr ] / 36500
            # Using the rounded sum on one side and B*r on the other would leave
            # a residual that looks like a modelling error but is just rounding.
            i1 = (_d(c["ftp_rate_x_balance"]) / DAY_BASIS) if c else ZERO
            i0 = (_d(p["ftp_rate_x_balance"]) / DAY_BASIS) if p else ZERO
            r1 = (_d(c["ftp_rate_x_balance"]) / b1) if c and b1 else ZERO
            r0 = (_d(p["ftp_rate_x_balance"]) / b0) if p and b0 else ZERO

            db, dr = b1 - b0, r1 - r0
            volume = (r0 * db) / DAY_BASIS
            rate = (b0 * dr) / DAY_BASIS
            inter = (db * dr) / DAY_BASIS

            tot_vol += volume
            tot_rate += rate
            tot_inter += inter
            opening += i0
            closing += i1

            rows.append({
                "label": label,
                "status": "new" if not p else ("closed" if not c else "continuing"),
                "prior_profit": i0.quantize(MONEY_Q),
                "current_profit": i1.quantize(MONEY_Q),
                "change": (i1 - i0).quantize(MONEY_Q),
                "volume_effect": volume.quantize(MONEY_Q),
                "rate_effect": rate.quantize(MONEY_Q),
                "interaction_effect": inter.quantize(MONEY_Q),
                "prior_rate": r0.quantize(Decimal("0.000001")),
                "current_rate": r1.quantize(Decimal("0.000001")),
                "prior_balance": b0.quantize(MONEY_Q),
                "current_balance": b1.quantize(MONEY_Q),
            })

        rows.sort(key=lambda r: abs(r["change"]), reverse=True)
        # Computed on the unrounded accumulators, so this is the true residual
        # of the decomposition and not an artefact of display rounding.
        residual = (closing - opening) - (tot_vol + tot_rate + tot_inter)

        return {
            "available": True,
            "dimension": by,
            #: "preceding_period" compares against the window immediately before;
            #: "split_window" halves the loaded window because nothing precedes it.
            "comparison_mode": mode,
            "current_period": {"start": current_period.start,
                               "end": current_period.end,
                               "days": current_period.days},
            "prior_period": {"start": prior_period.start, "end": prior_period.end,
                             "days": prior_period.days},
            "opening_profit": opening.quantize(MONEY_Q),
            "closing_profit": closing.quantize(MONEY_Q),
            "total_change": (closing - opening).quantize(MONEY_Q),
            "volume_effect": tot_vol.quantize(MONEY_Q),
            "rate_effect": tot_rate.quantize(MONEY_Q),
            "interaction_effect": tot_inter.quantize(MONEY_Q),
            # Proof the decomposition is complete, surfaced rather than trusted.
            "residual": residual.quantize(Decimal("0.000001")),
            "segments": rows,
        }

    def _segments(self, f: Filters, by: Dimension) -> list[dict]:
        """Segment totals including the weighted-rate component."""
        from app.repositories.dashboard import _MEASURES

        if f.needs_fact_grain:
            col = self._fact_dimension(by)
            names = self._label_maps()
            stmt = (select(col, *_fact_sums())
                    .where(self.dash._fact_where(f)).group_by(col))
            out = []
            for r in self.s.execute(stmt):
                raw = r[0]
                key = raw.value if hasattr(raw, "value") else raw
                label = (str(key).replace("_", " ").title() if by == "category"
                         else names.get(by, {}).get(key, str(key)))
                row = {m: _d(getattr(r, m)) for m in _MEASURES}
                row["label"] = label
                row["account_count"] = r.account_count or 0
                row["negative_ftp_count"] = r.negative_ftp_count or 0
                out.append(row)
            return out

        model, keys, label_of = self._dimension(by, f)
        stmt = _apply_filters(
            _apply_scope(select(*keys, *_sums(model)), model, self.dash._scope_for(f)),
            model, f,
        ).group_by(*keys)

        out = []
        for r in self.s.execute(stmt):
            row = {m: _d(getattr(r, m)) for m in _MEASURES}
            row["label"] = label_of(r)
            row["account_count"] = r.account_count or 0
            row["negative_ftp_count"] = r.negative_ftp_count or 0
            out.append(row)
        return out

    def _dimension(self, by: Dimension, f: Filters):
        if by == "product":
            m = AggDailyBranchProduct
            return m, [m.product_code], lambda r: r[0]
        if by == "category":
            m = AggDailyBranch
            return m, [m.branch_category], lambda r: (
                r[0].value if hasattr(r[0], "value") else str(r[0])
            )
        if by == "division":
            m = AggDailyBranch
            return m, [m.division_id], lambda r: f"Division {r[0]}"
        if by == "district":
            m = AggDailyBranch
            return m, [m.district_id], lambda r: f"District {r[0]}"
        m = _grain(f)
        return m, [m.branch_code], lambda r: r[0]

    # ------------------------------------------------------------------ #
    # 4. Spread waterfall
    # ------------------------------------------------------------------ #

    def spread_waterfall(self, f: Filters, *, by: Dimension | None = None) -> dict[str, Any]:
        """Where the FTP margin comes from, decomposed into its four components.

        Exact at any grain because the aggregates store each component signed
        for its side. Rates are shown in basis points of the book so a small
        book and a large one can be compared directly.
        """
        r = self._totals(f)
        balance = _d(r.total_balance)

        def band(x: Decimal) -> Decimal:
            """Component expressed as an annualised rate on the book."""
            return ((x / balance) if balance else ZERO).quantize(Decimal("0.000001"))

        components = [
            {"key": "benchmark", "label": "Benchmark",
             "amount": (_d(r.benchmark_contrib) / DAY_BASIS).quantize(MONEY_Q),
             "rate": band(_d(r.benchmark_contrib))},
            {"key": "customer_rate", "label": "Customer rate (ROI)",
             "amount": (_d(r.roi_contrib) / DAY_BASIS).quantize(MONEY_Q),
             "rate": band(_d(r.roi_contrib))},
            {"key": "liquidity", "label": "Liquidity cost",
             "amount": (_d(r.liquidity_contrib) / DAY_BASIS).quantize(MONEY_Q),
             "rate": band(_d(r.liquidity_contrib))},
            {"key": "other", "label": "Other cost",
             "amount": (_d(r.other_contrib) / DAY_BASIS).quantize(MONEY_Q),
             "rate": band(_d(r.other_contrib))},
        ]
        net = (_d(r.ftp_rate_x_balance) / DAY_BASIS).quantize(MONEY_Q)
        by_segment = None
        if by:
            by_segment = [
                {
                    "label": seg["label"],
                    "benchmark": (seg["benchmark_contrib"] / DAY_BASIS).quantize(MONEY_Q),
                    "customer_rate": (seg["roi_contrib"] / DAY_BASIS).quantize(MONEY_Q),
                    "liquidity": (seg["liquidity_contrib"] / DAY_BASIS).quantize(MONEY_Q),
                    "other": (seg["other_contrib"] / DAY_BASIS).quantize(MONEY_Q),
                    "net": (seg["ftp_rate_x_balance"] / DAY_BASIS).quantize(MONEY_Q),
                }
                for seg in sorted(
                    self._segments(f, by),
                    key=lambda s: s["net_ftp_profit"], reverse=True,
                )
            ]

        return {
            "components": components,
            "net_ftp_profit": net,
            "total_balance": balance.quantize(MONEY_Q),
            "check": (
                sum((_d(c["amount"]) for c in components), ZERO) - net
            ).quantize(Decimal("0.01")),
            "by_segment": by_segment,
        }

    # ------------------------------------------------------------------ #
    # 5. Concentration -- Pareto and HHI
    # ------------------------------------------------------------------ #

    def concentration(self, f: Filters, *, by: Dimension = "branch") -> dict[str, Any]:
        """How dependent the book is on a few segments.

        HHI is the sum of squared percentage shares, the standard competition
        measure: under 1500 is diffuse, over 2500 is concentrated. Reported
        alongside a Pareto curve so the shape is visible, not just the index.

        Shares use absolute values, because a loss-making segment is still a
        concentration of exposure and would otherwise cancel a profitable one.
        """
        segments = self._segments(f, by)
        if not segments:
            return {"available": False, "segments": []}

        ranked = sorted(segments, key=lambda s: s["net_ftp_profit"], reverse=True)
        gross = sum(abs(s["net_ftp_profit"]) for s in ranked)
        net = sum(s["net_ftp_profit"] for s in ranked)
        if not gross:
            return {"available": False, "segments": []}

        cumulative = ZERO
        rows = []
        hhi = ZERO
        for i, s in enumerate(ranked, start=1):
            share = abs(s["net_ftp_profit"]) / gross * 100
            hhi += share * share
            cumulative += share
            rows.append({
                "rank": i,
                "label": s["label"],
                "net_ftp_profit": s["net_ftp_profit"].quantize(MONEY_Q),
                "share_pct": share.quantize(RATE_Q),
                "cumulative_pct": cumulative.quantize(RATE_Q),
                "total_balance": s["total_balance"].quantize(MONEY_Q),
                "account_count": s["account_count"],
            })

        def top_n_share(n: int) -> Decimal | None:
            return rows[min(n, len(rows)) - 1]["cumulative_pct"] if rows else None

        hhi_q = hhi.quantize(Decimal("1"))
        return {
            "available": True,
            "dimension": by,
            "segment_count": len(rows),
            "net_ftp_profit": net.quantize(MONEY_Q),
            "hhi": hhi_q,
            "hhi_interpretation": (
                "diffuse" if hhi_q < 1500
                else "moderately concentrated" if hhi_q < 2500
                else "highly concentrated"
            ),
            "top_1_pct": top_n_share(1),
            "top_3_pct": top_n_share(3),
            "top_5_pct": top_n_share(5),
            #: How many segments make up 80% of the book -- the Pareto point.
            "segments_to_80pct": next(
                (r["rank"] for r in rows if r["cumulative_pct"] >= 80), len(rows)
            ),
            "segments": rows,
        }

    # ------------------------------------------------------------------ #
    # 6. Movers
    # ------------------------------------------------------------------ #

    def movers(self, f: Filters, *, by: Dimension = "branch", limit: int = 5) -> dict[str, Any]:
        """Biggest improvers and deteriorators against the prior window."""
        bridge = self.variance_bridge(f, by=by)
        if not bridge.get("available"):
            return {"available": False, "reason": bridge.get("reason")}
        segs = sorted(bridge["segments"], key=lambda s: s["change"], reverse=True)
        return {
            "available": True,
            "dimension": by,
            "gainers": segs[:limit],
            "losers": [s for s in reversed(segs[-limit:]) if s["change"] < 0],
        }

    # ------------------------------------------------------------------ #
    # 7. Rankings with quartiles
    # ------------------------------------------------------------------ #

    def rankings(self, f: Filters, *, by: Dimension = "branch") -> dict[str, Any]:
        """League table on yield, not just absolute profit.

        Ranking branches by absolute profit only rewards size. The yield --
        annualised FTP per unit of balance -- is what says whether a branch is
        actually pricing well, so both are shown and the quartile is on yield.
        """
        segments = self._segments(f, by)
        if not segments:
            return {"available": False, "rows": []}

        rows = []
        for s in segments:
            bal = s["total_balance"]
            # income/balance_days * 365 * 100 reduces exactly to the
            # balance-weighted FTP rate, because the rate is already expressed
            # as an annual percentage. Multiplying again would inflate it 3.65x.
            yield_pct = (
                (s["ftp_rate_x_balance"] / bal).quantize(RATE_Q) if bal else ZERO
            )
            rows.append({
                "label": s["label"],
                "net_ftp_profit": s["net_ftp_profit"].quantize(MONEY_Q),
                "total_balance": bal.quantize(MONEY_Q),
                "yield_pct": yield_pct,
                "account_count": s["account_count"],
                "negative_ftp_count": s["negative_ftp_count"],
                "profit_per_account": (
                    (s["net_ftp_profit"] / s["account_count"]).quantize(MONEY_Q)
                    if s["account_count"] else ZERO
                ),
            })

        rows.sort(key=lambda r: r["yield_pct"], reverse=True)
        n = len(rows)
        for i, r in enumerate(rows):
            r["rank"] = i + 1
            r["percentile"] = Decimal(
                round((n - i - 0.5) / n * 100, 1)
            ) if n else ZERO
            r["quartile"] = min(4, int(i / n * 4) + 1) if n else 1

        yields = sorted(r["yield_pct"] for r in rows)
        median = (
            yields[n // 2] if n % 2
            else (yields[n // 2 - 1] + yields[n // 2]) / 2
        ) if n else ZERO

        return {
            "available": True,
            "dimension": by,
            "median_yield_pct": Decimal(median).quantize(RATE_Q),
            "best": rows[0] if rows else None,
            "worst": rows[-1] if rows else None,
            "spread_pct": (rows[0]["yield_pct"] - rows[-1]["yield_pct"]).quantize(RATE_Q)
                          if rows else ZERO,
            "rows": rows,
        }

    # ------------------------------------------------------------------ #
    # 8. Distribution of FTP rate
    # ------------------------------------------------------------------ #

    def rate_distribution(self, f: Filters, *, buckets: int = 12) -> dict[str, Any]:
        """Histogram of account-level FTP rate, balance-weighted.

        Weighting by balance matters: a thousand tiny accounts at a good spread
        do not offset one large account priced below cost, and an unweighted
        histogram would hide exactly that.
        """
        F = FtpCalculationResult
        where = self._fact_where(f)
        lo, hi = self.s.execute(
            select(func.min(F.ftp_rate), func.max(F.ftp_rate)).where(where)
        ).one()
        if lo is None:
            return {"available": False, "buckets": []}

        lo, hi = Decimal(lo), Decimal(hi)
        if lo == hi:
            hi = lo + Decimal("0.01")
        width = (hi - lo) / buckets

        # width_bucket returns buckets+1 for a value exactly equal to `hi`,
        # and 0 for one below `lo`. Clamp inside SQL so those fold into the end
        # buckets; clamping after GROUP BY would emit two rows for one range.
        bucket_expr = func.least(
            func.greatest(func.width_bucket(F.ftp_rate, lo, hi, buckets), 1),
            buckets,
        )
        rows = self.s.execute(
            select(
                bucket_expr.label("b"),
                func.count(),
                func.sum(F.balance),
                func.sum(F.ftp_income),
            ).where(where).group_by(bucket_expr).order_by(bucket_expr)
        ).all()

        total_accounts = sum(r[1] for r in rows) or 1
        total_balance = sum(_d(r[2]) for r in rows) or Decimal(1)

        out = []
        for b, count, bal, income in rows:
            idx = min(max(int(b), 1), buckets)
            out.append({
                "bucket": idx,
                "from_rate": (lo + width * (idx - 1)).quantize(Decimal("0.0001")),
                "to_rate": (lo + width * idx).quantize(Decimal("0.0001")),
                "account_count": count,
                "account_pct": Decimal(count / total_accounts * 100).quantize(RATE_Q),
                "balance": _d(bal).quantize(MONEY_Q),
                "balance_pct": (_d(bal) / total_balance * 100).quantize(RATE_Q),
                "ftp_income": _d(income).quantize(MONEY_Q),
                "is_negative": (lo + width * idx) <= 0,
            })

        return {
            "available": True,
            "min_rate": lo.quantize(Decimal("0.000001")),
            "max_rate": hi.quantize(Decimal("0.000001")),
            "buckets": out,
        }

    # ------------------------------------------------------------------ #
    # 9. Outliers
    # ------------------------------------------------------------------ #

    def outliers(self, f: Filters, *, z_threshold: float = 3.0,
                 limit: int = 25) -> dict[str, Any]:
        """Accounts priced unusually for their own product.

        The comparison is *within product*, because a home loan and a current
        account have no business being compared on rate. An account three
        standard deviations from its product's mean is either a data error or a
        deal worth knowing about, and both are worth surfacing.
        """
        F = FtpCalculationResult
        where = self._fact_where(f)

        stats = select(
            F.product_code.label("pc"),
            func.avg(F.ftp_rate).label("mean_rate"),
            func.stddev_samp(F.ftp_rate).label("sd_rate"),
            func.avg(F.normalized_roi).label("mean_roi"),
            func.stddev_samp(F.normalized_roi).label("sd_roi"),
        ).where(where).group_by(F.product_code).subquery()

        z_rate = case(
            (stats.c.sd_rate > 0, (F.ftp_rate - stats.c.mean_rate) / stats.c.sd_rate),
            else_=0,
        )
        z_roi = case(
            (stats.c.sd_roi > 0, (F.normalized_roi - stats.c.mean_roi) / stats.c.sd_roi),
            else_=0,
        )

        rows = self.s.execute(
            select(
                F.business_date, F.branch_code, F.account_no, F.product_code,
                F.side, F.balance, F.normalized_roi, F.ftp_rate, F.ftp_income,
                z_rate.label("z_rate"), z_roi.label("z_roi"),
            )
            .join(stats, stats.c.pc == F.product_code)
            .where(where)
            .where(func.abs(z_rate) >= z_threshold)
            .order_by(func.abs(z_rate).desc())
            .limit(limit)
        ).all()

        return {
            "z_threshold": z_threshold,
            "count": len(rows),
            "rows": [
                {
                    "business_date": r.business_date, "branch_code": r.branch_code,
                    "account_no": r.account_no, "product_code": r.product_code,
                    "side": r.side.value if hasattr(r.side, "value") else str(r.side),
                    "balance": _d(r.balance).quantize(MONEY_Q),
                    "normalized_roi": _d(r.normalized_roi),
                    "ftp_rate": _d(r.ftp_rate),
                    "ftp_income": _d(r.ftp_income).quantize(MONEY_Q),
                    "z_rate": Decimal(r.z_rate or 0).quantize(Decimal("0.01")),
                    "z_roi": Decimal(r.z_roi or 0).quantize(Decimal("0.01")),
                }
                for r in rows
            ],
        }

    # ------------------------------------------------------------------ #
    # 10. Profit leakage
    # ------------------------------------------------------------------ #

    def leakage(self, f: Filters, *, limit: int = 20) -> dict[str, Any]:
        """Where the book loses money, and how much it would be worth to fix.

        `opportunity` is what the negative accounts would contribute if they
        merely broke even -- the size of the prize, which is what makes this
        actionable rather than merely alarming.
        """
        F = FtpCalculationResult
        where = self._fact_where(f)
        neg = and_(where, F.negative_ftp_flag.is_(True))

        total_income = _d(self.s.scalar(select(func.sum(F.ftp_income)).where(where)))
        agg = self.s.execute(
            select(func.count(), func.sum(F.balance), func.sum(F.ftp_income)).where(neg)
        ).one()
        count, balance, drag = agg[0] or 0, _d(agg[1]), _d(agg[2])

        by_product = [
            {"label": r[0], "account_count": r[1],
             "balance": _d(r[2]).quantize(MONEY_Q),
             "ftp_income": _d(r[3]).quantize(MONEY_Q)}
            for r in self.s.execute(
                select(F.product_code, func.count(), func.sum(F.balance),
                       func.sum(F.ftp_income))
                .where(neg).group_by(F.product_code)
                .order_by(func.sum(F.ftp_income))
            ).all()
        ]
        by_branch = [
            {"label": r[0], "account_count": r[1],
             "balance": _d(r[2]).quantize(MONEY_Q),
             "ftp_income": _d(r[3]).quantize(MONEY_Q)}
            for r in self.s.execute(
                select(F.branch_code, func.count(), func.sum(F.balance),
                       func.sum(F.ftp_income))
                .where(neg).group_by(F.branch_code)
                .order_by(func.sum(F.ftp_income))
            ).all()
        ]
        worst = self.s.scalars(
            select(F).where(neg).order_by(F.ftp_income).limit(limit)
        ).all()

        return {
            "negative_account_days": count,
            "negative_balance": balance.quantize(MONEY_Q),
            "drag": drag.quantize(MONEY_Q),
            "total_ftp_profit": total_income.quantize(MONEY_Q),
            "drag_as_pct_of_profit": (
                (abs(drag) / total_income * 100).quantize(RATE_Q)
                if total_income else None
            ),
            "opportunity": abs(drag).quantize(MONEY_Q),
            "by_product": by_product,
            "by_branch": by_branch,
            "worst_accounts": [
                {"business_date": r.business_date, "branch_code": r.branch_code,
                 "account_no": r.account_no, "product_code": r.product_code,
                 "balance": _d(r.balance).quantize(MONEY_Q),
                 "normalized_roi": _d(r.normalized_roi),
                 "ftp_rate": _d(r.ftp_rate),
                 "ftp_income": _d(r.ftp_income).quantize(MONEY_Q)}
                for r in worst
            ],
        }

    # ------------------------------------------------------------------ #
    # 11. Balance vs return scatter
    # ------------------------------------------------------------------ #

    def scatter(self, f: Filters, *, by: Dimension = "branch") -> dict[str, Any]:
        """Balance against yield, with medians drawn as quadrant lines.

        The useful quadrant is high balance, low yield: large books priced
        thinly, which is where repricing effort pays back most.
        """
        segments = self._segments(f, by)
        pts = []
        for s in segments:
            bal = s["total_balance"]
            if not bal:
                continue
            pts.append({
                "label": s["label"],
                "balance": bal.quantize(MONEY_Q),
                "ftp_income": s["net_ftp_profit"].quantize(MONEY_Q),
                "yield_pct": (s["ftp_rate_x_balance"] / bal).quantize(RATE_Q),
                "account_count": s["account_count"],
            })
        if not pts:
            return {"available": False, "points": []}

        def median(vals):
            v = sorted(vals)
            n = len(v)
            return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2

        mb = median([p["balance"] for p in pts])
        my = median([p["yield_pct"] for p in pts])
        for p in pts:
            high_bal = p["balance"] >= mb
            high_yield = p["yield_pct"] >= my
            p["quadrant"] = (
                "star" if high_bal and high_yield
                else "opportunity" if high_bal else
                "efficient" if high_yield else "marginal"
            )
        return {
            "available": True,
            "dimension": by,
            "median_balance": Decimal(mb).quantize(MONEY_Q),
            "median_yield_pct": Decimal(my).quantize(RATE_Q),
            "points": pts,
        }

    # ------------------------------------------------------------------ #
    # 12. Asset / liability structure
    # ------------------------------------------------------------------ #

    def balance_sheet_structure(self, f: Filters) -> dict[str, Any]:
        """Asset and liability sides side by side, with the funding gap.

        Asset yield and liability cost are both expressed as annualised rates so
        the FTP spread between them is directly readable.
        """
        m = AggDailyProduct
        scope_all = self.dash._scope_for(f)
        stmt = _apply_filters(
            select(
                m.side,
                func.sum(m.total_balance), func.sum(m.net_ftp_profit),
                func.sum(m.roi_x_balance), func.sum(m.ftp_rate_x_balance),
                func.sum(m.account_count),
            ), m, f
        ).group_by(m.side)
        # AggDailyProduct has no branch_id, so it is only usable unscoped.
        if not scope_all.unrestricted:
            m = AggDailyBranchProduct
            stmt = _apply_filters(
                _apply_scope(
                    select(
                        func.min(AggDailyProduct.side), func.sum(m.total_balance),
                        func.sum(m.net_ftp_profit), func.sum(m.roi_x_balance),
                        func.sum(m.ftp_rate_x_balance), func.sum(m.account_count),
                    ).join(AggDailyProduct,
                           and_(AggDailyProduct.product_id == m.product_id,
                                AggDailyProduct.business_date == m.business_date)),
                    m, scope_all,
                ), m, f
            ).group_by(AggDailyProduct.side)

        sides: dict[str, dict] = {}
        for side, bal, profit, roi_xb, rate_xb, accts in self.s.execute(stmt):
            key = side.value if hasattr(side, "value") else str(side)
            bal = _d(bal)
            sides[key] = {
                "balance": bal.quantize(MONEY_Q),
                "ftp_profit": _d(profit).quantize(MONEY_Q),
                "avg_customer_rate": ((_d(roi_xb) / bal).quantize(RATE_Q) if bal else ZERO),
                "avg_ftp_rate": ((_d(rate_xb) / bal).quantize(RATE_Q) if bal else ZERO),
                "account_days": accts or 0,
            }

        a = sides.get("ASSET", {})
        l = sides.get("LIABILITY", {})
        ab, lb = _d(a.get("balance")), _d(l.get("balance"))
        return {
            "asset": a or None,
            "liability": l or None,
            "funding_gap": (ab - lb).quantize(MONEY_Q),
            #: Below 1.0 the asset book is not self-funded from these deposits.
            "coverage_ratio": ((lb / ab).quantize(Decimal("0.0001")) if ab else None),
            "ftp_spread": (
                _d(a.get("avg_ftp_rate")) + _d(l.get("avg_ftp_rate"))
            ).quantize(RATE_Q),
        }

    # ------------------------------------------------------------------ #

    def _fact_where(self, f: Filters):
        """Scope-and-filter predicate for the fact table.

        Delegates, so there is one definition of what a filter means rather
        than two that can drift.
        """
        return self.dash._fact_where(f)

    # ------------------------------------------------------------------ #
    # 13. Leaderboards -- top performers, and who leads where
    # ------------------------------------------------------------------ #

    #: How each dimension is addressed on the branch x product grain, which is
    #: the only aggregate carrying both the hierarchy and the product.
    _BP_DIMS = {
        "branch": ("branch_id", "branch_code"),
        "product": ("product_id", "product_code"),
        "division": ("division_id", "division_id"),
        "district": ("district_id", "district_id"),
        "category": ("branch_category", "branch_category"),
    }

    def _bp_key(self, dim: Dimension):
        m = AggDailyBranchProduct
        id_col, label_col = self._BP_DIMS[dim]
        return getattr(m, id_col), getattr(m, label_col)

    def _label_maps(self) -> dict[str, dict[Any, str]]:
        """Readable names for id-keyed dimensions, resolved once per request."""
        from app.models import Branch, District, Division, Product
        return {
            "division": {d.id: d.name for d in self.s.scalars(select(Division))},
            "district": {d.id: d.name for d in self.s.scalars(select(District))},
            "branch": {b.branch_code: f"{b.branch_code} {b.branch_name}"
                       for b in self.s.scalars(select(Branch))},
            "product": {p.product_code: p.short_name
                        for p in self.s.scalars(select(Product))},
        }

    def _bp_rollup(self, f: Filters, dims: list[Dimension]) -> list[dict]:
        """Group the branch x product grain by one or two dimensions."""
        from app.repositories.dashboard import _sums

        m = AggDailyBranchProduct
        keys = []
        for d in dims:
            id_col, label_col = self._bp_key(d)
            keys.append(id_col)
            if label_col is not id_col:
                keys.append(label_col)

        stmt = _apply_filters(
            _apply_scope(select(*keys, *_sums(m)), m, self.dash._scope_for(f)), m, f,
        ).group_by(*keys)

        out = []
        for r in self.s.execute(stmt):
            row: dict[str, Any] = {
                "net_ftp_profit": _d(r.net_ftp_profit),
                "total_balance": _d(r.total_balance),
                "ftp_rate_x_balance": _d(r.ftp_rate_x_balance),
                "asset_ftp_profit": _d(r.asset_ftp_profit),
                "liability_ftp_profit": _d(r.liability_ftp_profit),
                "account_count": r.account_count or 0,
                "negative_ftp_count": r.negative_ftp_count or 0,
            }
            i = 0
            for d in dims:
                id_col, label_col = self._bp_key(d)
                raw = r[i]; i += 1
                if label_col is not id_col:
                    raw_label = r[i]; i += 1
                else:
                    raw_label = raw
                row[f"{d}_key"] = raw.value if hasattr(raw, "value") else raw
                row[f"{d}_label"] = (
                    raw_label.value if hasattr(raw_label, "value") else raw_label
                )
            out.append(row)
        return out

    @staticmethod
    def _yield_of(row: dict) -> Decimal:
        bal = row["total_balance"]
        return (row["ftp_rate_x_balance"] / bal).quantize(RATE_Q) if bal else ZERO

    def headline_performers(self, f: Filters) -> dict[str, Any]:
        """Best and worst on every dimension at once, for the dashboard header.

        Both *profit* and *yield* leaders are reported, because they are often
        different segments and conflating them is how a large, thinly-priced
        book gets mistaken for a good one.
        """
        names = self._label_maps()
        out: dict[str, Any] = {}

        for dim in ("branch", "product", "division", "district", "category"):
            rows = self._bp_rollup(f, [dim])  # type: ignore[list-item]
            if not rows:
                out[dim] = None
                continue

            def decorate(r: dict) -> dict:
                key = r[f"{dim}_key"]
                label = names.get(dim, {}).get(
                    r[f"{dim}_label"], str(r[f"{dim}_label"])
                )
                if dim == "category":
                    label = str(r[f"{dim}_label"]).replace("_", " ").title()
                return {
                    "key": key, "label": label,
                    "net_ftp_profit": r["net_ftp_profit"].quantize(MONEY_Q),
                    "total_balance": r["total_balance"].quantize(MONEY_Q),
                    "yield_pct": self._yield_of(r),
                    "account_count": r["account_count"],
                    "negative_ftp_count": r["negative_ftp_count"],
                }

            by_profit = sorted(rows, key=lambda r: r["net_ftp_profit"], reverse=True)
            by_yield = sorted(rows, key=self._yield_of, reverse=True)
            total = sum(r["net_ftp_profit"] for r in rows) or Decimal(1)

            top = decorate(by_profit[0])
            top["share_pct"] = (top["net_ftp_profit"] / total * 100).quantize(RATE_Q)

            out[dim] = {
                "count": len(rows),
                #: False when there is only one member in scope. The maximum and
                #: the minimum of a one-element set are the same element, so
                #: calling it both the best and the worst performer is true
                #: arithmetic and a meaningless statement. The caller shows the
                #: single figure instead of a ranking.
                "rankable": len(rows) > 1,
                "top_by_profit": top,
                "bottom_by_profit": decorate(by_profit[-1]),
                "top_by_yield": decorate(by_yield[0]),
                "bottom_by_yield": decorate(by_yield[-1]),
                #: True when the profit leader is not the yield leader -- the
                #: case worth flagging, because size is masking thin pricing.
                #: Undefined with a single member, so it is forced false there.
                "profit_yield_diverge": (
                    len(rows) > 1
                    and by_profit[0].get(f"{dim}_key") != by_yield[0].get(f"{dim}_key")
                ),
            }
        return out

    def leaderboard(self, f: Filters, *, group: Dimension, of: Dimension,
                    top: int = 3, metric: str = "profit") -> dict[str, Any]:
        """Top `of` within each `group` -- e.g. the best branch in each division.

        Ranking on `yield` rather than `profit` answers a different question:
        not "who earns most" but "who prices best", which is the fairer
        comparison when the groups differ in size.
        """
        if group == of:
            return {"available": False,
                    "reason": "group and ranked dimension must differ"}

        names = self._label_maps()
        rows = self._bp_rollup(f, [group, of])
        if not rows:
            return {"available": False, "reason": "no data in this slice", "groups": []}

        def label_for(dim: Dimension, r: dict) -> str:
            raw = r[f"{dim}_label"]
            if dim == "category":
                return str(raw).replace("_", " ").title()
            return names.get(dim, {}).get(raw, str(raw))

        buckets: dict[Any, list[dict]] = defaultdict(list)
        for r in rows:
            buckets[r[f"{group}_key"]].append(r)

        key_fn = (lambda r: r["net_ftp_profit"]) if metric == "profit" else self._yield_of

        groups = []
        for gkey, members in buckets.items():
            ranked = sorted(members, key=key_fn, reverse=True)
            gtotal = sum(m["net_ftp_profit"] for m in members) or Decimal(1)
            entries = []
            for i, m in enumerate(ranked[:top], start=1):
                entries.append({
                    "rank": i,
                    "label": label_for(of, m),
                    "net_ftp_profit": m["net_ftp_profit"].quantize(MONEY_Q),
                    "total_balance": m["total_balance"].quantize(MONEY_Q),
                    "yield_pct": self._yield_of(m),
                    "account_count": m["account_count"],
                    "share_of_group_pct": (
                        m["net_ftp_profit"] / gtotal * 100
                    ).quantize(RATE_Q),
                })
            groups.append({
                "group_key": gkey,
                "group_label": label_for(group, members[0]),
                "group_net_ftp_profit": sum(
                    (m["net_ftp_profit"] for m in members), ZERO
                ).quantize(MONEY_Q),
                "member_count": len(members),
                "leader": entries[0] if entries else None,
                "laggard": {
                    "label": label_for(of, ranked[-1]),
                    "net_ftp_profit": ranked[-1]["net_ftp_profit"].quantize(MONEY_Q),
                    "yield_pct": self._yield_of(ranked[-1]),
                } if ranked else None,
                "entries": entries,
            })

        groups.sort(key=lambda g: g["group_net_ftp_profit"], reverse=True)
        return {
            "available": True, "group": group, "of": of, "metric": metric,
            "top": top, "groups": groups,
        }

    def product_leadership(self, f: Filters, *, area: Dimension = "district") -> dict[str, Any]:
        """Which product leads in each area, and by how much.

        `dominance` is the winner's share of that area's profit, and `margin` is
        how far ahead of the runner-up it sits. A high share with a thin margin
        is a different situation from a high share with a wide one, and the
        pair says which.
        """
        if area == "product":
            return {"available": False, "reason": "area cannot be product"}

        names = self._label_maps()
        rows = self._bp_rollup(f, [area, "product"])
        if not rows:
            return {"available": False, "reason": "no data in this slice", "areas": []}

        buckets: dict[Any, list[dict]] = defaultdict(list)
        for r in rows:
            buckets[r[f"{area}_key"]].append(r)

        def area_label(r: dict) -> str:
            raw = r[f"{area}_label"]
            if area == "category":
                return str(raw).replace("_", " ").title()
            return names.get(area, {}).get(raw, str(raw))

        areas = []
        all_products: set[str] = set()
        for members in buckets.values():
            ranked = sorted(members, key=lambda m: m["net_ftp_profit"], reverse=True)
            total = sum(m["net_ftp_profit"] for m in members) or Decimal(1)
            win, second = ranked[0], (ranked[1] if len(ranked) > 1 else None)
            all_products.update(str(m["product_label"]) for m in members)

            areas.append({
                "area_key": ranked[0][f"{area}_key"],
                "area_label": area_label(ranked[0]),
                "area_net_ftp_profit": sum((m["net_ftp_profit"] for m in members),
                                           ZERO).quantize(MONEY_Q),
                "winner": {
                    "product_code": str(win["product_label"]),
                    "product_name": names["product"].get(
                        str(win["product_label"]), str(win["product_label"])),
                    "net_ftp_profit": win["net_ftp_profit"].quantize(MONEY_Q),
                    "yield_pct": self._yield_of(win),
                    "total_balance": win["total_balance"].quantize(MONEY_Q),
                },
                "dominance_pct": (win["net_ftp_profit"] / total * 100).quantize(RATE_Q),
                "runner_up": {
                    "product_code": str(second["product_label"]),
                    "net_ftp_profit": second["net_ftp_profit"].quantize(MONEY_Q),
                } if second else None,
                "margin_over_runner_up": (
                    (win["net_ftp_profit"] - second["net_ftp_profit"]).quantize(MONEY_Q)
                    if second else None
                ),
                "products_present": len(members),
                "breakdown": [
                    {"product_code": str(m["product_label"]),
                     "net_ftp_profit": m["net_ftp_profit"].quantize(MONEY_Q),
                     "yield_pct": self._yield_of(m),
                     "share_pct": (m["net_ftp_profit"] / total * 100).quantize(RATE_Q)}
                    for m in ranked
                ],
            })

        areas.sort(key=lambda a: a["area_net_ftp_profit"], reverse=True)
        wins: dict[str, int] = defaultdict(int)
        for a in areas:
            wins[a["winner"]["product_code"]] += 1

        return {
            "available": True,
            "area": area,
            "area_count": len(areas),
            "product_count": len(all_products),
            #: How many areas each product wins -- one product taking every area
            #: is a very different book from five products splitting them.
            "wins_by_product": sorted(
                ({"product_code": k,
                  "product_name": names["product"].get(k, k),
                  "areas_won": v} for k, v in wins.items()),
                key=lambda x: x["areas_won"], reverse=True,
            ),
            "areas": areas,
        }

    # ------------------------------------------------------------------ #
    # 14. The banker's daily set
    # ------------------------------------------------------------------ #

    def nii_reconciliation(self, f: Filters) -> dict[str, Any]:
        """Net interest income reconciled to FTP -- the canonical FTP output.

        FTP exists to answer one question: of the margin the bank earns from
        customers, how much belongs to the business units that wrote the
        business, and how much belongs to the treasury book that funded it?

        The identity is exact and falls straight out of the stored components::

            NII              = SUM(roi_contrib) / 36500
            business units   = NII + benchmark + liquidity + other contributions
            treasury retains = NII - business units

        The benchmark term is the cost of funding the net asset position: when
        assets exceed deposits the treasury has bought the difference, and that
        cost is properly theirs rather than the branches'.
        """
        r = self._totals(f)
        interest_received = _d(r.interest_receivable)
        interest_paid = _d(r.interest_payable)
        nii = interest_received - interest_paid

        funding = _d(r.benchmark_contrib) / DAY_BASIS
        liquidity = _d(r.liquidity_contrib) / DAY_BASIS
        other = _d(r.other_contrib) / DAY_BASIS
        lending = _d(r.asset_ftp_profit)
        deposit = _d(r.liability_ftp_profit)
        business_units = lending + deposit
        treasury = nii - business_units

        return {
            "net_interest_income": nii.quantize(MONEY_Q),
            "interest_received": interest_received.quantize(MONEY_Q),
            "interest_paid": interest_paid.quantize(MONEY_Q),
            "business_units_total": business_units.quantize(MONEY_Q),
            "lending_spread": lending.quantize(MONEY_Q),
            "deposit_spread": deposit.quantize(MONEY_Q),
            "treasury_retained": treasury.quantize(MONEY_Q),
            "treasury_funding_of_gap": funding.quantize(MONEY_Q),
            "liquidity_premium": liquidity.quantize(MONEY_Q),
            "other_cost": other.quantize(MONEY_Q),
            # A share of NII only means something when NII is positive. With a
            # deposit-heavy book NII can be negative, and dividing by it gives
            # a figure like -1,248% that reads as a fault rather than as a
            # book that costs more to fund than it earns.
            "business_units_share_pct": (
                (business_units / nii * 100).quantize(RATE_Q) if nii > 0 else None
            ),
            "nii_is_negative": nii < 0,
            #: Proof the split is complete rather than merely plausible.
            "check": (
                nii + funding + liquidity + other - business_units
            ).quantize(Decimal("0.01")),
        }

    def banking_ratios(self, f: Filters) -> dict[str, Any]:
        """The ratios a bank reports daily, computed on the same slice.

        All are annualised from balance-days, so they read as rates regardless
        of how many days the window covers.
        """
        from app.models import Product

        r = self._totals(f)
        assets = _d(r.asset_balance)
        liabs = _d(r.liability_balance)
        received = _d(r.interest_receivable)
        paid = _d(r.interest_payable)
        nii = received - paid

        def annualised(amount: Decimal, base: Decimal) -> Decimal | None:
            return (amount / base * DAY_BASIS).quantize(RATE_Q) if base else None

        yield_on_advances = annualised(received, assets)
        cost_of_deposits = annualised(paid, liabs)
        nim = annualised(nii, assets)

        # CASA needs the demand/time split, which lives on the product master.
        if f.needs_fact_grain:
            F = FtpCalculationResult
            casa_rows = self.s.execute(
                select(F.liability_nature, func.sum(F.balance))
                .where(self.dash._fact_where(f))
                .where(F.side == Side.LIABILITY)
                .group_by(F.liability_nature)
            ).all()
        else:
            m = AggDailyBranchProduct
            casa_rows = self.s.execute(
                _apply_filters(
                    _apply_scope(
                        select(Product.liability_nature, func.sum(m.liability_balance))
                        .join(Product, Product.id == m.product_id)
                        .where(Product.side == Side.LIABILITY),
                        m, self.dash._scope_for(f),
                    ), m, f,
                ).group_by(Product.liability_nature)
            ).all()
        demand = sum((_d(v) for k, v in casa_rows if k and k.value == "DEMAND"), ZERO)
        time_ = sum((_d(v) for k, v in casa_rows if k and k.value == "TIME"), ZERO)
        deposits = demand + time_

        return {
            "yield_on_advances_pct": yield_on_advances,
            "cost_of_deposits_pct": cost_of_deposits,
            "gross_spread_pct": (
                (yield_on_advances - cost_of_deposits).quantize(RATE_Q)
                if yield_on_advances is not None and cost_of_deposits is not None else None
            ),
            "nim_pct": nim,
            "ftp_yield_pct": annualised(_d(r.net_ftp_profit), _d(r.total_balance)),
            #: Advances over deposits. Above 100% means the book is not funded
            #: by its own deposits and the shortfall is bought from treasury.
            "credit_deposit_ratio_pct": (
                (assets / liabs * 100).quantize(RATE_Q) if liabs else None
            ),
            #: Current and savings balances over total deposits. Watched daily
            #: because low-cost deposits are what protect the margin.
            "casa_ratio_pct": (
                (demand / deposits * 100).quantize(RATE_Q) if deposits else None
            ),
            "casa_balance": demand.quantize(MONEY_Q),
            "term_balance": time_.quantize(MONEY_Q),
            "advances": assets.quantize(MONEY_Q),
            "deposits": liabs.quantize(MONEY_Q),
            "funding_gap": (assets - liabs).quantize(MONEY_Q),
        }

    def repricing_opportunity(self, f: Filters, *, limit: int = 25) -> dict[str, Any]:
        """What the book would earn if underpriced accounts moved to their
        product's median spread.

        Median rather than mean, because a handful of deeply mispriced accounts
        would drag a mean target down and understate the prize. Accounts already
        at or above median are left alone -- this measures upside, not churn.
        """
        F = FtpCalculationResult
        where = self._fact_where(f)

        medians = select(
            F.product_code.label("pc"),
            func.percentile_cont(0.5).within_group(F.ftp_rate).label("median_rate"),
        ).where(where).group_by(F.product_code).subquery()

        uplift = (medians.c.median_rate - F.ftp_rate) * F.balance / DAY_BASIS

        rows = self.s.execute(
            select(
                F.business_date, F.branch_code, F.account_no, F.product_code,
                F.balance, F.ftp_rate, medians.c.median_rate, uplift.label("uplift"),
            )
            .join(medians, medians.c.pc == F.product_code)
            .where(where).where(F.ftp_rate < medians.c.median_rate)
            .order_by(uplift.desc()).limit(limit)
        ).all()

        totals = self.s.execute(
            select(func.count(), func.sum(F.balance), func.sum(uplift))
            .join(medians, medians.c.pc == F.product_code)
            .where(where).where(F.ftp_rate < medians.c.median_rate)
        ).one()

        current = _d(self.s.scalar(select(func.sum(F.ftp_income)).where(where)))
        prize = _d(totals[2])

        return {
            "accounts_below_median": totals[0] or 0,
            "balance_below_median": _d(totals[1]).quantize(MONEY_Q),
            "opportunity": prize.quantize(MONEY_Q),
            "current_ftp_profit": current.quantize(MONEY_Q),
            "uplift_pct": ((prize / current * 100).quantize(RATE_Q) if current else None),
            "by_product": [
                {"product_code": r[0], "accounts": r[1],
                 "opportunity": _d(r[2]).quantize(MONEY_Q)}
                for r in self.s.execute(
                    select(F.product_code, func.count(), func.sum(uplift))
                    .join(medians, medians.c.pc == F.product_code)
                    .where(where).where(F.ftp_rate < medians.c.median_rate)
                    .group_by(F.product_code).order_by(func.sum(uplift).desc())
                ).all()
            ],
            "top_accounts": [
                {"business_date": r.business_date, "branch_code": r.branch_code,
                 "account_no": r.account_no, "product_code": r.product_code,
                 "balance": _d(r.balance).quantize(MONEY_Q),
                 "ftp_rate": _d(r.ftp_rate),
                 "median_rate": _d(r.median_rate).quantize(Decimal("0.000001")),
                 "uplift": _d(r.uplift).quantize(MONEY_Q)}
                for r in rows
            ],
        }

    def watchlist(self, f: Filters) -> dict[str, Any]:
        """What needs attention today.

        Ordered by money at stake rather than by rule, because an operator has
        finite attention and the largest exposure should be read first.
        """
        from app.models import UploadBatch

        items: list[dict[str, Any]] = []
        period = self.resolve_period(f)
        latest = self.dash.latest_business_date()

        # --- staleness ---------------------------------------------------- #
        if latest:
            lag = (date.today() - latest).days
            if lag > 1:
                items.append({
                    "severity": "warning" if lag <= 3 else "critical",
                    "code": "STALE_DATA",
                    "title": f"No data for {lag} days",
                    "detail": f"The most recent business date loaded is {latest}.",
                    "amount": None,
                })

        # --- rejected rows on the most recent batch ------------------------ #
        batch = self.s.execute(
            select(UploadBatch.batch_ref, UploadBatch.rejected_rows,
                   UploadBatch.total_rows, UploadBatch.status)
            .order_by(UploadBatch.id.desc()).limit(1)
        ).first()
        if batch and batch.rejected_rows:
            items.append({
                "severity": "critical",
                "code": "REJECTED_ROWS",
                "title": f"{batch.rejected_rows:,} rows rejected in {batch.batch_ref}",
                "detail": f"of {batch.total_rows:,} read. Those accounts are absent "
                          "from every figure on this page.",
                "amount": None,
            })
        if batch and batch.status == "FAILED":
            items.append({
                "severity": "critical", "code": "BATCH_FAILED",
                "title": f"Upload {batch.batch_ref} failed",
                "detail": "The last upload did not complete.", "amount": None,
            })

        # --- loss-making accounts ------------------------------------------ #
        leak = self.leakage(f, limit=1)
        if leak["negative_account_days"]:
            items.append({
                "severity": "serious",
                "code": "NEGATIVE_FTP",
                "title": f"{leak['negative_account_days']:,} loss-making account-days",
                "detail": f"Dragging {leak['drag']} on a balance of "
                          f"{leak['negative_balance']}.",
                "amount": leak["drag"],
            })

        # --- ROI vs interest disagreement ---------------------------------- #
        F = FtpCalculationResult
        where = self._fact_where(f)
        mismatch = self.s.execute(
            select(func.count(), func.sum(func.abs(F.interest_variance)))
            .where(where).where(F.interest_mismatch.is_(True))
        ).one()
        if mismatch[0]:
            items.append({
                "severity": "warning",
                "code": "ROI_INTEREST_MISMATCH",
                "title": f"{mismatch[0]:,} accounts where ROI and interest disagree",
                "detail": f"Total variance {_d(mismatch[1]).quantize(MONEY_Q)} against "
                          "what the supplied rate implies.",
                "amount": _d(mismatch[1]).quantize(MONEY_Q),
            })

        # --- products priced below their own funding cost ------------------- #
        thin = self.s.execute(
            select(F.product_code,
                   func.sum(F.ftp_rate * F.balance) / func.nullif(func.sum(F.balance), 0),
                   func.sum(F.balance))
            .where(where).group_by(F.product_code)
            .having(func.sum(F.ftp_rate * F.balance) < 0)
        ).all()
        for code, rate, bal in thin:
            items.append({
                "severity": "critical", "code": "PRODUCT_BELOW_COST",
                "title": f"{code} is priced below its funding cost",
                "detail": f"Weighted FTP rate {_d(rate).quantize(RATE_Q)}% on "
                          f"{_d(bal).quantize(MONEY_Q)} of balance.",
                "amount": None,
            })

        # --- repricing upside ------------------------------------------------ #
        rep = self.repricing_opportunity(f, limit=1)
        if rep["opportunity"] and rep["opportunity"] > ZERO:
            items.append({
                "severity": "info",
                "code": "REPRICING_UPSIDE",
                "title": f"{rep['opportunity']} available from repricing",
                "detail": f"{rep['accounts_below_median']:,} account-days sit below "
                          "their product's median spread.",
                "amount": rep["opportunity"],
            })

        order = {"critical": 0, "serious": 1, "warning": 2, "info": 3}
        items.sort(key=lambda i: (order.get(i["severity"], 9),
                                  -abs(n_or_zero(i.get("amount")))))
        return {
            "as_of": latest,
            "period": {"start": period.start, "end": period.end} if period else None,
            "count": len(items),
            "critical_count": sum(1 for i in items if i["severity"] == "critical"),
            "items": items,
        }

    def period_summary(self, f: Filters) -> dict[str, Any]:
        """Month-, quarter- and year-to-date totals against the latest date."""
        latest = self.dash.latest_business_date()
        if latest is None:
            return {"available": False, "periods": []}

        starts = {
            "MTD": date(latest.year, latest.month, 1),
            "QTD": date(latest.year, 3 * ((latest.month - 1) // 3) + 1, 1),
            "YTD": date(latest.year, 1, 1),
        }
        out = []
        for label, start in starts.items():
            k = self.dash.kpis(replace(f, date_from=start, date_to=latest))
            bal = _d(k.get("total_balance"))
            out.append({
                "label": label,
                "start": start,
                "end": latest,
                "net_ftp_profit": _d(k.get("net_ftp_profit")).quantize(MONEY_Q),
                "asset_ftp_profit": _d(k.get("asset_ftp_profit")).quantize(MONEY_Q),
                "liability_ftp_profit": _d(k.get("liability_ftp_profit")).quantize(MONEY_Q),
                "days": k.get("day_count", 0),
                "avg_daily": (
                    (_d(k.get("net_ftp_profit")) / k["day_count"]).quantize(MONEY_Q)
                    if k.get("day_count") else ZERO
                ),
                "yield_pct": (
                    (_d(k.get("ftp_rate_x_balance", 0)) / bal).quantize(RATE_Q)
                    if bal else _d(k.get("ftp_over_balance_pct"))
                ),
            })
        return {"available": True, "as_of": latest, "periods": out}


def n_or_zero(v: Any) -> Decimal:
    try:
        return Decimal(str(v)) if v is not None else ZERO
    except Exception:  # noqa: BLE001
        return ZERO
