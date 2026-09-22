"""side on the branch x product aggregate

A branch x product row is single-sided by construction. Without the column a
`side` filter found no attribute to filter on and was silently dropped, so the
dashboard answered as though the filter had not been set.

Revision ID: f4a5b6700004
Revises: e3f4a5600003
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f4a5b6700004"
down_revision: Union[str, None] = "e3f4a5600003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agg_daily_branch_product",
        sa.Column("side",
                  sa.Enum("ASSET", "LIABILITY", name="product_side",
                          create_type=False),
                  nullable=False, server_default="ASSET"),
    )
    # Aggregates are rebuilt from facts on every run, but backfill so existing
    # rows are correct before the next one.
    op.execute("""
        UPDATE agg_daily_branch_product a
           SET side = p.side
          FROM products p
         WHERE p.id = a.product_id
    """)
    op.create_index("ix_agg_bp_side", "agg_daily_branch_product", ["side"])


def downgrade() -> None:
    op.drop_index("ix_agg_bp_side", "agg_daily_branch_product")
    op.drop_column("agg_daily_branch_product", "side")
