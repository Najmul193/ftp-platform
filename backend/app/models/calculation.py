"""Calculation runs, the fact table, and the additive aggregates.

The fact table is partitioned by `business_date` (see the migration). It is
append-only: corrections supersede rather than update, which means no row
bloat, no vacuum storms and no lock contention on the hot path.

Dashboards never read this table -- they read the aggregates below, so query
cost is bounded by aggregate cardinality rather than by history size.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger, Date, DateTime, Index, Integer, String, Text, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.types import BranchCategory, LiabilityNature, RateSource, Side, ValueSource
from app.models.base import Amount, Base, Money, Rate, pg_enum


class CalculationRun(Base):
    """One execution of the engine over a date range.

    Runs are append-only. Recalculating a date creates a new run and marks the
    previous one `is_current = false`; both are retained so a restatement can
    always be explained.
    """

    __tablename__ = "calculation_runs"
    __table_args__ = (
        Index("ix_run_dates", "business_date_from", "business_date_to"),
        Index("ix_run_status", "status", "started_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_ref: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    #: UPLOAD | MANUAL | CONFIG_CHANGE | SCHEDULED | SCENARIO
    trigger_type: Mapped[str] = mapped_column(String(20))
    batch_id: Mapped[int | None] = mapped_column(BigInteger, index=True)

    business_date_from: Mapped[date] = mapped_column(Date)
    business_date_to: Mapped[date] = mapped_column(Date)
    global_config_id: Mapped[int | None] = mapped_column(Integer)

    status: Mapped[str] = mapped_column(String(20), server_default=text("'PENDING'"))
    rows_in: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    rows_out: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    error_detail: Mapped[str | None] = mapped_column(Text)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    initiated_by: Mapped[int | None] = mapped_column(BigInteger)
    is_current: Mapped[bool] = mapped_column(server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class FtpCalculationResult(Base):
    """One account-day. Self-describing: every input's provenance travels with it.

    This is the platform's equivalent of the workbook's `Consolidated Data`
    sheet -- but where that sheet carried bare numbers, each row here states
    which configuration version produced each rate and whether ROI came from the
    bank or was derived. A published figure can be explained without re-deriving
    it.
    """

    __tablename__ = "ftp_calculation_results"
    __table_args__ = (
        # The real safeguard against a duplicate live account-day: a partial
        # unique index makes it physically impossible, independent of any
        # application check.
        Index(
            "uq_ftp_results_current_key",
            "business_date", "branch_code", "account_no",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        Index("ix_ftp_branch_date", "branch_id", "business_date",
              postgresql_where=text("is_current")),
        Index("ix_ftp_product_date", "product_id", "business_date",
              postgresql_where=text("is_current")),
        Index("ix_ftp_division_date", "division_id", "business_date",
              postgresql_where=text("is_current")),
        Index("ix_ftp_district_date", "district_id", "business_date",
              postgresql_where=text("is_current")),
        Index("ix_ftp_negative", "business_date", "branch_id",
              postgresql_where=text("is_current AND negative_ftp_flag")),
        Index("ix_ftp_run", "run_id"),
        {"postgresql_partition_by": "RANGE (business_date)"},
    )

    # Composite PK: a partitioned table must include the partition key.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    business_date: Mapped[date] = mapped_column(Date, primary_key=True)

    run_id: Mapped[int] = mapped_column(BigInteger)
    batch_id: Mapped[int] = mapped_column(BigInteger)

    # --- identity, denormalised so rollups are one indexed scan ---------- #
    branch_id: Mapped[int] = mapped_column(Integer)
    branch_code: Mapped[str] = mapped_column(String(10))
    division_id: Mapped[int] = mapped_column(Integer)
    district_id: Mapped[int] = mapped_column(Integer)
    branch_category: Mapped[BranchCategory] = mapped_column(
        pg_enum(BranchCategory, "branch_category")
    )
    account_no: Mapped[str] = mapped_column(String(40))
    product_id: Mapped[int] = mapped_column(Integer)
    product_code: Mapped[str] = mapped_column(String(40))
    side: Mapped[Side] = mapped_column(pg_enum(Side, "product_side"))
    liability_nature: Mapped[LiabilityNature | None] = mapped_column(
        pg_enum(LiabilityNature, "liability_nature")
    )

    # --- inputs exactly as supplied --------------------------------------- #
    balance: Mapped[Decimal] = mapped_column(Money)
    raw_roi: Mapped[Decimal | None] = mapped_column(Rate)
    raw_int_payable: Mapped[Decimal | None] = mapped_column(Amount)
    raw_int_receivable: Mapped[Decimal | None] = mapped_column(Amount)

    # --- normalised, with provenance -------------------------------------- #
    normalized_roi: Mapped[Decimal] = mapped_column(Rate)
    roi_source: Mapped[ValueSource] = mapped_column(pg_enum(ValueSource, "value_source"))
    customer_interest: Mapped[Decimal] = mapped_column(Amount)
    interest_source: Mapped[ValueSource] = mapped_column(pg_enum(ValueSource, "value_source"))
    interest_expected: Mapped[Decimal | None] = mapped_column(Amount)
    interest_variance: Mapped[Decimal | None] = mapped_column(Amount)
    interest_mismatch: Mapped[bool] = mapped_column(server_default=text("false"))

    # --- rates, each with the layer and version that supplied it ---------- #
    benchmark_rate: Mapped[Decimal] = mapped_column(Rate)
    benchmark_source: Mapped[RateSource] = mapped_column(pg_enum(RateSource, "rate_source"))
    liquidity_cost: Mapped[Decimal] = mapped_column(Rate)
    liquidity_source: Mapped[RateSource] = mapped_column(pg_enum(RateSource, "rate_source"))
    other_cost: Mapped[Decimal] = mapped_column(Rate)
    other_source: Mapped[RateSource] = mapped_column(pg_enum(RateSource, "rate_source"))
    global_config_version: Mapped[int] = mapped_column(Integer)
    product_config_version: Mapped[int | None] = mapped_column(Integer)

    # --- outputs ----------------------------------------------------------- #
    ftp_rate: Mapped[Decimal] = mapped_column(Rate)
    ftp_income: Mapped[Decimal] = mapped_column(Amount)
    asset_ftp_profit: Mapped[Decimal] = mapped_column(Amount, server_default=text("0"))
    liability_ftp_profit: Mapped[Decimal] = mapped_column(Amount, server_default=text("0"))
    negative_ftp_flag: Mapped[bool] = mapped_column(server_default=text("false"))

    is_current: Mapped[bool] = mapped_column(server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


# --------------------------------------------------------------------------- #
# Aggregates
# --------------------------------------------------------------------------- #


class _AggMixin:
    """Only additive components are stored.

    Weighted averages are kept as `SUM(rate x balance)` alongside `SUM(balance)`
    and divided at read time. Storing a pre-averaged rate would make rollups
    silently wrong, because an average of averages is not the average.
    """

    business_date: Mapped[date] = mapped_column(Date, primary_key=True)
    run_id: Mapped[int] = mapped_column(BigInteger)

    asset_balance: Mapped[Decimal] = mapped_column(Money, server_default=text("0"))
    liability_balance: Mapped[Decimal] = mapped_column(Money, server_default=text("0"))
    interest_receivable: Mapped[Decimal] = mapped_column(Amount, server_default=text("0"))
    interest_payable: Mapped[Decimal] = mapped_column(Amount, server_default=text("0"))
    asset_ftp_profit: Mapped[Decimal] = mapped_column(Amount, server_default=text("0"))
    liability_ftp_profit: Mapped[Decimal] = mapped_column(Amount, server_default=text("0"))
    net_ftp_profit: Mapped[Decimal] = mapped_column(Amount, server_default=text("0"))

    #: Weighted-average components, kept additive.
    roi_x_balance: Mapped[Decimal] = mapped_column(Amount, server_default=text("0"))
    ftp_rate_x_balance: Mapped[Decimal] = mapped_column(Amount, server_default=text("0"))
    total_balance: Mapped[Decimal] = mapped_column(Money, server_default=text("0"))

    account_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    negative_ftp_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class AggDailyBranch(Base, _AggMixin):
    __tablename__ = "agg_daily_branch"
    branch_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    branch_code: Mapped[str] = mapped_column(String(10))
    division_id: Mapped[int] = mapped_column(Integer, index=True)
    district_id: Mapped[int] = mapped_column(Integer, index=True)
    branch_category: Mapped[BranchCategory] = mapped_column(
        pg_enum(BranchCategory, "branch_category")
    )


class AggDailyProduct(Base, _AggMixin):
    __tablename__ = "agg_daily_product"
    product_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_code: Mapped[str] = mapped_column(String(40))
    side: Mapped[Side] = mapped_column(pg_enum(Side, "product_side"))


class AggDailyBranchProduct(Base, _AggMixin):
    """Powers the branch x product heatmap."""

    __tablename__ = "agg_daily_branch_product"
    branch_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    branch_code: Mapped[str] = mapped_column(String(10))
    product_code: Mapped[str] = mapped_column(String(40))


class AggDailyDivision(Base, _AggMixin):
    __tablename__ = "agg_daily_division"
    division_id: Mapped[int] = mapped_column(Integer, primary_key=True)


class AggDailyDistrict(Base, _AggMixin):
    __tablename__ = "agg_daily_district"
    district_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    division_id: Mapped[int] = mapped_column(Integer, index=True)


class AggDailyCategory(Base, _AggMixin):
    __tablename__ = "agg_daily_category"
    branch_category: Mapped[BranchCategory] = mapped_column(
        pg_enum(BranchCategory, "branch_category"), primary_key=True
    )
