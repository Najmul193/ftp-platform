"""ROI <-> interest, and the sign convention, as properties rather than examples.

Why properties here
-------------------
The parity suite (`tests/parity`) proves the engine against `FTP1.xlsm`, which is
a genuine external oracle: Excel computed those cells with the bank's own
formulas. But that oracle is narrow. Measured over its 960 rows it contains:

    both ROI and interest supplied   810 rows
    ROI zero, no interest            150 rows
    ROI supplied alone                 0 rows
    interest supplied alone            0 rows
    negative FTP spread                0 rows

So the "interest supplied, ROI derived" direction and every negative spread have
no external oracle at all. Asserting them against hand-computed literals would
only restate the formula the engine already implements, and would pass just as
happily if the formula itself were wrong.

These tests instead assert properties that hold regardless of the formula:

* the two ROI/interest directions must be inverses of each other;
* the spread must respond to ROI with the opposite sign on each side of the
  balance sheet, and to the benchmark with the opposite sign again;
* income must be linear in balance.

A divisor error, a transposed subtraction or a side-swapped sign convention
breaks at least one of these. Together with parity on the positive both-supplied
case, that is real coverage of the part the workbook cannot speak to.
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.domain.calculation import ftp_income, ftp_rate, normalize
from app.domain.types import (
    DayCountBasis, RateComponent, RateSource, RawRow, ResolvedRates, Side,
)

DIVISOR = DayCountBasis.ACT_365.divisor          # 36500


def _rates(benchmark="8.00", liquidity="0.30", other="0.05") -> ResolvedRates:
    mk = lambda v: RateComponent(  # noqa: E731
        value=Decimal(v), source=RateSource.GLOBAL_DEFAULT, config_version=1)
    return ResolvedRates(benchmark=mk(benchmark), liquidity=mk(liquidity),
                         other=mk(other))


def _row(balance, *, roi=None, int_payable=None, int_receivable=None) -> RawRow:
    return RawRow(
        source_row_no=1, business_date=None, branch_code="1",
        account_no="1000000001", side=None, product_code="X",
        balance=balance, int_payable=int_payable,
        int_receivable=int_receivable, roi=roi,
    )


# Balances from a thousand to a hundred million, the range a branch actually
# holds. Below that the round trip loses precision for a structural reason the
# last test pins down explicitly.
balances = st.decimals(min_value=Decimal("1000"), max_value=Decimal("100000000"),
                       places=2, allow_nan=False, allow_infinity=False)
rois = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("25"),
                   places=6, allow_nan=False, allow_infinity=False)
sides = st.sampled_from([Side.ASSET, Side.LIABILITY])


@given(balance=balances, roi=rois, side=sides)
@settings(max_examples=300, deadline=None)
def test_roi_to_interest_and_back_is_identity(balance, roi, side):
    """ROI -> interest -> ROI returns the ROI, within the rounding contract.

    This is what makes the derived-ROI path trustworthy without an oracle: it
    cannot agree with the forward path by coincidence. A wrong divisor in either
    direction shows up immediately, because the two would no longer cancel.
    """
    forward = normalize(_row(balance, roi=roi), side)
    assert forward.roi == roi

    interest = forward.customer_interest
    back = normalize(
        _row(balance,
             int_payable=interest if side is Side.LIABILITY else None,
             int_receivable=interest if side is Side.ASSET else None),
        side,
    )

    # Interest is stored to 6 dp, so it carries at most half a unit in the last
    # place. Inverting multiplies that error by divisor/balance. The bound is
    # derived from the rounding contract, not tuned to make the test pass.
    tolerance = (Decimal("0.0000005") * DIVISOR / balance) + Decimal("0.000001")
    assert abs(back.roi - roi) <= tolerance


@given(balance=balances, interest=st.decimals(
    min_value=Decimal("0.01"), max_value=Decimal("1000000"), places=6,
    allow_nan=False, allow_infinity=False), side=sides)
@settings(max_examples=300, deadline=None)
def test_interest_to_roi_and_back_is_identity(balance, interest, side):
    """The same inverse, entered from the other direction."""
    back = normalize(
        _row(balance,
             int_payable=interest if side is Side.LIABILITY else None,
             int_receivable=interest if side is Side.ASSET else None),
        side,
    )
    assume(Decimal("0") < back.roi <= Decimal("100"))
    forward = normalize(_row(balance, roi=back.roi), side)

    tolerance = (Decimal("0.0000005") * balance / DIVISOR) + Decimal("0.000001")
    assert abs(forward.customer_interest - interest) <= tolerance


@given(roi=rois, delta=st.decimals(min_value=Decimal("0.01"),
                                   max_value=Decimal("5"), places=6))
@settings(max_examples=200, deadline=None)
def test_spread_responds_to_roi_with_opposite_sign_per_side(roi, delta):
    """Paying the customer more narrows a liability spread and widens an asset's.

    This is the sign convention itself, asserted without writing the formula
    down. If the two branches were swapped, both sides would move together and
    this fails -- which the workbook cannot catch, because every one of its rows
    is a positive spread.
    """
    rates = _rates()
    higher = roi + delta

    liab_before = ftp_rate(Side.LIABILITY, roi, rates)
    liab_after = ftp_rate(Side.LIABILITY, higher, rates)
    asset_before = ftp_rate(Side.ASSET, roi, rates)
    asset_after = ftp_rate(Side.ASSET, higher, rates)

    assert liab_after < liab_before, "a liability spread must narrow as ROI rises"
    assert asset_after > asset_before, "an asset spread must widen as ROI rises"

    # And the movement is the same size on both sides, opposite in sign.
    assert (liab_before - liab_after) == (asset_after - asset_before) == delta


@given(roi=rois, delta=st.decimals(min_value=Decimal("0.01"),
                                   max_value=Decimal("5"), places=6))
@settings(max_examples=200, deadline=None)
def test_spread_responds_to_benchmark_with_the_opposite_sign_again(roi, delta):
    """A higher benchmark widens a liability spread and narrows an asset's."""
    low = _rates(benchmark="8.00")
    high = _rates(benchmark=str(Decimal("8.00") + delta))

    assert ftp_rate(Side.LIABILITY, roi, high) > ftp_rate(Side.LIABILITY, roi, low)
    assert ftp_rate(Side.ASSET, roi, high) < ftp_rate(Side.ASSET, roi, low)


