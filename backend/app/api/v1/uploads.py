"""Upload routes -- the daily Excel path."""

from __future__ import annotations

import shutil
from datetime import date
from typing import Literal
from pathlib import Path

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile,
    status,
)
from sqlalchemy import select

from app.api.deps import DbDep, UserDep, require
from app.api.schemas import BatchOut, ExceptionOut, UploadResult
from app.core.config import settings
from app.ingestion.adapters.excel import ExcelAdapter
from app.ingestion.mapping import LEGACY_WORKBOOK_MAPPING
from app.models import UploadBatch, UploadException
from app.services.pipeline import PipelineError, UploadMode, UploadPipeline
from app.services.rejects import build_rejects_workbook

router = APIRouter(prefix="/uploads", tags=["uploads"])

ALLOWED_SUFFIXES = {".xlsx", ".xlsm", ".csv"}
#: ZIP magic. Both .xlsx and .xlsm are zip containers; anything else is refused
#: before a parser ever sees it.
ZIP_MAGIC = b"PK\x03\x04"


def _store(upload: UploadFile) -> Path:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"{suffix or 'file'} is not accepted; allowed: "
            f"{sorted(ALLOWED_SUFFIXES)}",
        )

    head = upload.file.read(4)
    upload.file.seek(0)
    if suffix in {".xlsx", ".xlsm"} and head != ZIP_MAGIC:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "file extension says Excel but the content is not a valid workbook",
        )

    target_dir = Path(settings.UPLOAD_STORAGE_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{date.today():%Y%m%d}-{upload.filename}"

    with target.open("wb") as fh:
        shutil.copyfileobj(upload.file, fh, length=1024 * 1024)

    if target.stat().st_size > settings.UPLOAD_MAX_BYTES:
        target.unlink(missing_ok=True)
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"file exceeds {settings.UPLOAD_MAX_BYTES // 1024 // 1024} MB",
        )
    return target


@router.post("/probe", dependencies=[Depends(require("UPLOAD_CREATE"))])
def probe(file: UploadFile = File(...)):
    """Inspect a workbook without ingesting anything.

    Shows which sheets qualify and which do not, each with a reason. A sheet is
    never passed over in silence -- that is how a day goes missing unnoticed.
    """
    path = _store(file)
    result = ExcelAdapter(LEGACY_WORKBOOK_MAPPING).probe(path)
    return {
        "ok": result.ok,
        "errors": result.errors,
        "header_issues": result.header_issues,
        "business_dates": [d.isoformat() for d in result.business_dates],
        "total_data_rows": result.total_data_rows,
        "looks_like_rejects_export": result.looks_like_rejects_export,
        "suggested_mode": "merge" if result.looks_like_rejects_export else "replace",
        "sheets": [
            {"name": s.name,
             "business_date": s.business_date.isoformat() if s.business_date else None,
             "included": s.included, "reason": s.reason, "data_rows": s.data_rows}
            for s in result.sheets
        ],
    }


@router.post("", response_model=UploadResult,
             dependencies=[Depends(require("UPLOAD_CREATE"))])
def upload(
    db: DbDep,
    user: UserDep,
    file: UploadFile = File(...),
    business_date: date | None = Form(None),
    sheet_name: str | None = Form(None),
    auto_commit: bool = Form(True),
    mode: Literal["replace", "merge"] = Form("replace"),
):
    """Ingest a file end to end.

    Three shapes are supported, in order of how often they occur:

    * a single daily sheet -- supply `business_date` if the sheet is not
      date-named;
    * a multi-sheet workbook plus `sheet_name`;
    * a full historical backfill, with neither, which loads every date-named
      sheet using its own name as the date.

    `mode` decides what happens to data already loaded for the same date:

    * `replace` (default) -- the bank resent the day, so anything absent from
      the new file is gone.
    * `merge` -- a completion file, typically the rejected-rows workbook sent
      back once the missing branch or product was registered. Only the accounts
      present in the file are superseded; the rest of the day stays.
    """
    path = _store(file)
    pipe = UploadPipeline(db, actor_id=user.id, actor_username=user.username)
    try:
        result = pipe.run(
            path, business_date=business_date, sheet_name=sheet_name,
            auto_commit=auto_commit, mode=UploadMode(mode),
        )
    except PipelineError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    return UploadResult(
        batch_ref=result.batch_ref, status=result.status,
        total_rows=result.total_rows, accepted_rows=result.accepted_rows,
        warned_rows=result.warned_rows, rejected_rows=result.rejected_rows,
        structural_rows=result.structural_rows,
        business_dates=result.business_dates, run_ref=result.run_ref,
        exceptions_by_rule=result.exceptions_by_rule,
    )


@router.get("", response_model=list[BatchOut],
            dependencies=[Depends(require("UPLOAD_VIEW"))])
def list_batches(db: DbDep, limit: int = Query(50, le=200),
                 status_filter: str | None = None):
    stmt = select(UploadBatch).order_by(UploadBatch.uploaded_at.desc()).limit(limit)
    if status_filter:
        stmt = stmt.where(UploadBatch.status == status_filter)
    return list(db.scalars(stmt))


@router.get("/{batch_ref}", response_model=BatchOut,
            dependencies=[Depends(require("UPLOAD_VIEW"))])
def get_batch(batch_ref: str, db: DbDep):
    batch = db.scalar(select(UploadBatch).filter_by(batch_ref=batch_ref))
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no batch {batch_ref}")
    return batch


@router.get("/{batch_ref}/exceptions", response_model=list[ExceptionOut],
            dependencies=[Depends(require("UPLOAD_VIEW"))])
def batch_exceptions(batch_ref: str, db: DbDep, severity: str | None = None,
                     limit: int = Query(500, le=5000)):
    batch = db.scalar(select(UploadBatch).filter_by(batch_ref=batch_ref))
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no batch {batch_ref}")

    stmt = (
        select(UploadException)
        .where(UploadException.batch_id == batch.id)
        .order_by(UploadException.severity, UploadException.source_row_no)
        .limit(limit)
    )
    if severity:
        stmt = stmt.where(UploadException.severity == severity)
    return list(db.scalars(stmt))


@router.get("/{batch_ref}/rejects.xlsx",
            dependencies=[Depends(require("UPLOAD_VIEW"))])
def download_rejects(batch_ref: str, db: DbDep):
    """Download the rows this batch could not accept, as a re-uploadable workbook.

    The file keeps the bank's original column layout and appends the reason, so
    once the missing branch or product is registered the same file goes straight
    back in. A rejection the operator cannot hand back is one they would have to
    reconstruct by hand.
    """
    batch = db.scalar(select(UploadBatch).filter_by(batch_ref=batch_ref))
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no batch {batch_ref}")

    content, count = build_rejects_workbook(db, batch)
    if not count:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"batch {batch_ref} has no rejected rows",
        )

    name = f"rejected-{batch.business_date or 'rows'}-{batch.batch_ref}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
