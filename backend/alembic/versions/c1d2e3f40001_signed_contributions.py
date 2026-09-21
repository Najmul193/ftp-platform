"""signed rate contributions

Replaces the unsigned component columns with signed contributions, so that

    ftp_rate_x_balance = benchmark + roi + liquidity + other contributions

holds at every grain including a branch that mixes assets and liabilities.
Unsigned components cannot decompose a mixed-side rollup because the liability
and asset spread formulas carry opposite signs.

Revision ID: c1d2e3f40001
Revises: 86851de8e2df
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c1d2e3f40001"
down_revision: Union[str, None] = "86851de8e2df"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = (
    "agg_daily_branch", "agg_daily_product", "agg_daily_branch_product",
    "agg_daily_division", "agg_daily_district", "agg_daily_category",
)
RENAMES = {
    "benchmark_x_balance": "benchmark_contrib",
    "liquidity_x_balance": "liquidity_contrib",
    "other_x_balance": "other_contrib",
}


def upgrade() -> None:
    for table in TABLES:
        for old, new in RENAMES.items():
            op.alter_column(table, old, new_column_name=new)
        op.add_column(
            table,
            sa.Column("roi_contrib", sa.Numeric(20, 6), nullable=False,
                      server_default=sa.text("0")),
        )


def downgrade() -> None:
    for table in TABLES:
        op.drop_column(table, "roi_contrib")
        for old, new in RENAMES.items():
            op.alter_column(table, new, new_column_name=old)
