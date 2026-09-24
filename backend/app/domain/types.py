"""Value objects and enumerations for the FTP domain.

Every monetary and rate quantity is `Decimal`. `float` is never used: the
calculation is financial, results are published to management, and binary
floating point cannot represent the decimal rates the bank supplies.

`None` and `Decimal("0")` are rigorously distinct throughout. `None` means the
bank did not supply a value; `0` means the bank supplied zero. Conflating them
is defect L2 of the legacy workbook -- `CANOR` legitimately carries ROI 0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any

# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #


class Side(str, Enum):
    """Which side of the balance sheet an account sits on."""

    ASSET = "ASSET"
    LIABILITY = "LIABILITY"

    @classmethod
    def from_code(cls, raw: str | None) -> "Side":
        """Parse the bank's single-letter code. Raises on anything else."""
        if raw is None:
            raise ValueError("side is required")
        match raw.strip().upper():
            case "A" | "ASSET":
                return cls.ASSET
            case "L" | "LIABILITY":
                return cls.LIABILITY
            case other:
                raise ValueError(f"invalid side {other!r}; expected 'A' or 'L'")

    @property
    def code(self) -> str:
        return "A" if self is Side.ASSET else "L"


class LiabilityNature(str, Enum):
    DEMAND = "DEMAND"
    TIME = "TIME"


class BranchCategory(str, Enum):
    """Fixed set of four (plan decision D2)."""

    METRO = "METRO"
    URBAN = "URBAN"
    SEMI_URBAN = "SEMI_URBAN"
    RURAL = "RURAL"


class ScopeLevel(str, Enum):
    """Where a user sits in HO -> Division -> District -> Branch (D1)."""

    HO = "HO"
    DIVISION = "DIVISION"
    DISTRICT = "DISTRICT"
    BRANCH = "BRANCH"


class RateSource(str, Enum):
    """Which configuration layer supplied a rate component."""

    PRODUCT_OVERRIDE = "PRODUCT_OVERRIDE"
    GLOBAL_DEFAULT = "GLOBAL_DEFAULT"


class ValueSource(str, Enum):
    """Whether a value came from the bank or was derived."""

    BANK_PROVIDED = "BANK_PROVIDED"
    CALCULATED_FROM_ROI = "CALCULATED_FROM_ROI"
    CALCULATED_FROM_INTEREST = "CALCULATED_FROM_INTEREST"


class DayCountBasis(str, Enum):
    """Day-count convention. ACT/365 reproduces the legacy workbook exactly."""

    ACT_365 = "ACT_365"
    ACT_360 = "ACT_360"

    @property
    def days(self) -> int:
        return 365 if self is DayCountBasis.ACT_365 else 360

    @property
    def divisor(self) -> Decimal:
        """Days x 100, because rates are expressed in percent.

        ACT/365 gives 36500 -- the literal in the workbook's formulas.
        """
        return Decimal(self.days * 100)


class Severity(str, Enum):
    REJECT = "REJECT"
    WARN = "WARN"
    INFO = "INFO"


# --------------------------------------------------------------------------- #
# Value objects
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class RawRow:
    """The canonical staging shape every ingestion adapter emits.

    Adapters differ; everything downstream of this type does not. Numeric fields
    are `Decimal | None`, never coerced to zero -- a blank cell parses to `None`.
    """

    source_row_no: int
    business_date: date | None = None
    branch_code: str | None = None
    account_no: str | None = None
    side: str | None = None
    product_code: str | None = None
    balance: Decimal | None = None
    int_payable: Decimal | None = None
    int_receivable: Decimal | None = None
    roi: Decimal | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RateComponent:
    """One resolved rate component, carrying its provenance.

    The config version is stored on every fact row so a historical number can be
    explained without re-deriving it.
    """

    value: Decimal
    source: RateSource
    config_version: int


@dataclass(frozen=True, slots=True)
class ResolvedRates:
    benchmark: RateComponent
    liquidity: RateComponent
    other: RateComponent


@dataclass(frozen=True, slots=True)
class ProductRates:
    """A product's rate overrides. `None` on a component means inherit global."""

    product_code: str
    version: int
    benchmark_rate: Decimal | None = None
    liquidity_cost: Decimal | None = None
    other_cost: Decimal | None = None


@dataclass(frozen=True, slots=True)
class GlobalRates:
    """System-wide rate defaults."""

    version: int
    benchmark_rate: Decimal | None = None
    liquidity_cost: Decimal | None = None
    other_cost: Decimal | None = None
    #: Day-count convention in force; sets the income divisor for the date.
    day_count_basis: DayCountBasis = DayCountBasis.ACT_365


@dataclass(frozen=True, slots=True)
class Normalized:
    """ROI and customer interest after normalisation, with provenance."""

    roi: Decimal
    roi_source: ValueSource
    customer_interest: Decimal
    interest_source: ValueSource
    interest_expected: Decimal | None = None
    interest_variance: Decimal | None = None
    interest_mismatch: bool = False


@dataclass(frozen=True, slots=True)
class CalculationResult:
    """The complete, self-describing outcome for one account-day."""

    side: Side
    balance: Decimal
    normalized: Normalized
    rates: ResolvedRates
    ftp_rate: Decimal
    ftp_income: Decimal
    asset_ftp_profit: Decimal
    liability_ftp_profit: Decimal
    negative_ftp_flag: bool

    @property
    def net_ftp_profit(self) -> Decimal:
        return self.asset_ftp_profit + self.liability_ftp_profit


@dataclass(frozen=True, slots=True)
class Tolerance:
    """Tolerance for reconciling bank-supplied interest against expected.

    Scaled rather than flat: a fixed absolute tolerance false-positives on large
    balances and misses real errors on small ones.

        tolerance = max(absolute_floor, balance * relative_bps / 10000)
    """

    absolute_floor: Decimal = Decimal("0.01")
    relative_bps: Decimal = Decimal("1")

    def for_balance(self, balance: Decimal) -> Decimal:
        relative = abs(balance) * self.relative_bps / Decimal(10000)
        return max(self.absolute_floor, relative)
