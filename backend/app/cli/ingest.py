"""Run the ingestion pipeline from the command line.

    python -m app.cli.ingest <file> [--date YYYY-MM-DD] [--sheet NAME] [--preview]
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from sqlalchemy import select

from app.core.db import session_scope
from app.models import User
from app.services.pipeline import PipelineError, UploadPipeline


def main() -> int:
    ap = argparse.ArgumentParser(description="Ingest a bank data file")
    ap.add_argument("file", type=Path)
    ap.add_argument("--date", type=date.fromisoformat, default=None,
                    help="business date for a daily single-sheet file")
    ap.add_argument("--sheet", default=None, help="worksheet to read")
    ap.add_argument("--preview", action="store_true",
                    help="validate and report without committing")
    ap.add_argument("--user", default="admin")
    args = ap.parse_args()

    with session_scope() as s:
        actor = s.scalar(select(User).filter_by(username=args.user))
        pipe = UploadPipeline(
            s, actor_id=actor.id if actor else None,
            actor_username=actor.username if actor else args.user,
        )
        try:
            r = pipe.run(args.file, business_date=args.date, sheet_name=args.sheet,
                         auto_commit=not args.preview)
        except PipelineError as exc:
            print(f"FAILED: {exc}")
            return 1

    print(f"batch     {r.batch_ref}   status {r.status}")
    print(f"rows      {r.total_rows} total | {r.accepted_rows} accepted | "
          f"{r.warned_rows} warned | {r.rejected_rows} rejected | "
          f"{r.structural_rows} structural")
    if r.business_dates:
        print(f"dates     {r.business_dates[0]} .. {r.business_dates[-1]} "
              f"({len(r.business_dates)})")
    if r.run_ref:
        print(f"run       {r.run_ref}")
    if r.exceptions_by_rule:
        print(f"rules     {r.exceptions_by_rule}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
