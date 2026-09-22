"""Ingestion: sources, mapping profiles, batches, staging and exceptions."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger, Date, DateTime, ForeignKey, Index, Integer, String, Text, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.types import Severity
from app.models.base import (
    Amount, AuthorshipMixin, Base, Money, Rate, TimestampMixin, pg_enum,
)

BATCH_STATUSES = (
    "RECEIVED", "PARSING", "PARSED", "VALIDATED", "AWAITING_REVIEW",
    "COMMITTED", "CALCULATING", "COMPLETED", "FAILED", "CANCELLED",
)


class SourceSystem(Base, TimestampMixin):
    """Where data arrives from. Adding one is configuration, not a migration."""

    __tablename__ = "source_systems"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    adapter_type: Mapped[str] = mapped_column(String(20))  # EXCEL|CSV|PARQUET|API|SFTP
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class ColumnMappingProfile(Base, TimestampMixin, AuthorshipMixin):
    """A versioned source layout.

    The batch records which profile version parsed it, so a file can always be
    re-read exactly as it was originally read even after the profile changes.
    """

    __tablename__ = "column_mappings"
    __table_args__ = (
        Index("uq_column_mapping_name_version", "name", "version", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_system_id: Mapped[int] = mapped_column(ForeignKey("source_systems.id"))
    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    mapping: Mapped[dict] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class UploadBatch(Base, TimestampMixin):
    """One file, tracked end to end.

    Restatement never deletes: a re-upload for a date supersedes the prior batch
    and both remain queryable. Dashboards filter `is_current`; auditors can view
    and diff any prior version.
    """

    __tablename__ = "upload_batches"
    __table_args__ = (
        Index("ix_batch_date_current", "business_date", "is_current"),
        Index("ix_batch_status", "status", "uploaded_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    batch_ref: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    source_system_id: Mapped[int | None] = mapped_column(ForeignKey("source_systems.id"))
    column_mapping_id: Mapped[int | None] = mapped_column(ForeignKey("column_mappings.id"))

    business_date: Mapped[date | None] = mapped_column(Date, index=True)
    file_name: Mapped[str] = mapped_column(String(260))
    #: Content hash. A duplicate upload is rejected outright, naming the original.
    file_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    storage_uri: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(20), server_default=text("'RECEIVED'"))
    status_message: Mapped[str | None] = mapped_column(Text)

    total_rows: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    accepted_rows: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    warned_rows: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    rejected_rows: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    structural_rows: Mapped[int] = mapped_column(Integer, server_default=text("0"))

    supersedes_batch_id: Mapped[int | None] = mapped_column(BigInteger)
    superseded_by_batch_id: Mapped[int | None] = mapped_column(BigInteger)
    is_current: Mapped[bool] = mapped_column(server_default=text("true"))

    uploaded_by: Mapped[int | None] = mapped_column(BigInteger)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    committed_by: Mapped[int | None] = mapped_column(BigInteger)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    calculation_run_id: Mapped[int | None] = mapped_column(BigInteger)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StagingAccountData(Base):
    """Landing zone, one row per parsed source row.

    UNLOGGED in the migration: the content is rebuildable from the stored
    original file, so skipping WAL is safe and materially faster at volume.
    """

    __tablename__ = "staging_account_data"
    __table_args__ = (
        Index("ix_staging_batch_row", "batch_id", "source_row_no"),
        Index("ix_staging_batch_status", "batch_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    batch_id: Mapped[int] = mapped_column(BigInteger, index=True)
    source_row_no: Mapped[int] = mapped_column(Integer)
    origin: Mapped[str | None] = mapped_column(String(120))

    business_date: Mapped[date | None] = mapped_column(Date)
    branch_code: Mapped[str | None] = mapped_column(String(10))
    account_no: Mapped[str | None] = mapped_column(String(40))
    side: Mapped[str | None] = mapped_column(String(10))
    product_code: Mapped[str | None] = mapped_column(String(40))

    balance: Mapped[Decimal | None] = mapped_column(Money)
    int_payable: Mapped[Decimal | None] = mapped_column(Amount)
    int_receivable: Mapped[Decimal | None] = mapped_column(Amount)
    roi: Mapped[Decimal | None] = mapped_column(Rate)

    extras: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(10), server_default=text("'OK'"))
    rule_code: Mapped[str | None] = mapped_column(String(10))


class BankDailyAccountData(Base):
    """Raw bank-provided data, exactly as supplied, after validation.

    Preserved separately from the calculated results so the inputs can always be
    re-examined independently of any engine or configuration version.
    """

    __tablename__ = "bank_daily_account_data"
    __table_args__ = (
        Index("ix_bank_daily_key", "business_date", "branch_code", "account_no"),
        Index("ix_bank_daily_batch", "batch_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    batch_id: Mapped[int] = mapped_column(BigInteger)
    business_date: Mapped[date] = mapped_column(Date)
    branch_code: Mapped[str] = mapped_column(String(10))
    account_no: Mapped[str] = mapped_column(String(40))
    side: Mapped[str] = mapped_column(String(10))
    product_code: Mapped[str] = mapped_column(String(40))

    balance: Mapped[Decimal] = mapped_column(Money)
    raw_int_payable: Mapped[Decimal | None] = mapped_column(Amount)
    raw_int_receivable: Mapped[Decimal | None] = mapped_column(Amount)
    raw_roi: Mapped[Decimal | None] = mapped_column(Rate)

    source_row_no: Mapped[int | None] = mapped_column(Integer)
    validation_status: Mapped[str] = mapped_column(String(10), server_default=text("'OK'"))
    is_current: Mapped[bool] = mapped_column(server_default=text("true"))
    #: Which batch retired this row. Recorded per row rather than inferred from
    #: the date, because a MERGE retires only the account-days it contains --
    #: without this, undoing a batch could not tell which rows to bring back.
    superseded_by_batch_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class UploadException(Base):
    """One rule firing on one row, retained so a user can fix the source file.

    Rejections are counted and explained; nothing is dropped silently.
    """

    __tablename__ = "upload_exceptions"
    __table_args__ = (
        Index("ix_exception_batch_rule", "batch_id", "rule_code"),
        Index("ix_exception_severity", "batch_id", "severity"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    batch_id: Mapped[int] = mapped_column(BigInteger, index=True)
    source_row_no: Mapped[int | None] = mapped_column(Integer)
    #: Human-readable "<sheet>!<row>" so the user can open the exact cell.
    origin: Mapped[str | None] = mapped_column(String(120))
    severity: Mapped[Severity] = mapped_column(pg_enum(Severity, "exception_severity"))
    rule_code: Mapped[str] = mapped_column(String(10))
    field_name: Mapped[str | None] = mapped_column(String(40))
    raw_value: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
