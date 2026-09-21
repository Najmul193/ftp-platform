"""Declarative base, shared column types and mixins."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, DateTime, Enum as SAEnum, MetaData, Numeric, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

#: Explicit naming so Alembic autogenerate produces stable, reviewable names
#: rather than database-assigned ones that churn between environments.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map = {
        dict[str, Any]: JSONB,
        Decimal: Numeric(20, 6),
    }


def pg_enum(enum_cls: type, name: str) -> SAEnum:
    """A native PostgreSQL enum that stores the member *value*."""
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=True,
        values_callable=lambda e: [m.value for m in e],
        create_type=True,
    )


#: Rates: percent to 6 dp, matching `domain.calculation.RATE_SCALE`.
Rate = Numeric(12, 6)
#: Amounts: 6 dp, matching `domain.calculation.AMOUNT_SCALE`.
Amount = Numeric(20, 6)
#: Balances as supplied by the bank.
Money = Numeric(20, 2)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )


class AuthorshipMixin:
    """Who created and last changed the row.

    Denormalised alongside the audit trail on purpose: the audit log is the
    legal record, but having the actor on the row itself keeps admin screens
    readable without a join per row.
    """

    created_by: Mapped[int | None] = mapped_column(BigInteger)
    updated_by: Mapped[int | None] = mapped_column(BigInteger)
