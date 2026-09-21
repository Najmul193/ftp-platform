"""Engine and session factory.

Synchronous SQLAlchemy, a conscious deviation from the plan's async note. The
read path is served from pre-aggregated tables (sub-millisecond queries) and the
write path is bulk COPY inside a worker, so async concurrency buys nothing here
while costing testability and stack-trace clarity. If a future read path becomes
I/O-bound and fan-out heavy, this is the one module that changes.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,          # a recycled Render connection fails fast, not mid-query
    echo=settings.DB_ECHO,
    future=True,
)


@event.listens_for(engine, "connect")
def _set_statement_timeout(dbapi_connection, _record) -> None:
    """Bound every statement. Saturation should queue, never hang (principle P7)."""
    with dbapi_connection.cursor() as cur:
        cur.execute(f"SET statement_timeout = {settings.DB_STATEMENT_TIMEOUT_MS}")


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope. Commits on success, rolls back on any exception.

    Services use this so that a change and its audit row share one transaction
    -- a committed change without its audit record is then impossible.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    with session_scope() as session:
        yield session


def healthcheck() -> bool:
    with engine.connect() as conn:
        return conn.execute(text("SELECT 1")).scalar() == 1
