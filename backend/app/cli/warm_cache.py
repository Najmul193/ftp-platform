"""Compute and store the dashboard results people open first.

Stored analytics results are keyed on the data version, so after every upload
the first viewer of each page would otherwise pay for the computation. On a
small managed database that first view can take longer than the page is
willing to wait. Run this after loading data to take that cost up front:

    python -m app.cli.warm_cache            # the default (unfiltered) views
    python -m app.cli.warm_cache --divisions  # plus each division's views

The server also starts it by itself after every upload and deletion
(app.services.cache_warm), with --after-batch so it waits for that change to be
committed before computing anything.

Requests go through the application in-process, exactly as the browser sends
them, as the head-office `admin` user, so the stored results are the ones a
head-office viewer will be served.
"""

from __future__ import annotations

import argparse
import time

from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.core.db import SessionLocal, engine
from app.core.security import create_access_token
from app.main import app
from app.models import Division, User

DIMS = ("product", "branch", "division", "district", "category")
WARM_LOCK_KEY = 820_260_924   # arbitrary, unique to this job

#: The requests each page makes when it opens with no filters, taken from the
#: access log of real browser sessions, plus the options behind each page's
#: selectors.
DEFAULT_PATHS = [
    # Basic overview / Overview
    "/dashboard/kpis", "/dashboard/by-branch", "/dashboard/by-product",
    "/dashboard/by-division", "/dashboard/by-district", "/dashboard/by-category",
    "/dashboard/trend", "/dashboard/heatmap",
    "/analytics/summary", "/analytics/trend?ma_window=7", "/analytics/spread-waterfall",
    "/analytics/balance-sheet", "/analytics/movers",
    # Daily
    "/analytics/watchlist", "/analytics/nii-reconciliation", "/analytics/banking-ratios",
    "/analytics/period-summary", "/analytics/repricing", "/analytics/deposit-cost",
    # Analytics
    "/analytics/rate-distribution?buckets=12", "/analytics/leakage",
    # Accounts / Consolidated
    "/analytics/outliers?z=2.5",
    "/dashboard/accounts?limit=50&offset=0&order=ftp_income&desc=true",
    "/dashboard/accounts?limit=50&offset=0&order=business_date&desc=false",
    # Leaders
    "/analytics/headline-performers",
]
for d in DIMS:
    DEFAULT_PATHS += [
        f"/analytics/variance-bridge?by={d}", f"/analytics/concentration?by={d}",
        f"/analytics/rankings?by={d}", f"/analytics/scatter?by={d}",
        f"/analytics/account-risk?by={d}", f"/analytics/product-leadership?area={d}",
    ]
    for metric in ("profit", "yield"):
        DEFAULT_PATHS.append(
            f"/analytics/leaderboard?group={d}&of=branch&top=3&metric={metric}")

#: What a division filter changes on the pages most likely to be drilled into.
DIVISION_PATHS = [
    "/dashboard/kpis", "/dashboard/by-branch", "/dashboard/by-product",
    "/dashboard/by-district", "/dashboard/trend", "/analytics/summary",
    "/analytics/watchlist", "/analytics/repricing", "/analytics/banking-ratios",
    "/analytics/deposit-cost", "/analytics/nii-reconciliation",
    "/analytics/period-summary", "/analytics/rate-distribution?buckets=12",
]


def main() -> int:
    ap = argparse.ArgumentParser(description="Pre-compute stored dashboard results")
    ap.add_argument("--divisions", action="store_true",
                    help="also warm each division's views")
    ap.add_argument("--after-batch", default=None,
                    help="wait until this upload batch is committed (or gone) first")
    ap.add_argument("--expect", choices=("present", "absent"), default="present")
    args = ap.parse_args()

    if args.after_batch and not _wait_for_batch(args.after_batch, args.expect):
        print(f"warm-up skipped: batch {args.after_batch} never became {args.expect}")
        return 1

    # One warm-up at a time. A later one waits for the earlier to finish and then
    # runs, so the newest data version is always the one left warm.
    lock_conn = engine.connect()
    lock_conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": WARM_LOCK_KEY})
    try:
        return _warm(args)
    finally:
        lock_conn.close()


def _wait_for_batch(batch_ref: str, expect: str, timeout_s: int = 60) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        with SessionLocal() as s:
            status = s.execute(
                text("SELECT status FROM upload_batches WHERE batch_ref = :r"),
                {"r": batch_ref},
            ).scalar()
        if expect == "present" and status == "COMPLETED":
            return True
        if expect == "absent" and status is None:
            return True
        time.sleep(2)
    return False


def _warm(args) -> int:
    with SessionLocal() as s:
        admin = s.scalar(select(User).filter_by(username="admin"))
        if admin is None:
            print("no admin user")
            return 1
        token = create_access_token(
            str(admin.id),
            {"username": admin.username, "scope": admin.scope_level.value,
             "roles": [ur.role.code for ur in admin.roles]},
        )
        paths = list(DEFAULT_PATHS)
        if args.divisions:
            for (div_id,) in s.execute(select(Division.id).order_by(Division.id)):
                for p in DIVISION_PATHS:
                    sep = "&" if "?" in p else "?"
                    paths.append(f"{p}{sep}division_id={div_id}")
        before = s.execute(text("SELECT count(*) FROM analytics_cache")).scalar()

    failures = 0
    started = time.monotonic()
    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {token}"}
        for i, p in enumerate(paths, 1):
            t = time.monotonic()
            r = client.get(f"/api/v1{p}", headers=headers)
            ok = r.status_code == 200
            failures += not ok
            print(f"[{i:>3}/{len(paths)}] {r.status_code} {time.monotonic() - t:6.1f}s  {p}",
                  flush=True)

    with SessionLocal() as s:
        after = s.execute(text("SELECT count(*) FROM analytics_cache")).scalar()
    print(f"done in {time.monotonic() - started:.0f}s: {len(paths) - failures} ok, "
          f"{failures} failed; stored results {before} -> {after}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
