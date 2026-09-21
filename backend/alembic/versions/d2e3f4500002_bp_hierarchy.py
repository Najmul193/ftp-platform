"""hierarchy columns on the branch x product aggregate

Lets cross-dimensional leadership questions ("which product leads in each
district", "top branch per division") resolve from a single aggregate scan
rather than dropping to the partitioned fact table.

Revision ID: d2e3f4500002
Revises: c1d2e3f40001
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d2e3f4500002"
down_revision: Union[str, None] = "c1d2e3f40001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "agg_daily_branch_product"


def upgrade() -> None:
    # Aggregates are rebuilt from facts on every run, so adding NOT NULL columns
    # with a default is safe: the next refresh repopulates them truthfully.
    op.add_column(TABLE, sa.Column("division_id", sa.Integer(), nullable=False,
                                   server_default=sa.text("0")))
    op.add_column(TABLE, sa.Column("district_id", sa.Integer(), nullable=False,
                                   server_default=sa.text("0")))
    op.add_column(TABLE, sa.Column(
        "branch_category",
        sa.Enum("METRO", "URBAN", "SEMI_URBAN", "RURAL",
                name="branch_category", create_type=False),
        nullable=False, server_default="URBAN"))
    op.add_column(TABLE, sa.Column("product_short_name", sa.String(60), nullable=True))
    op.create_index(f"ix_{TABLE}_division_id", TABLE, ["division_id"])
    op.create_index(f"ix_{TABLE}_district_id", TABLE, ["district_id"])


def downgrade() -> None:
    op.drop_index(f"ix_{TABLE}_district_id", TABLE)
    op.drop_index(f"ix_{TABLE}_division_id", TABLE)
    for col in ("product_short_name", "branch_category", "district_id", "division_id"):
        op.drop_column(TABLE, col)
