"""Product master and user-defined fields (plan §4.3, §4.4)."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.types import LiabilityNature, Side
from app.models.base import AuthorshipMixin, Base, TimestampMixin, pg_enum


class Product(Base, TimestampMixin, AuthorshipMixin):
    """Product identity. Rates live in `product_rate_config`, not here.

    Identity changes rarely; rates change often, must be effective-dated, and
    must be separately approvable. Keeping them apart is what lets a rate change
    go through maker-checker without re-approving the product itself.
    """

    __tablename__ = "products"
    __table_args__ = (
        # DEMAND/TIME applies to liabilities only. Enforced in the database so
        # an asset can never acquire a liability nature by any code path.
        CheckConstraint(
            "(side = 'LIABILITY' AND liability_nature IS NOT NULL) OR "
            "(side = 'ASSET' AND liability_nature IS NULL)",
            name="liability_nature_matches_side",
        ),
        Index("ix_products_side_active", "side", "is_active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    #: The code exactly as it appears in the bank feed.
    product_code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    short_name: Mapped[str] = mapped_column(String(60))
    details: Mapped[str | None] = mapped_column(Text)
    side: Mapped[Side] = mapped_column(pg_enum(Side, "product_side"))
    liability_nature: Mapped[LiabilityNature | None] = mapped_column(
        pg_enum(LiabilityNature, "liability_nature")
    )
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    udf: Mapped[dict | None] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class UdfDefinition(Base, TimestampMixin, AuthorshipMixin):
    """HO-defined extra attributes, without a code change.

    Values live in the owning row's `udf` JSONB. The API validates submitted
    values against the active definitions on write, so the JSONB cannot drift
    from its declared schema.

    UDFs are descriptive only -- they never participate in the FTP calculation,
    which keeps the engine's inputs closed and exhaustively testable.
    """

    __tablename__ = "udf_definitions"
    __table_args__ = (
        Index("uq_udf_entity_key", "entity", "field_key", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    entity: Mapped[str] = mapped_column(String(20))       # PRODUCT | BRANCH
    field_key: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(120))
    data_type: Mapped[str] = mapped_column(String(20))    # TEXT|NUMBER|DATE|BOOLEAN|ENUM
    required: Mapped[bool] = mapped_column(server_default=text("false"))
    options: Mapped[dict | None] = mapped_column(JSONB)
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
