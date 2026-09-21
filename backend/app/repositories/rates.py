"""Effective-dated rate lookup.

Selecting which configuration rows are in force on a date is a repository
concern; combining them is the pure resolver in `domain.rates`. Keeping the
split means the resolution rule is unit-testable without a database.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.domain.errors import ConfigMissingError
from app.domain.rates import resolve_rates
from app.domain.types import GlobalRates, ProductRates, ResolvedRates
from app.models import GlobalRateConfig, Product, ProductRateConfig


def _in_force(column_from, column_to, on: date):
    return (column_from <= on) & or_(column_to.is_(None), column_to > on)


def load_global(session: Session, on: date) -> GlobalRates:
    row = session.scalar(
        select(GlobalRateConfig)
        .where(GlobalRateConfig.status == "APPROVED")
        .where(_in_force(GlobalRateConfig.effective_from,
                         GlobalRateConfig.effective_to, on))
        .order_by(GlobalRateConfig.effective_from.desc())
        .limit(1)
    )
    if row is None:
        raise ConfigMissingError("<global>", on, "global_rate_config")
    return GlobalRates(
        version=row.version,
        benchmark_rate=row.benchmark_rate,
        liquidity_cost=row.liquidity_cost,
        other_cost=row.other_cost,
    )


def load_product_overrides(session: Session, on: date) -> dict[str, ProductRates]:
    """All approved product overrides in force on a date, keyed by product code.

    Loaded in one query rather than per row: at 10M rows/day a per-row lookup
    would dominate the run, and the set is tiny (one row per product).
    """
    rows = session.execute(
        select(Product.product_code, ProductRateConfig)
        .join(ProductRateConfig, ProductRateConfig.product_id == Product.id)
        .where(ProductRateConfig.status == "APPROVED")
        .where(_in_force(ProductRateConfig.effective_from,
                         ProductRateConfig.effective_to, on))
    ).all()
    return {
        code: ProductRates(
            product_code=code,
            version=cfg.version,
            benchmark_rate=cfg.benchmark_rate,
            liquidity_cost=cfg.liquidity_cost,
            other_cost=cfg.other_cost,
        )
        for code, cfg in rows
    }


class RateBook:
    """Resolved rates for one business date, cached per product.

    Rate resolution happens once per (product, date) -- five rows, not ten
    million -- and the result is reused across every account row.
    """

    def __init__(self, session: Session, on: date) -> None:
        self.on = on
        self.global_rates = load_global(session, on)
        self.overrides = load_product_overrides(session, on)
        self._cache: dict[str, ResolvedRates] = {}

    def resolve(self, product_code: str) -> ResolvedRates:
        hit = self._cache.get(product_code)
        if hit is None:
            hit = resolve_rates(
                product_code, self.on, self.global_rates,
                self.overrides.get(product_code),
            )
            self._cache[product_code] = hit
        return hit
