"""Effective-dated rate configuration (plan §4.5).

Two independently approvable layers. `NULL` on a product component means
INHERIT the global default; `0.00` means an explicit zero override. Keeping
those distinct is what stops a missing benchmark silently pricing at zero.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer,
    String, Text, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.types import DayCountBasis
from app.models.base import AuthorshipMixin, Base, Rate, TimestampMixin, pg_enum

#: Lifecycle of a configuration row.
CONFIG_STATUSES = ("DRAFT", "PENDING_APPROVAL", "APPROVED", "REJECTED", "SUPERSEDED")


class _RateConfigMixin:
    version: Mapped[int] = mapped_column(Integer)
    benchmark_rate: Mapped[Decimal | None] = mapped_column(Rate)
    liquidity_cost: Mapped[Decimal | None] = mapped_column(Rate)
    other_cost: Mapped[Decimal | None] = mapped_column(Rate)
    effective_from: Mapped[date] = mapped_column(Date)
    #: NULL means open-ended; the exclusion constraint maps it to 'infinity'.
    effective_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), server_default=text("'DRAFT'"))
    maker_id: Mapped[int | None] = mapped_column(BigInteger)
    checker_id: Mapped[int | None] = mapped_column(BigInteger)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)


class GlobalRateConfig(Base, _RateConfigMixin, TimestampMixin, AuthorshipMixin):
    """System-wide defaults.

    In the seeded configuration `benchmark_rate` is deliberately NULL, so a
    product with no benchmark override is a hard ConfigMissingError at
    validation time rather than a silent zero.
    """

    __tablename__ = "global_rate_config"
    __table_args__ = (
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="global_period_valid",
        ),
        CheckConstraint(
            "maker_id IS NULL OR checker_id IS NULL OR checker_id <> maker_id",
            name="global_maker_is_not_checker",
        ),
        Index("ix_global_rate_effective", "effective_from", "effective_to"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    day_count_basis: Mapped[DayCountBasis] = mapped_column(
        pg_enum(DayCountBasis, "day_count_basis"),
        server_default=text("'ACT_365'"),
    )


class ProductRateConfig(Base, _RateConfigMixin, TimestampMixin, AuthorshipMixin):
    """Per-product overrides. NULL on a component inherits the global value."""

    __tablename__ = "product_rate_config"
    __table_args__ = (
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="product_period_valid",
        ),
        CheckConstraint(
            "maker_id IS NULL OR checker_id IS NULL OR checker_id <> maker_id",
            name="product_maker_is_not_checker",
        ),
        Index("ix_product_rate_lookup", "product_id", "effective_from", "effective_to"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)


class SystemSetting(Base, TimestampMixin, AuthorshipMixin):
    """Operational knobs that are not rates: tolerances, bands, thresholds."""

    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    value: Mapped[dict] = mapped_column(JSONB)
    description: Mapped[str | None] = mapped_column(Text)
