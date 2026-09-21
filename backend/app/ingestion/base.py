"""The adapter boundary (plan §7.1).

Adding a source means implementing this protocol. It does not mean touching
validation, calculation, aggregation or audit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterator, Protocol, runtime_checkable

from app.domain.types import RawRow


@dataclass(slots=True)
class SheetInfo:
    """What the adapter found in one worksheet, and whether it will be read."""

    name: str
    business_date: date | None
    included: bool
    reason: str
    data_rows: int = 0


@dataclass(slots=True)
class ProbeResult:
    """A dry-run inspection, shown to the user before anything is ingested.

    `probe` exists so layout drift is *detected and explained* rather than
    discovered halfway through a load. It never mutates state.
    """

    adapter: str
    sheets: list[SheetInfo] = field(default_factory=list)
    header_issues: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def included_sheets(self) -> list[SheetInfo]:
        return [s for s in self.sheets if s.included]

    @property
    def business_dates(self) -> list[date]:
        return sorted({s.business_date for s in self.included_sheets if s.business_date})

    @property
    def total_data_rows(self) -> int:
        return sum(s.data_rows for s in self.included_sheets)

    @property
    def ok(self) -> bool:
        return not self.errors and bool(self.included_sheets)


@dataclass(slots=True)
class ExtractStats:
    """Counts reconciling every physical row to an outcome.

    Rows are never dropped without being counted. The legacy macro skipped
    subtotal rows and bad-Type rows in silence (defects L3, L4); here every
    physical row lands in exactly one bucket and the buckets must sum.
    """

    physical_rows: int = 0
    data_rows: int = 0
    structural_rows: int = 0   # declared ignore rule, e.g. branch subtotals
    blank_rows: int = 0

    def reconciles(self) -> bool:
        return self.physical_rows == self.data_rows + self.structural_rows + self.blank_rows


@runtime_checkable
class SourceAdapter(Protocol):
    """Emit `RawRow` from some source. The only source-specific code."""

    code: str

    def probe(self, source: Path) -> ProbeResult: ...

    def extract(self, source: Path, stats: ExtractStats | None = None) -> Iterator[RawRow]: ...