@given(roi=rois, side=sides,
       liquidity=st.decimals(min_value=Decimal("0"), max_value=Decimal("2"),
                             places=6),
       other=st.decimals(min_value=Decimal("0"), max_value=Decimal("2"),
                         places=6),
       extra=st.decimals(min_value=Decimal("0.01"), max_value=Decimal("2"),
                         places=6))
@settings(max_examples=200, deadline=None)
def test_costs_always_reduce_the_spread_on_both_sides(roi, side, liquidity,
                                                      other, extra):
    """Liquidity and other cost are a load, never a benefit, whichever side."""
    base = ftp_rate(side, roi, _rates(liquidity=str(liquidity), other=str(other)))
    loaded = ftp_rate(side, roi, _rates(liquidity=str(liquidity + extra),
                                        other=str(other)))
    assert loaded < base
    loaded_other = ftp_rate(side, roi,
                            _rates(liquidity=str(liquidity),
                                   other=str(other + extra)))
    assert loaded_other < base


@given(balance=balances, rate=st.decimals(min_value=Decimal("-5"),
                                          max_value=Decimal("5"), places=6),
       factor=st.integers(min_value=2, max_value=50))
@settings(max_examples=200, deadline=None)
def test_income_is_linear_in_balance(balance, rate, factor):
    """Doubling the balance doubles the income, sign included."""
    one = ftp_income(balance, rate)
    many = ftp_income(balance * factor, rate)
    # Both sides are quantised, so allow the last place per multiplied unit.
    assert abs(many - one * factor) <= Decimal("0.000001") * factor


def test_round_trip_precision_degrades_only_on_tiny_balances():
    """The one place the inverse is genuinely lossy, stated rather than hidden.

    At a balance of 1 unit, a 6 dp interest figure can only pin ROI to about
    0.018 -- so deriving ROI from interest on a near-empty account is imprecise
    by construction. Worth knowing, and worth not discovering in production.
    """
    roi = Decimal("6.000000")
    worst = {}
    for balance in (Decimal("1"), Decimal("10"), Decimal("100"),
                    Decimal("1000"), Decimal("100000")):
        fwd = normalize(_row(balance, roi=roi), Side.LIABILITY)
        back = normalize(_row(balance, int_payable=fwd.customer_interest),
                         Side.LIABILITY)
        worst[balance] = abs(back.roi - roi)

    assert worst[Decimal("1")] > worst[Decimal("100000")]
    assert worst[Decimal("100000")] <= Decimal("0.000001")
    # The error shrinks with balance, as divisor/balance predicts.
    assert worst[Decimal("1")] <= Decimal("0.02")
