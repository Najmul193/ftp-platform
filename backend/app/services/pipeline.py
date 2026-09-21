"""The upload -> recalculation pipeline (plan §8).

Stages, each idempotent and independently resumable:

    RECEIVE -> PARSE -> VALIDATE -> [PREVIEW] -> COMMIT -> CALCULATE
            -> AGGREGATE -> COMPLETE

Restatement never deletes. Re-uploading a date supersedes the previous batch and
both remain queryable: dashboards filter `is_current`, auditors can diff any
prior version.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from sqlalchemy import case, func, select, text, update
from sqlalchemy.orm import Session

from app.core.security import file_digest
from app.domain.calculation import calculate
from app.domain.types import RawRow, Severity, Side, Tolerance
from app.domain.validation import (
    Exception_, ProductInfo, ValidationContext, rejected_rows, validate_batch,
)
from app.ingestion.adapters.excel import ExcelAdapter
from app.ingestion.base import ExtractStats
from app.ingestion.mapping import LEGACY_WORKBOOK_MAPPING, ColumnMapping
from app.models import (
    AggDailyBranch, AggDailyBranchProduct, AggDailyCategory, AggDailyDistrict,
    AggDailyDivision, AggDailyProduct, BankDailyAccountData, Branch,
    CalculationRun, FtpCalculationResult, Product, UploadBatch, UploadException,
)
from app.repositories.rates import RateBook
from app.services import audit


class PipelineError(Exception):
    """A stage could not proceed. The batch is marked FAILED with this message."""


@dataclass
class StageResult:
    batch_ref: str
    status: str
    total_rows: int = 0
    accepted_rows: int = 0
    warned_rows: int = 0
    rejected_rows: int = 0
    structural_rows: int = 0
    business_dates: list[date] = field(default_factory=list)
    exceptions_by_rule: dict[str, int] = field(default_factory=dict)
    run_ref: str | None = None
    message: str | None = None


def _ref(prefix: str) -> str:
    return f"{prefix}-{datetime.now(UTC):%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"


class UploadPipeline:
    """Orchestrates one file from arrival to live dashboards."""

    def __init__(self, session: Session, *, actor_id: int | None = None,
                 actor_username: str | None = None) -> None:
        self.s = session
        self.actor_id = actor_id
        self.actor_username = actor_username

    # ------------------------------------------------------------------ #
    # 1. RECEIVE
    # ------------------------------------------------------------------ #

    def receive(self, path: Path, *, business_date: date | None = None,
                sheet_name: str | None = None) -> UploadBatch:
        """Register the file. A duplicate is rejected outright, naming the original."""
        content = path.read_bytes()
        digest = file_digest(content)

        prior = self.s.scalar(select(UploadBatch).filter_by(file_hash=digest))
        if prior is not None:
            raise PipelineError(
                f"this exact file was already uploaded as {prior.batch_ref} on "
                f"{prior.uploaded_at:%Y-%m-%d %H:%M} (status {prior.status})"
            )

        batch = UploadBatch(
            batch_ref=_ref("UPL"),
            business_date=business_date,
            file_name=path.name,
            file_hash=digest,
            file_size=len(content),
            storage_uri=str(path.resolve()),
            status="RECEIVED",
            uploaded_by=self.actor_id,
        )
        self.s.add(batch)
        self.s.flush()

        audit.record(
            self.s, action="UPLOAD", entity_type="upload_batch",
            entity_id=batch.batch_ref,
            after={"file_name": path.name, "file_hash": digest,
                   "file_size": len(content),
                   "business_date": business_date.isoformat() if business_date else None},
            actor_user_id=self.actor_id, actor_username=self.actor_username,
        )
        return batch

    # ------------------------------------------------------------------ #
    # 2-3. PARSE + VALIDATE
    # ------------------------------------------------------------------ #

    def parse_and_validate(
        self, batch: UploadBatch, *, mapping: ColumnMapping = LEGACY_WORKBOOK_MAPPING,
        business_date: date | None = None, sheet_name: str | None = None,
    ) -> tuple[list[RawRow], list[Exception_], ExtractStats]:
        batch.status = "PARSING"
        self.s.flush()

        adapter = ExcelAdapter(mapping, business_date=business_date, sheet_name=sheet_name)
        stats = ExtractStats()
        rows = list(adapter.extract(Path(batch.storage_uri), stats))

        if not rows:
            raise PipelineError("no data rows were extracted from the file")

        batch.status = "PARSED"
        ctx = self._validation_context(rows, mapping)
        findings, counts = validate_batch(rows, ctx)

        blocked = rejected_rows(findings)
        warned = {f.source_row_no for f in findings
                  if f.severity is Severity.WARN and f.source_row_no}

        for f in findings:
            self.s.add(UploadException(
                batch_id=batch.id, source_row_no=f.source_row_no or None,
                origin=f.origin, severity=f.severity, rule_code=f.rule_code,
                field_name=f.field, raw_value=f.raw_value, message=f.message,
            ))

        batch.total_rows = len(rows)
        batch.rejected_rows = len(blocked)
        batch.accepted_rows = len(rows) - len(blocked)
        batch.warned_rows = len(warned - blocked)
        batch.structural_rows = stats.structural_rows
        batch.status = "VALIDATED"
        dates = sorted({r.business_date for r in rows if r.business_date})
        if len(dates) == 1:
            batch.business_date = dates[0]
        self.s.flush()

        return rows, findings, stats

    def _validation_context(
        self, rows: Iterable[RawRow], mapping: ColumnMapping
    ) -> ValidationContext:
        branches = {
            b.branch_code for b in self.s.scalars(
                select(Branch).where(Branch.is_active.is_(True))
            )
        }
        products = {
            p.product_code: ProductInfo(p.product_code, p.side, p.is_active)
            for p in self.s.scalars(select(Product))
        }

        # One RateBook per distinct date in the file.
        books: dict[date, RateBook] = {}

        def resolver(product_code: str, on: date):
            book = books.get(on)
            if book is None:
                book = books[on] = RateBook(self.s, on)
            return book.resolve(product_code)

        return ValidationContext(
            active_branches=branches,
            products=products,
            rate_resolver=resolver,
            tolerance=Tolerance(),
            mapped_columns=set(mapping.capture_as_extras.values()),
        )

    # ------------------------------------------------------------------ #
    # 4. PREVIEW
    # ------------------------------------------------------------------ #

    @staticmethod
    def preview(batch: UploadBatch, findings: list[Exception_],
                stats: ExtractStats) -> StageResult:
        by_rule: dict[str, int] = defaultdict(int)
        for f in findings:
            by_rule[f.rule_code] += 1
        return StageResult(
            batch_ref=batch.batch_ref, status="AWAITING_REVIEW",
            total_rows=batch.total_rows, accepted_rows=batch.accepted_rows,
            warned_rows=batch.warned_rows, rejected_rows=batch.rejected_rows,
            structural_rows=stats.structural_rows,
            exceptions_by_rule=dict(by_rule),
        )

    # ------------------------------------------------------------------ #
    # 5. COMMIT
    # ------------------------------------------------------------------ #

    def commit_batch(self, batch: UploadBatch, rows: list[RawRow],
                     findings: list[Exception_]) -> list[date]:
        """Promote accepted rows and supersede any prior batch for the same dates."""
        blocked = rejected_rows(findings)
        accepted = [r for r in rows if r.source_row_no not in blocked]
        if not accepted:
            raise PipelineError(
                f"every row was rejected ({batch.rejected_rows} of {batch.total_rows}); "
                "nothing to commit"
            )

        dates = sorted({r.business_date for r in accepted if r.business_date})
        self._supersede_prior(batch, dates)

        self.s.bulk_save_objects([
            BankDailyAccountData(
                batch_id=batch.id, business_date=r.business_date,
                branch_code=r.branch_code, account_no=r.account_no,
                side=r.side, product_code=r.product_code, balance=r.balance,
                raw_int_payable=r.int_payable, raw_int_receivable=r.int_receivable,
                raw_roi=r.roi, source_row_no=r.source_row_no,
            )
            for r in accepted
        ])

        batch.status = "COMMITTED"
        batch.committed_by = self.actor_id
        batch.committed_at = datetime.now(UTC)
        self.s.flush()

        audit.record(
            self.s, action="COMMIT", entity_type="upload_batch",
            entity_id=batch.batch_ref,
            after={"accepted": len(accepted), "rejected": len(blocked),
                   "dates": [d.isoformat() for d in dates]},
            actor_user_id=self.actor_id, actor_username=self.actor_username,
        )
        return dates

    def _supersede_prior(self, batch: UploadBatch, dates: list[date]) -> None:
        """Mark earlier data for these dates superseded. Nothing is deleted."""
        prior_ids = set(self.s.scalars(
            select(BankDailyAccountData.batch_id)
            .where(BankDailyAccountData.business_date.in_(dates))
            .where(BankDailyAccountData.is_current.is_(True))
            .distinct()
        ))
        prior_ids.discard(batch.id)
        if not prior_ids:
            return

        self.s.execute(
            update(BankDailyAccountData)
            .where(BankDailyAccountData.business_date.in_(dates))
            .where(BankDailyAccountData.is_current.is_(True))
            .values(is_current=False)
        )
        self.s.execute(
            update(FtpCalculationResult)
            .where(FtpCalculationResult.business_date.in_(dates))
            .where(FtpCalculationResult.is_current.is_(True))
            .values(is_current=False)
        )
        self.s.execute(
            update(UploadBatch).where(UploadBatch.id.in_(prior_ids))
            .values(is_current=False, superseded_by_batch_id=batch.id)
        )
        batch.supersedes_batch_id = max(prior_ids)

        audit.record(
            self.s, action="SUPERSEDE", entity_type="upload_batch",
            entity_id=batch.batch_ref,
            after={"superseded_batch_ids": sorted(prior_ids),
                   "dates": [d.isoformat() for d in dates]},
            actor_user_id=self.actor_id, actor_username=self.actor_username,
        )

    # ------------------------------------------------------------------ #
    # 6. CALCULATE
    # ------------------------------------------------------------------ #

    def calculate_dates(self, batch: UploadBatch, dates: list[date]) -> CalculationRun:
        """Run the engine over the committed rows for these dates.

        Uses the reference Python engine. At T2+ this becomes the set-based SQL
        projection, whose equivalence to this path is held by the differential
        test -- see plan §15.7.
        """
        batch.status = "CALCULATING"
        run = CalculationRun(
            run_ref=_ref("RUN"), trigger_type="UPLOAD", batch_id=batch.id,
            business_date_from=min(dates), business_date_to=max(dates),
            status="RUNNING", started_at=datetime.now(UTC),
            initiated_by=self.actor_id,
        )
        self.s.add(run)
        self.s.flush()

        branches = {
            b.branch_code: b for b in self.s.scalars(select(Branch))
        }
        products = {p.product_code: p for p in self.s.scalars(select(Product))}

        facts: list[FtpCalculationResult] = []
        rows_in = 0

        for on in dates:
            book = RateBook(self.s, on)
            run.global_config_id = book.global_rates.version

            source = self.s.scalars(
                select(BankDailyAccountData)
                .where(BankDailyAccountData.business_date == on)
                .where(BankDailyAccountData.batch_id == batch.id)
                .where(BankDailyAccountData.is_current.is_(True))
            )

            for rec in source:
                rows_in += 1
                side = Side.from_code(rec.side)
                rates = book.resolve(rec.product_code)
                raw = RawRow(
                    source_row_no=rec.source_row_no or 0,
                    business_date=rec.business_date, branch_code=rec.branch_code,
                    account_no=rec.account_no, side=rec.side,
                    product_code=rec.product_code, balance=rec.balance,
                    int_payable=rec.raw_int_payable,
                    int_receivable=rec.raw_int_receivable, roi=rec.raw_roi,
                )
                res = calculate(raw, side, rates)
                b = branches[rec.branch_code]
                p = products[rec.product_code]

                facts.append(FtpCalculationResult(
                    run_id=run.id, batch_id=batch.id, business_date=on,
                    branch_id=b.id, branch_code=b.branch_code,
                    division_id=b.division_id, district_id=b.district_id,
                    branch_category=b.category,
                    account_no=rec.account_no, product_id=p.id,
                    product_code=p.product_code, side=side,
                    liability_nature=p.liability_nature,
                    balance=rec.balance,
                    raw_roi=rec.raw_roi, raw_int_payable=rec.raw_int_payable,
                    raw_int_receivable=rec.raw_int_receivable,
                    normalized_roi=res.normalized.roi,
                    roi_source=res.normalized.roi_source,
                    customer_interest=res.normalized.customer_interest,
                    interest_source=res.normalized.interest_source,
                    interest_expected=res.normalized.interest_expected,
                    interest_variance=res.normalized.interest_variance,
                    interest_mismatch=res.normalized.interest_mismatch,
                    benchmark_rate=rates.benchmark.value,
                    benchmark_source=rates.benchmark.source,
                    liquidity_cost=rates.liquidity.value,
                    liquidity_source=rates.liquidity.source,
                    other_cost=rates.other.value,
                    other_source=rates.other.source,
                    global_config_version=book.global_rates.version,
                    product_config_version=(
                        book.overrides[p.product_code].version
                        if p.product_code in book.overrides else None
                    ),
                    ftp_rate=res.ftp_rate, ftp_income=res.ftp_income,
                    asset_ftp_profit=res.asset_ftp_profit,
                    liability_ftp_profit=res.liability_ftp_profit,
                    negative_ftp_flag=res.negative_ftp_flag,
                ))

        self.s.bulk_save_objects(facts)
        run.rows_in = rows_in
        run.rows_out = len(facts)
        run.status = "COMPLETED"
        run.finished_at = datetime.now(UTC)
        batch.calculation_run_id = run.id
        self.s.flush()

        audit.record(
            self.s, action="CALC_RUN", entity_type="calculation_run",
            entity_id=run.run_ref,
            after={"rows_in": rows_in, "rows_out": len(facts),
                   "dates": [d.isoformat() for d in dates]},
            actor_user_id=self.actor_id, actor_username=self.actor_username,
        )
        return run

    # ------------------------------------------------------------------ #
    # 7. AGGREGATE
    # ------------------------------------------------------------------ #

    def refresh_aggregates(self, run: CalculationRun, dates: list[date]) -> None:
        """Rebuild every grain for the affected dates only.

        Only additive components are stored: weighted averages are kept as
        SUM(rate x balance) alongside SUM(balance) and divided at read time, so
        aggregates stay correct under any further rollup.
        """
        F = FtpCalculationResult
        common = [
            func.sum(F.balance).filter(F.side == Side.ASSET),
            func.sum(F.balance).filter(F.side == Side.LIABILITY),
            func.sum(F.customer_interest).filter(F.side == Side.ASSET),
            func.sum(F.customer_interest).filter(F.side == Side.LIABILITY),
            func.sum(F.asset_ftp_profit),
            func.sum(F.liability_ftp_profit),
            func.sum(F.ftp_income),
            func.sum(F.normalized_roi * F.balance),
            func.sum(F.ftp_rate * F.balance),
            # Signed to match the side's formula, so the four contributions
            # sum to ftp_rate_x_balance at any rollup.
            func.sum(
                case((F.side == Side.LIABILITY, F.benchmark_rate * F.balance),
                     else_=-F.benchmark_rate * F.balance)
            ),
            func.sum(
                case((F.side == Side.LIABILITY, -F.normalized_roi * F.balance),
                     else_=F.normalized_roi * F.balance)
            ),
            func.sum(-F.liquidity_cost * F.balance),
            func.sum(-F.other_cost * F.balance),
            func.sum(F.balance),
            func.count(),
            func.count().filter(F.negative_ftp_flag.is_(True)),
        ]

        def agg_values(row, offset: int) -> dict:
            v = row[offset:]
            z = Decimal(0)
            return dict(
                run_id=run.id,
                asset_balance=v[0] or z, liability_balance=v[1] or z,
                interest_receivable=v[2] or z, interest_payable=v[3] or z,
                asset_ftp_profit=v[4] or z, liability_ftp_profit=v[5] or z,
                net_ftp_profit=v[6] or z,
                roi_x_balance=v[7] or z, ftp_rate_x_balance=v[8] or z,
                benchmark_contrib=v[9] or z, roi_contrib=v[10] or z,
                liquidity_contrib=v[11] or z, other_contrib=v[12] or z,
                total_balance=v[13] or z,
                account_count=v[14] or 0, negative_ftp_count=v[15] or 0,
            )

        grains = [
            (AggDailyBranch,
             [F.business_date, F.branch_id, F.branch_code, F.division_id,
              F.district_id, F.branch_category],
             lambda r: dict(business_date=r[0], branch_id=r[1], branch_code=r[2],
                            division_id=r[3], district_id=r[4], branch_category=r[5]), 6),
            (AggDailyProduct,
             [F.business_date, F.product_id, F.product_code, F.side],
             lambda r: dict(business_date=r[0], product_id=r[1],
                            product_code=r[2], side=r[3]), 4),
            (AggDailyBranchProduct,
             [F.business_date, F.branch_id, F.product_id, F.branch_code, F.product_code],
             lambda r: dict(business_date=r[0], branch_id=r[1], product_id=r[2],
                            branch_code=r[3], product_code=r[4]), 5),
            (AggDailyDivision, [F.business_date, F.division_id],
             lambda r: dict(business_date=r[0], division_id=r[1]), 2),
            (AggDailyDistrict, [F.business_date, F.district_id, F.division_id],
             lambda r: dict(business_date=r[0], district_id=r[1], division_id=r[2]), 3),
            (AggDailyCategory, [F.business_date, F.branch_category],
             lambda r: dict(business_date=r[0], branch_category=r[1]), 2),
        ]

        for model, keys, key_fn, offset in grains:
            self.s.execute(
                model.__table__.delete().where(model.business_date.in_(dates))
            )
            rows = self.s.execute(
                select(*keys, *common)
                .where(F.business_date.in_(dates))
                .where(F.is_current.is_(True))
                .group_by(*keys)
            ).all()
            if rows:
                self.s.bulk_save_objects(
                    [model(**key_fn(r), **agg_values(r, offset)) for r in rows]
                )
        self.s.flush()

    # ------------------------------------------------------------------ #
    # Full run
    # ------------------------------------------------------------------ #

    def run(self, path: Path, *, business_date: date | None = None,
            sheet_name: str | None = None, auto_commit: bool = True,
            mapping: ColumnMapping = LEGACY_WORKBOOK_MAPPING) -> StageResult:
        """Execute every stage. Returns a summary suitable for the UI."""
        batch = self.receive(path, business_date=business_date, sheet_name=sheet_name)
        try:
            rows, findings, stats = self.parse_and_validate(
                batch, mapping=mapping, business_date=business_date,
                sheet_name=sheet_name,
            )
            result = self.preview(batch, findings, stats)

            if not auto_commit:
                batch.status = "AWAITING_REVIEW"
                self.s.flush()
                return result

            dates = self.commit_batch(batch, rows, findings)
            run = self.calculate_dates(batch, dates)
            self.refresh_aggregates(run, dates)

            batch.status = "COMPLETED"
            batch.completed_at = datetime.now(UTC)
            self.s.flush()

            result.status = "COMPLETED"
            result.business_dates = dates
            result.run_ref = run.run_ref
            return result

        except Exception as exc:
            batch.status = "FAILED"
            batch.status_message = str(exc)[:2000]
            self.s.flush()
            raise
