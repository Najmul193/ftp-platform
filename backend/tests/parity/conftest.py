"""Fixtures binding the platform to the legacy workbook.

The rate configuration below is the workbook's own, expressed in the platform's
model: liquidity and other cost were uniform across all five products, so they
are global defaults; only the benchmark varied, so it is a product override.
That is plan decision D3, and reproducing 960 rows with it is the evidence the
decision was right.
"""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

import pytest

from app.domain.types import GlobalRates, ProductRates, Side

WORKBOOK = Path("/Users/rivan/FTP/FTP1.xlsm")
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def workbook_path() -> Path:
    if not WORKBOOK.exists():
        pytest.skip(f"legacy workbook not present at {WORKBOOK}")
    return WORKBOOK


@pytest.fixture(scope="session")
def global_rates() -> GlobalRates:
    """Benchmark is deliberately None: a product without an override must raise
    ConfigMissingError rather than silently price at zero (defect L1)."""
    return GlobalRates(
        version=1,
        benchmark_rate=None,
        liquidity_cost=Decimal("0.30"),
        other_cost=Decimal("0.05"),
    )


@pytest.fixture(scope="session")
def product_rates() -> dict[str, ProductRates]:
    return {
        code: ProductRates(code, 1, benchmark_rate=Decimal(bm))
        for code, bm in [
            ("SBSTU", "5.50"),
            ("FD 1 year", "8.80"),
            ("CANOR", "2.00"),
            ("HMLON 5 y", "9.00"),
            ("CC", "7.60"),
        ]
    }


@pytest.fixture(scope="session")
def product_sides() -> dict[str, Side]:
    return {
        "SBSTU": Side.LIABILITY,
        "FD 1 year": Side.LIABILITY,
        "CANOR": Side.LIABILITY,
        "HMLON 5 y": Side.ASSET,
        "CC": Side.ASSET,
    }


def _load(name: str) -> list[dict[str, str]]:
    with (FIXTURES / name).open() as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="session")
def expected_rows() -> list[dict[str, str]]:
    """The macro's own `Consolidated Data`, 960 account-day rows."""
    return _load("workbook_consolidated.csv")


@pytest.fixture(scope="session")
def expected_branch() -> list[dict[str, str]]:
    return _load("workbook_branch.csv")


@pytest.fixture(scope="session")
def expected_product() -> list[dict[str, str]]:
    return _load("workbook_product.csv")


@pytest.fixture(scope="session")
def expected_daily() -> list[dict[str, str]]:
    return _load("workbook_daily.csv")
