"""Validation rules V001-V019 (plan §8.3).

Severity decides what happens to the row:

* ``REJECT`` -- the row does not enter the fact table, and is reported with its
  source row number so the user can open the file at exactly that line.
* ``WARN``   -- the row is admitted and flagged.
* ``INFO``   -- advisory only.

The governing principle is that **no row is ever dropped silently**. The legacy
macro skipped rows whose Type was not A or L with no count and no message
(defect L3); here every rejection is a counted, explained record.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Callable, Iterable

from app.domain.errors import ConfigMissingError, ValidationError
from app.domain.types import (
    DayCountBasis,
    RawRow,
    ResolvedRates,
    Severity,
    Side,
    Tolerance,
)

#: Branch(3) + side(2) + product(1) + serial(4), as observed in the workbook.
#: Advisory only: the bank may change the scheme, so it must never reject.
ACCOUNT_PATTERN = re.compile(r"^\d{10}$")


@dataclass(frozen=True, slots=True)
class ProductInfo:
    code: str
    side: Side
    active: bool = True


@dataclass(frozen=True, slots=True)
class Exception_:
    """One rule firing on one row."""

    source_row_no: int
    severity: Severity
    rule_code: str
    message: str
    field: str | None = None
    raw_value: str | None = None
    origin: str | None = None

    @property
    def blocking(self) -> bool:
        return self.severity is Severity.REJECT


@dataclass(slots=True)
class ValidationContext:
    """Everything the rules need, passed in rather than fetched.

    Keeping this a plain value object is what lets the whole rule set be tested
    without a database.
    """

    active_branches: set[str]
    products: dict[str, ProductInfo]
    rate_resolver: Callable[[str, date], ResolvedRates] | None = None
    basis: DayCountBasis = DayCountBasis.ACT_365
    tolerance: Tolerance = field(default_factory=Tolerance)
    roi_min: Decimal = Decimal("0")
    roi_max: Decimal = Decimal("25")
    balance_change_pct: Decimal = Decimal("50")
    prior_day_accounts: set[str] = field(default_factory=set)
    prior_day_balances: dict[str, Decimal] = field(default_factory=dict)
    prior_day_branch_counts: dict[str, int] = field(default_factory=dict)
    branch_count_tolerance_pct: Decimal = Decimal("10")
    mapped_columns: set[str] = field(default_factory=set)


def _key(row: RawRow) -> tuple[str, str, str]:
    return (
        row.business_date.isoformat() if row.business_date else "",
        row.branch_code or "",
        row.account_no or "",
    )


def validate_row(
    row: RawRow, ctx: ValidationContext, seen: set[tuple[str, str, str]]
) -> list[Exception_]:
    """Apply every row-level rule. Returns all findings, not just the first.

    Reporting every problem on a row at once matters: a user fixing a file
    should see all of it in one pass rather than rediscovering the next issue on
    each re-upload.
    """
    out: list[Exception_] = []
    origin = row.extras.get("_origin")

    def add(code: str, sev: Severity, msg: str, fld: str | None = None, raw: object = None):
        out.append(
            Exception_(row.source_row_no, sev, code, msg, fld,
                       None if raw is None else str(raw), origin)
        )

    # --- coercion failures recorded by the adapter ------------------------ #
    for err in row.extras.get("_coercion_errors", []):
        code, _, msg = str(err).partition(":")
        add(code or "V007", Severity.REJECT, msg or str(err))

    # --- V001 required fields --------------------------------------------- #
    for fld, val in (
        ("business_date", row.business_date),
        ("branch_code", row.branch_code),
        ("account_no", row.account_no),
        ("side", row.side),
        ("product_code", row.product_code),
        ("balance", row.balance),
    ):
        if val is None or (isinstance(val, str) and not val.strip()):
            add("V001", Severity.REJECT, f"{fld} is required", fld)

    # --- V002 side domain -------------------------------------------------- #
    side: Side | None = None
    if row.side is not None:
        try:
            side = Side.from_code(row.side)
        except ValueError:
            add("V002", Severity.REJECT,
                f"side must be 'A' or 'L', got {row.side!r}", "side", row.side)

    # --- V003 branch ------------------------------------------------------- #
    if row.branch_code and row.branch_code not in ctx.active_branches:
        add("V003", Severity.REJECT,
            f"branch {row.branch_code!r} is unknown or inactive",
            "branch_code", row.branch_code)

    # --- V004 / V005 product ---------------------------------------------- #
    product = ctx.products.get(row.product_code) if row.product_code else None
    if row.product_code and product is None:
        add("V004", Severity.REJECT,
            f"product {row.product_code!r} is not in the product master",
            "product_code", row.product_code)
    elif product and not product.active:
        add("V004", Severity.REJECT,
            f"product {row.product_code!r} is inactive", "product_code")
    elif product and side and product.side is not side:
        add("V005", Severity.REJECT,
            f"product {row.product_code!r} is {product.side.code} but the row says "
            f"{side.code}", "side")

    # --- V006 rate configuration ------------------------------------------ #
    if product and row.business_date and ctx.rate_resolver is not None:
        try:
            ctx.rate_resolver(row.product_code, row.business_date)  # type: ignore[arg-type]
        except ConfigMissingError as exc:
            add("V006", Severity.REJECT, exc.message, exc.component)

    # --- V007 balance numeric (None here means absent or uncoercible) ------ #
    if row.balance is None and not any(e.rule_code == "V001" for e in out):
        add("V007", Severity.REJECT, "balance is not numeric", "balance")

    # --- V008 / V009 rate-or-interest -------------------------------------- #
    if side is not None:
        supplied = row.int_payable if side is Side.LIABILITY else row.int_receivable
        name = "int_payable" if side is Side.LIABILITY else "int_receivable"
        if row.roi is None and supplied is None:
            add("V008", Severity.REJECT,
                f"side {side.code} requires roi or {name}; neither supplied", "roi")
        elif row.roi is None and row.balance == Decimal("0"):
            add("V009", Severity.REJECT,
                "cannot derive roi from interest when balance is zero", "roi")

    # --- V010 duplicate business key --------------------------------------- #
    key = _key(row)
    if all(key) :
        if key in seen:
            add("V010", Severity.REJECT,
                f"duplicate of date+branch+account {key}", "account_no")
        else:
            seen.add(key)

    # --- V011 negative balance ---------------------------------------------- #
    if row.balance is not None and row.balance < Decimal("0"):
        add("V011", Severity.WARN, f"negative balance {row.balance}", "balance", row.balance)

    # --- V012 ROI band ------------------------------------------------------ #
    if row.roi is not None and not (ctx.roi_min <= row.roi <= ctx.roi_max):
        add("V012", Severity.WARN,
            f"roi {row.roi} outside the expected band "
            f"[{ctx.roi_min}, {ctx.roi_max}]", "roi", row.roi)

    # --- V013 ROI/interest reconciliation ----------------------------------- #
    if side is not None and row.roi is not None and row.balance is not None:
        supplied = row.int_payable if side is Side.LIABILITY else row.int_receivable
        if supplied is not None:
            expected = row.balance * row.roi / ctx.basis.divisor
            variance = supplied - expected
            if abs(variance) > ctx.tolerance.for_balance(row.balance):
                add("V013", Severity.WARN,
                    f"supplied interest {supplied} differs from expected "
                    f"{expected:.6f} by {variance:.6f}", "interest", variance)

    # --- V016 day-on-day balance move --------------------------------------- #
    if row.account_no and row.balance is not None:
        prior = ctx.prior_day_balances.get(row.account_no)
        if prior not in (None, Decimal("0")):
            move = abs(row.balance - prior) / abs(prior) * Decimal("100")
            if move > ctx.balance_change_pct:
                add("V016", Severity.WARN,
                    f"balance moved {move:.1f}% from {prior} "
                    f"(threshold {ctx.balance_change_pct}%)", "balance")

    # --- V018 account number shape (advisory) -------------------------------- #
    if row.account_no and not ACCOUNT_PATTERN.match(row.account_no):
        add("V018", Severity.INFO,
            f"account {row.account_no!r} does not match the expected 10-digit "
            "structure", "account_no", row.account_no)

    return out


def validate_batch(
    rows: Iterable[RawRow], ctx: ValidationContext
) -> tuple[list[Exception_], dict[str, int]]:
    """Row-level rules plus the batch-level ones (V015, V017, V019).

    Returns the findings and a count per severity, so the preview can state
    exactly how many rows will be accepted before anything is committed.
    """
    rows = list(rows)
    seen: set[tuple[str, str, str]] = set()
    findings: list[Exception_] = []

    for row in rows:
        findings.extend(validate_row(row, ctx, seen))

    # --- V015 accounts that vanished since the prior day -------------------- #
    present = {r.account_no for r in rows if r.account_no}
    for missing in sorted(ctx.prior_day_accounts - present):
        findings.append(
            Exception_(0, Severity.WARN, "V015",
                       f"account {missing} was present on the prior day but is "
                       "absent from this file", "account_no", missing)
        )

    # --- V017 branch row counts vs the prior day ---------------------------- #
    counts: dict[str, int] = {}
    for r in rows:
        if r.branch_code:
            counts[r.branch_code] = counts.get(r.branch_code, 0) + 1
    for branch, prior in ctx.prior_day_branch_counts.items():
        now = counts.get(branch, 0)
        if prior:
            delta = abs(now - prior) / prior * Decimal("100")
            if delta > ctx.branch_count_tolerance_pct:
                findings.append(
                    Exception_(0, Severity.WARN, "V017",
                               f"branch {branch} has {now} rows against {prior} "
                               f"on the prior day ({delta:.1f}% change)",
                               "branch_code", branch)
                )

    # --- V019 unmapped columns present in the source ------------------------ #
    extras_seen: set[str] = set()
    for r in rows:
        extras_seen.update(
            k for k in r.extras if not k.startswith("_")
        )
    unmapped = extras_seen - ctx.mapped_columns
    if unmapped:
        findings.append(
            Exception_(0, Severity.INFO, "V019",
                       f"source carries unmapped columns: {sorted(unmapped)}")
        )

    counts_by_sev = {s.value: 0 for s in Severity}
    for f in findings:
        counts_by_sev[f.severity.value] += 1
    return findings, counts_by_sev


def rejected_rows(findings: Iterable[Exception_]) -> set[int]:
    """Source row numbers that must not enter the fact table."""
    return {f.source_row_no for f in findings if f.blocking and f.source_row_no}
