"""Stored results for the analytics that read the account-level fact table.

Those queries scan every account-day in the window. On a workstation that is a
fraction of a second; on a small managed database (a tenth of a CPU) it is tens
of seconds, and a page that fires several at once never finishes. A result is
therefore computed once per *data version* and read back from `analytics_cache`
until the data changes.

What makes a stored result safe to reuse
----------------------------------------
* It is keyed on the method, its exact arguments (the `Filters` included), the
  caller's resolved scope and the data version -- so a branch user can never be
  served a head-office result, and one filter never answers for another.
* The data version is the newest `audit_log` id plus today's date. Every change
  that can move a figure -- an upload, a deletion, a recalculation, a master or
  rate edit -- writes its audit row in the same transaction as the change, so
  the version moves exactly when the data does. The date is there because some
  results (the staleness warning) depend on today.
* Lookups happen inside repository methods, i.e. after the endpoint's
  authentication and permission checks have already passed.
* Results are stored pickled, so Decimals and dates come back exactly as the
  query produced them. Only this module writes the table.

Any failure here (table missing before the migration has run, a network blip)
falls back to computing the result normally: the cache can make a request
faster, never make it fail.
"""

from __future__ import annotations

import functools
import hashlib
import logging
import pickle
import threading
from datetime import date
from typing import Any, Callable, TypeVar

from sqlalchemy import text

from app.core.db import engine

log = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

#: Computing a missing result may legitimately take longer than the
#: database-wide statement cap that protects the live server from pile-ups.
#: Concurrent requests for the same result wait on one computation (below), so
#: lifting the cap for the computation itself does not reintroduce the pile-up.
COMPUTE_STATEMENT_TIMEOUT = "90s"
#: The median and distribution queries sort the whole window; the managed
#: default (about 2 MB) sends those sorts to disk.
COMPUTE_WORK_MEM = "32MB"

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def data_version(session) -> str:
    """Moves whenever anything that can change a figure is committed."""
    latest = session.execute(text("SELECT coalesce(max(id), 0) FROM audit_log")).scalar()
    return f"{latest}:{date.today().isoformat()}"


def _scope_repr(scope) -> str:
    if scope is None:
        return "none"
    if scope.unrestricted:
        return "HO"
    return ",".join(str(b) for b in sorted(scope.branch_ids))


def _key(method: str, scope, version: str, args: tuple, kwargs: dict) -> str:
    raw = repr((method, _scope_repr(scope), version, args, sorted(kwargs.items())))
    return hashlib.sha256(raw.encode()).hexdigest()


def _read(key: str) -> tuple[bool, Any]:
    try:
        with engine.connect() as conn:
            payload = conn.execute(
                text("SELECT payload FROM analytics_cache WHERE cache_key = :k"),
                {"k": key},
            ).scalar()
        if payload is None:
            return False, None
        return True, pickle.loads(payload)
    except Exception:  # noqa: BLE001 - a cache miss, never an error
        log.warning("analytics cache read failed", exc_info=True)
        return False, None


def _write(key: str, version: str, method: str, value: Any) -> None:
    try:
        payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO analytics_cache (cache_key, version, method, payload) "
                     "VALUES (:k, :v, :m, :p) ON CONFLICT (cache_key) DO NOTHING"),
                {"k": key, "v": version, "m": method, "p": payload},
            )
            # Results from superseded versions can never be read again.
            conn.execute(text("DELETE FROM analytics_cache WHERE version <> :v"),
                         {"v": version})
    except Exception:  # noqa: BLE001
        log.warning("analytics cache write failed", exc_info=True)


def cached(fn: F) -> F:
    """Serve a repository method's result from the cache when the data is
    unchanged; otherwise compute it once and store it.

    The decorated method's instance must carry `s` (the request session) and
    `scope` (the caller's ScopeFilter), as both repositories do.
    """
    method = f"{fn.__qualname__}"

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            version = data_version(self.s)
        except Exception:  # noqa: BLE001
            log.warning("analytics cache version failed", exc_info=True)
            return fn(self, *args, **kwargs)

        key = _key(method, self.scope, version, args, kwargs)
        hit, value = _read(key)
        if hit:
            return value

        with _lock_for(key):
            hit, value = _read(key)        # another request may have just built it
            if hit:
                return value
            self.s.execute(text(f"SET LOCAL statement_timeout = '{COMPUTE_STATEMENT_TIMEOUT}'"))
            self.s.execute(text(f"SET LOCAL work_mem = '{COMPUTE_WORK_MEM}'"))
            value = fn(self, *args, **kwargs)
            _write(key, version, method, value)
            return value

    return wrapper  # type: ignore[return-value]
