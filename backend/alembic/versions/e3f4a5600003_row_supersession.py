"""per-row supersession, so a batch can be undone precisely

A REPLACE retires the whole date; a MERGE retires only the account-days it
carries. Recording the retiring batch on each row is what makes deleting a
batch reversible: without it, restoring the previous state would have to guess
which rows the batch displaced.

Revision ID: e3f4a5600003
Revises: d2e3f4500002
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e3f4a5600003"
down_revision: Union[str, None] = "d2e3f4500002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bank_daily_account_data",
        sa.Column("superseded_by_batch_id", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ix_bank_daily_superseded_by",
        "bank_daily_account_data",
        ["superseded_by_batch_id"],
        postgresql_where=sa.text("superseded_by_batch_id IS NOT NULL"),
    )
    # Backfill what can be known: rows already retired were retired by the batch
    # that currently claims to supersede theirs.
    op.execute("""
        UPDATE bank_daily_account_data b
           SET superseded_by_batch_id = ub.superseded_by_batch_id
          FROM upload_batches ub
         WHERE ub.id = b.batch_id
           AND b.is_current = false
           AND ub.superseded_by_batch_id IS NOT NULL
    """)


def downgrade() -> None:
    op.drop_index("ix_bank_daily_superseded_by", "bank_daily_account_data")
    op.drop_column("bank_daily_account_data", "superseded_by_batch_id")
