"""Column mapping profiles -- source layouts as configuration, not code.

A mapping is versioned data, stored in the database and audited. The batch
records which mapping version parsed it, so a file can always be re-read exactly
as it was originally read even after the profile changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from app.domain.errors import ValidationError

FieldType = Literal["string", "decimal", "date"]


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """How one canonical field is found in the source."""

    letter: str
    required: bool = False
    type: FieldType = "string"
    transform: str | None = None          # "upper" | "lower" | "strip"
    domain: tuple[str, ...] | None = None
    blank_is_null: bool = True

    @property
    def index(self) -> int:
        """Zero-based column index from a spreadsheet letter ('A' -> 0)."""
        n = 0
        for ch in self.letter.upper():
            n = n * 26 + (ord(ch) - 64)
        return n - 1


@dataclass(frozen=True, slots=True)
class SheetSelector:
    """How to decide which worksheets carry data, and what date each one is.

    `date_in_name` reproduces the workbook's convention ("1 Sep 26") but with a
    *declared* pattern rather than the macro's "anything Excel can read as a
    date". That looseness meant a stray sheet named "5 Jan" would silently
    become input.
    """

    mode: Literal["date_in_name", "explicit", "all"] = "date_in_name"
    patterns: tuple[str, ...] = ("%d %b %y", "%d %b %Y", "%d-%b-%y", "%Y-%m-%d")

    def parse(self, sheet_name: str) -> date | None:
        """Return the business date a sheet name encodes, or None if it is not
        a data sheet."""
        if self.mode != "date_in_name":
            return None
        name = sheet_name.strip()
        for pattern in self.patterns:
            try:
                return datetime.strptime(name, pattern).date()
            except ValueError:
                continue
        return None


@dataclass(frozen=True, slots=True)
class ColumnMapping:
    """A complete, versioned source profile."""

    name: str
    version: int = 1
    header_row: int = 1
    first_data_row: int = 2
    sheet_selector: SheetSelector = field(default_factory=SheetSelector)
    columns: dict[str, ColumnSpec] = field(default_factory=dict)
    #: Canonical fields whose blankness marks a row as structural, not data.
    #: In the legacy workbook the branch subtotal rows are blank in column A --
    #: the macro excluded them only by accident (defect L4). Here it is declared.
    ignore_row_when_blank: tuple[str, ...] = ("branch_code",)
    #: Columns present in the file that are deliberately NOT mapped. In the
    #: workbook these are benchmark/liquidity/other/FTP/income -- now derived
    #: from configuration. Captured into `extras` for reconciliation only.
    capture_as_extras: dict[str, str] = field(default_factory=dict)

    def coerce(self, field_name: str, raw: Any) -> Any:
        """Convert one raw cell to its canonical Python value.

        A blank cell becomes `None`, never `Decimal("0")`. That single rule
        closes defects L1 and L2.
        """
        spec = self.columns[field_name]

        if raw is None:
            return None
        if isinstance(raw, str):
            raw = raw.strip()
            if raw == "" and spec.blank_is_null:
                return None

        if spec.type == "decimal":
            try:
                return Decimal(str(raw))
            except (InvalidOperation, ValueError) as exc:
                raise ValidationError(
                    "V007",
                    f"{field_name}: {raw!r} is not numeric",
                    field=field_name,
                ) from exc

        if spec.type == "date":
            if isinstance(raw, datetime):
                return raw.date()
            if isinstance(raw, date):
                return raw
            raise ValidationError(
                "V001", f"{field_name}: {raw!r} is not a date", field=field_name
            )

        value = str(raw)
        match spec.transform:
            case "upper":
                value = value.upper()
            case "lower":
                value = value.lower()
        value = value.strip()

        if spec.domain and value not in spec.domain:
            raise ValidationError(
                "V002",
                f"{field_name}: {value!r} not in {spec.domain}",
                field=field_name,
            )
        return value


#: The profile matching `FTP1.xlsm`, and the default for the pilot.
#:
#: Columns I-M (benchmark, liquidity, other, FTP, income) are deliberately not
#: mapped as inputs. They are now resolved from governed configuration; the
#: file's own values are captured into `extras` purely so the reconciliation
#: report can show that the platform agrees with the workbook.
LEGACY_WORKBOOK_MAPPING = ColumnMapping(
    name="Legacy FTP Workbook (FTP1.xlsm)",
    version=1,
    header_row=1,
    first_data_row=2,
    sheet_selector=SheetSelector(mode="date_in_name"),
    columns={
        "branch_code": ColumnSpec("A", required=True, transform="strip"),
        "account_no": ColumnSpec("B", required=True, transform="strip"),
        "side": ColumnSpec("C", required=True, transform="upper", domain=("A", "L")),
        "balance": ColumnSpec("D", required=True, type="decimal"),
        "int_payable": ColumnSpec("E", type="decimal"),
        "int_receivable": ColumnSpec("F", type="decimal"),
        "product_code": ColumnSpec("G", required=True, transform="strip"),
        "roi": ColumnSpec("H", type="decimal"),
    },
    ignore_row_when_blank=("branch_code",),
    capture_as_extras={
        "I": "file_benchmark_rate",
        "J": "file_liquidity_cost",
        "K": "file_other_cost",
        "L": "file_ftp_rate",
        "M": "file_ftp_income",
    },
)
