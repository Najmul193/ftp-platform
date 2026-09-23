"""analytics result cache

The heavy analytics (repricing, the watchlist, rate distribution, outliers,
leakage, account risk) read the account-level fact table rather than the
aggregates. On a small managed database that is tens of seconds per request, so
a result is stored once per data version and served from here until the data
changes. Rows are disposable: truncating the table only costs recomputation.

Revision ID: g5b6c7800006
Revises: f4a5b6700004
"""
from typing import Sequence, Union

from alembic import op

revision: str = "g5b6c7800006"
down_revision: Union[str, None] = "f4a5b6700004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE analytics_cache (
            cache_key   varchar(64)  PRIMARY KEY,
            version     varchar(80)  NOT NULL,
            method      varchar(80)  NOT NULL,
            payload     bytea        NOT NULL,
            created_at  timestamptz  NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_analytics_cache_version ON analytics_cache (version)")


def downgrade() -> None:
    op.execute("DROP TABLE analytics_cache")
