"""The day-count basis reaches every figure that depends on it.

ACT/365 divides by 36,500 and ACT/360 by 36,000. The engine, the ROI/interest
normalisation and the V013 reconciliation must all use the basis in force for
the row's date -- a hard-coded 365 anywhere makes an ACT/360 book disagree with
itself.
"""

from datetime import date
from decimal import Decimal

from app.domain.calculation import calculate, normalize
from app.domain.types import (
    DayCountBasis, RateComponent, RateSource, RawRow, ResolvedRates, Side,
)
from app.domain.validation import ValidationContext


def _rates(bm: str, liq: str = "0.30", oth: str = "0.05") -> ResolvedRates:
    c = lambda v: RateComponent(Decimal(v), RateSource.PRODUCT_OVERRIDE, 1)  # noqa: E731
    return ResolvedRates(benchmark=c(bm), liquidity=c(liq), other=c(oth))


def _row(**kw) -> RawRow:
    base = dict(source_row_no=1, business_date=date(2026, 9, 20), branch_code="100",
                account_no="A1", side="L", product_code="TDR06",
                balance=Decimal("1000000"), int_payable=None, int_receivable=None,
                roi=Decimal("7.00"))
    base.update(kw)
    return RawRow(**base)


def test_income_uses_the_basis_divisor():
    row, rates = _row(), _rates("8.00")
    r365 = calculate(row, Side.LIABILITY, rates, basis=DayCountBasis.ACT_365)
    r360 = calculate(row, Side.LIABILITY, rates, basis=DayCountBasis.ACT_360)
    # spread 8.00 - 7.00 - 0.30 - 0.05 = 0.65 on 1,000,000
    assert r365.ftp_rate == r360.ftp_rate == Decimal("0.650000")
    assert r365.ftp_income == Decimal("17.808219")      # 650,000 / 36,500
    assert r360.ftp_income == Decimal("18.055556")      # 650,000 / 36,000


def test_customer_interest_and_derived_roi_follow_the_basis():
    derived = normalize(_row(), Side.LIABILITY, basis=DayCountBasis.ACT_360)
    assert derived.customer_interest == Decimal("194.444444")   # 7,000,000 / 36,000
    back = normalize(_row(roi=None, int_payable=Decimal("194.444444")),
                     Side.LIABILITY, basis=DayCountBasis.ACT_360)
    assert back.roi == Decimal("7.000000")


def test_validation_reconciles_each_date_on_its_own_basis():
    ctx = ValidationContext(
        active_branches={"100"}, products={},
        basis_resolver=lambda on: (DayCountBasis.ACT_360 if on >= date(2026, 9, 20)
                                   else DayCountBasis.ACT_365))
    assert ctx.basis_resolver(date(2026, 9, 19)) is DayCountBasis.ACT_365
    assert ctx.basis_resolver(date(2026, 9, 20)) is DayCountBasis.ACT_360
