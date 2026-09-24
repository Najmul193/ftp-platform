"""day-count divisor on facts and aggregates

The engine prices each date on the day-count basis in force for it (ACT/365
divisor 36,500; ACT/360 divisor 36,000). The divisor is stored with the figures
rather than looked up from configuration, so a date kept on earlier rates stays
explained by the basis it was actually computed on, and analytics can turn any
rollup of `rate x balance` into income by dividing each day by its own divisor.

Every existing row was priced on ACT/365, the only basis the engine applied
before this revision, so the constant default is also the correct backfill.

Revision ID: h6c7d8900007
Revises: g5b6c7800006
"""
from typing import Sequence, Union

from alembic import op

revision: str = "h6c7d8900007"
down_revision: Union[str, None] = "g5b6c7800006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = (
    "ftp_calculation_results",
    "agg_daily_branch", "agg_daily_product", "agg_daily_branch_product",
    "agg_daily_division", "agg_daily_district", "agg_daily_category",
)


def upgrade() -> None:
    # A constant default is a catalogue-only change in PostgreSQL 11+: no table
    # rewrite, so this is safe on the partitioned fact table at any volume.
    for t in TABLES:
        op.execute(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS day_divisor "
                   f"integer NOT NULL DEFAULT 36500")


def downgrade() -> None:
    for t in TABLES:
        op.execute(f"ALTER TABLE {t} DROP COLUMN IF EXISTS day_divisor")
