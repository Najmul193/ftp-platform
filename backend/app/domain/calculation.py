"""The FTP calculation engine -- the reference implementation.

Pure functions over `Decimal`. No I/O, no ORM, no globals. This is what the
parity suite runs against the legacy workbook fixtures, and it is the reference
that the fast set-based SQL path is proven equivalent to by the differential
test (plan §15.7).

Business rules, unchanged from the workbook because they are correct:

    LIABILITY   ftp_rate = benchmark - roi - liquidity - other
    ASSET       ftp_rate = roi - benchmark - liquidity - other
    both        ftp_income = balance * ftp_rate / (days * 100)

Rounding contract
-----------------
`ftp_rate` is quantised to 6 dp *before* income is derived from it, so a stored
fact row is internally reproducible: a user can take the row's own displayed
rate and balance and arrive at the row's own income. Deriving income from an
unrounded intermediate would make the row fail its own arithmetic.

ROUND_HALF_UP is ties-away-from-zero, which is what PostgreSQL `numeric` does,
so the Python and SQL paths agree exactly rather than approximately.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.domain.errors import ValidationError
from app.domain.types import (
    CalculationResult,
    DayCountBasis,
    Normalized,
    RawRow,
    ResolvedRates,
    Side,
    Tolerance,
    ValueSource,
)

#: Scale of every stored rate -- matches ``numeric(12,6)``.
RATE_SCALE = Decimal("0.000001")
#: Scale of every stored amount -- matches ``numeric(20,6)``.
AMOUNT_SCALE = Decimal("0.000001")

ZERO = Decimal("0")


def q_rate(value: Decimal) -> Decimal:
    """Quantise to the stored rate scale."""
    return value.quantize(RATE_SCALE, rounding=ROUND_HALF_UP)


def q_amount(value: Decimal) -> Decimal:
    """Quantise to the stored amount scale."""
    return value.quantize(AMOUNT_SCALE, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #


def normalize(
    row: RawRow,
    side: Side,
    *,
    basis: DayCountBasis = DayCountBasis.ACT_365,
    tolerance: Tolerance | None = None,
) -> Normalized:
    """Derive ROI and customer interest, preserving what the bank supplied.

    The bank may send ROI, the relevant interest amount, or both. Exactly one of
    three paths is taken:

    * ROI only      -- interest is derived from it.
    * Interest only -- ROI is derived from it (impossible at zero balance).
    * Both          -- both are kept as supplied and reconciled against each
      other. The bank's value is authoritative; the derived value never
      overwrites it. This closes defect L8, where the workbook silently
      recomputed interest from ROI and lost the discrepancy.

    Raises:
        ValidationError: V008 if neither is supplied; V009 if ROI must be
            derived from interest but the balance is zero.
    """
    tolerance = tolerance or Tolerance()
    divisor = basis.divisor

    if row.balance is None:
        raise ValidationError("V001", "balance is required", field="balance")
    balance = row.balance

    supplied_interest = (
        row.int_payable if side is Side.LIABILITY else row.int_receivable
    )
    interest_field = "int_payable" if side is Side.LIABILITY else "int_receivable"

    # --- neither supplied ------------------------------------------------- #
    if row.roi is None and supplied_interest is None:
        raise ValidationError(
            "V008",
            f"for side {side.code} the bank must supply roi or {interest_field}",
            field="roi",
        )

    # --- ROI supplied, interest derived ----------------------------------- #
    if row.roi is not None and supplied_interest is None:
        roi = q_rate(row.roi)
        return Normalized(
            roi=roi,
            roi_source=ValueSource.BANK_PROVIDED,
            customer_interest=q_amount(balance * roi / divisor),
            interest_source=ValueSource.CALCULATED_FROM_ROI,
        )

    # --- interest supplied, ROI derived ----------------------------------- #
    if row.roi is None and supplied_interest is not None:
        if balance == ZERO:
            raise ValidationError(
                "V009",
                "cannot derive roi from interest when balance is zero",
                field="roi",
            )
        return Normalized(
            roi=q_rate(supplied_interest * divisor / balance),
            roi_source=ValueSource.CALCULATED_FROM_INTEREST,
            customer_interest=q_amount(supplied_interest),
            interest_source=ValueSource.BANK_PROVIDED,
        )

    # --- both supplied, reconcile ----------------------------------------- #
    assert row.roi is not None and supplied_interest is not None
    roi = q_rate(row.roi)
    interest = q_amount(supplied_interest)
    expected = q_amount(balance * roi / divisor)
    variance = q_amount(interest - expected)

    return Normalized(
        roi=roi,
        roi_source=ValueSource.BANK_PROVIDED,
        customer_interest=interest,
        interest_source=ValueSource.BANK_PROVIDED,
        interest_expected=expected,
        interest_variance=variance,
        interest_mismatch=abs(variance) > tolerance.for_balance(balance),
    )


# --------------------------------------------------------------------------- #
# FTP rate and income
# --------------------------------------------------------------------------- #


def ftp_rate(side: Side, roi: Decimal, rates: ResolvedRates) -> Decimal:
    """The FTP spread, in percent.

    A liability earns the difference between what the bank could have paid for
    the funds (benchmark) and what it actually paid the customer (ROI). An asset
    earns the difference between what the customer pays (ROI) and what the funds
    cost internally (benchmark). Both then bear liquidity and other costs.
    """
    benchmark = rates.benchmark.value
    liquidity = rates.liquidity.value
    other = rates.other.value

    if side is Side.LIABILITY:
        raw = benchmark - roi - liquidity - other
    else:
        raw = roi - benchmark - liquidity - other

    return q_rate(raw)


def ftp_income(
    balance: Decimal,
    rate: Decimal,
    *,
    basis: DayCountBasis = DayCountBasis.ACT_365,
) -> Decimal:
    """One day's FTP income: ``balance * rate / (days * 100)``.

    `rate` is expected to be already quantised, so the result is reproducible
    from the stored row.
    """
    return q_amount(balance * rate / basis.divisor)


def calculate(
    row: RawRow,
    side: Side,
    rates: ResolvedRates,
    *,
    basis: DayCountBasis = DayCountBasis.ACT_365,
    tolerance: Tolerance | None = None,
) -> CalculationResult:
    """Run the full pipeline for one account-day.

    Normalise, resolve the spread, derive income, and split it onto the correct
    side of the balance sheet.
    """
    if row.balance is None:
        raise ValidationError("V001", "balance is required", field="balance")

    normalized = normalize(row, side, basis=basis, tolerance=tolerance)
    rate = ftp_rate(side, normalized.roi, rates)
    income = ftp_income(row.balance, rate, basis=basis)

    return CalculationResult(
        side=side,
        balance=row.balance,
        normalized=normalized,
        rates=rates,
        ftp_rate=rate,
        ftp_income=income,
        asset_ftp_profit=income if side is Side.ASSET else ZERO,
        liability_ftp_profit=income if side is Side.LIABILITY else ZERO,
        # The rate is the economic signal. Income sign follows it for a positive
        # balance, but a negative balance would invert it, so the flag tracks
        # the rate rather than the income.
        negative_ftp_flag=rate < ZERO,
    )
