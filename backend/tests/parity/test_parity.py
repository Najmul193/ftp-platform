"""Parity with the legacy workbook (plan §16).

Nothing replaces `FTP1.xlsm` until the platform reproduces it exactly. This
suite reads the real workbook through the production Excel adapter, runs the
production engine, and asserts against the macro's own published output.

On precision
------------
The workbook computes in binary floating point and never rounds. The platform
quantises every stored value to 6 dp, because that is the column type and
because a fact row must be reproducible from its own displayed figures.

So rollups are compared against the workbook's rows *quantised the same way*,
which is an exact, like-for-like assertion. The workbook's own float totals are
checked separately, at a tolerance, and the residual is reported -- that residual
is float accumulation error across 960 additions, and it belongs to the
workbook, not to the platform.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import pytest

from app.domain.calculation import calculate, q_amount
from app.domain.rates import resolve_rates
from app.domain.types import Side
from app.ingestion.adapters.excel import ExcelAdapter
from app.ingestion.base import ExtractStats
from app.ingestion.mapping import LEGACY_WORKBOOK_MAPPING

EXPECTED_ROWS = 960
EXPECTED_DATES = 6
EXPECTED_SUBTOTAL_ROWS = 30          # 5 branches x 6 days
GRAND_TOTAL = Decimal("53215.553151")

#: The workbook's own float rollups drift from the quantised truth by float
#: accumulation error. Anything beyond this is a real defect, not rounding.
FLOAT_DRIFT = Decimal("0.001")


@pytest.fixture(scope="module")
def calculated(workbook_path: Path, global_rates, product_rates, product_sides):
    """Run the real adapter and the real engine over the real workbook."""
    adapter = ExcelAdapter(LEGACY_WORKBOOK_MAPPING)
    stats = ExtractStats()
    out = []

    for row in adapter.extract(workbook_path, stats):
        side = Side.from_code(row.side)
        assert product_sides[row.product_code] is side, (
            f"row {row.extras['_origin']}: product {row.product_code!r} is "
            f"{product_sides[row.product_code].code} but the file says {row.side!r}"
        )
        rates = resolve_rates(
            row.product_code, row.business_date, global_rates,
            product_rates.get(row.product_code),
        )
        out.append((row, calculate(row, side, rates)))

    return out, stats


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #


def test_extracts_every_account_day(calculated):
    rows, stats = calculated
    assert len(rows) == EXPECTED_ROWS


def test_row_accounting_reconciles(calculated):
    """Every physical row is accounted for -- none silently dropped (L3, L4)."""
    _rows, stats = calculated
    assert stats.data_rows == EXPECTED_ROWS
    assert stats.structural_rows == EXPECTED_SUBTOTAL_ROWS
    assert stats.reconciles(), (
        f"{stats.physical_rows} physical != {stats.data_rows} data "
        f"+ {stats.structural_rows} structural + {stats.blank_rows} blank"
    )


def test_all_six_business_dates_present(calculated):
    rows, _ = calculated
    assert len({r.business_date for r, _ in rows}) == EXPECTED_DATES


# --------------------------------------------------------------------------- #
# Row-level parity -- the strong assertion
# --------------------------------------------------------------------------- #


def test_every_row_matches_the_workbook(calculated, expected_rows):
    """All 960 rows: ftp_rate, ftp_income and the side split, exact at 6 dp."""
    expected = {
        (e["business_date"], e["branch_code"], e["account_no"]): e
        for e in expected_rows
    }
    assert len(expected) == EXPECTED_ROWS, "fixture keys are not unique"

    mismatches: list[str] = []
    for row, res in calculated[0]:
        key = (row.business_date.isoformat(), row.branch_code, row.account_no)
        e = expected.get(key)
        if e is None:
            mismatches.append(f"{key}: absent from the workbook")
            continue

        for label, actual, want in (
            ("ftp_rate", res.ftp_rate, q_amount(Decimal(e["ftp_rate"]))),
            ("ftp_income", res.ftp_income, q_amount(Decimal(e["ftp_income"]))),
            ("asset_ftp", res.asset_ftp_profit, q_amount(Decimal(e["asset_ftp_profit"]))),
            ("liab_ftp", res.liability_ftp_profit, q_amount(Decimal(e["liability_ftp_profit"]))),
        ):
            if actual != want:
                mismatches.append(
                    f"{row.extras['_origin']} {key} {label}: got {actual}, want {want}"
                )

    assert not mismatches, "\n".join(mismatches[:25])


def test_rate_provenance_is_as_designed(calculated):
    """Benchmark from the product, liquidity and other from global (D3)."""
    for _row, res in calculated[0]:
        assert res.rates.benchmark.source.value == "PRODUCT_OVERRIDE"
        assert res.rates.liquidity.source.value == "GLOBAL_DEFAULT"
        assert res.rates.other.source.value == "GLOBAL_DEFAULT"


# --------------------------------------------------------------------------- #
# Rollups
# --------------------------------------------------------------------------- #


def _quantised_expected(expected_rows, key, column):
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for e in expected_rows:
        totals[e[key]] += q_amount(Decimal(e[column]))
    return totals


def test_branch_rollup(calculated, expected_rows, expected_branch):
    actual: dict[str, Decimal] = defaultdict(Decimal)
    for row, res in calculated[0]:
        actual[row.branch_code] += res.ftp_income

    assert actual == _quantised_expected(expected_rows, "branch_code", "ftp_income")

    for e in expected_branch:  # and against the macro's own Branch Profit sheet
        assert abs(actual[e["branch_code"]] - Decimal(e["net_ftp_profit"])) < FLOAT_DRIFT


def test_branch_asset_liability_split(calculated, expected_branch):
    asset: dict[str, Decimal] = defaultdict(Decimal)
    liab: dict[str, Decimal] = defaultdict(Decimal)
    for row, res in calculated[0]:
        asset[row.branch_code] += res.asset_ftp_profit
        liab[row.branch_code] += res.liability_ftp_profit

    for e in expected_branch:
        b = e["branch_code"]
        assert abs(asset[b] - Decimal(e["asset_ftp_profit"])) < FLOAT_DRIFT
        assert abs(liab[b] - Decimal(e["liability_ftp_profit"])) < FLOAT_DRIFT


def test_product_rollup(calculated, expected_rows, expected_product):
    actual: dict[str, Decimal] = defaultdict(Decimal)
    for row, res in calculated[0]:
        actual[row.product_code] += res.ftp_income

    assert actual == _quantised_expected(expected_rows, "product_code", "ftp_income")

    for e in expected_product:
        assert abs(actual[e["product_code"]] - Decimal(e["ftp_profit"])) < FLOAT_DRIFT


def test_daily_rollup(calculated, expected_rows, expected_daily):
    actual: dict[str, Decimal] = defaultdict(Decimal)
    for row, res in calculated[0]:
        actual[row.business_date.isoformat()] += res.ftp_income

    assert actual == _quantised_expected(expected_rows, "business_date", "ftp_income")

    for e in expected_daily:
        assert abs(actual[e["business_date"]] - Decimal(e["ftp_profit"])) < FLOAT_DRIFT


def test_grand_total(calculated):
    total = sum((res.ftp_income for _r, res in calculated[0]), Decimal(0))
    assert abs(total - GRAND_TOTAL) < FLOAT_DRIFT, f"got {total}, want {GRAND_TOTAL}"


def test_rollups_are_mutually_consistent(calculated):
    """Branch, product and date totals must each sum to the same number."""
    rows = calculated[0]
    by_branch = sum((r.ftp_income for _x, r in rows), Decimal(0))
    by_side = sum(
        (r.asset_ftp_profit + r.liability_ftp_profit for _x, r in rows), Decimal(0)
    )
    assert by_branch == by_side
