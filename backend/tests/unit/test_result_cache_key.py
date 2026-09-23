"""The stored-results key must separate everything that changes a result.

A stored dashboard result is only safe to serve if it cannot answer for a
different caller, filter or data version. These tests pin that down without a
database: the key is a pure function of its inputs.
"""

from datetime import date

from app.domain.scope import ScopeFilter
from app.repositories.cache import _key
from app.repositories.dashboard import Filters

HO = ScopeFilter(unrestricted=True)
BRANCH_7 = ScopeFilter(unrestricted=False, branch_ids=frozenset({7}))
BRANCHES_7_8 = ScopeFilter(unrestricted=False, branch_ids=frozenset({8, 7}))
V1, V2 = "702:2026-09-24", "703:2026-09-24"


def k(method="AnalyticsRepo.repricing_opportunity", scope=HO, version=V1,
      f=None, **kwargs):
    return _key(method, scope, version, (f or Filters(),), kwargs)


def test_identical_requests_share_a_result():
    assert k(limit=25) == k(limit=25)
    assert k(scope=BRANCHES_7_8) == k(scope=ScopeFilter(False, frozenset({7, 8})))


def test_a_branch_user_never_gets_a_head_office_result():
    assert k(scope=BRANCH_7) != k(scope=HO)
    assert k(scope=BRANCH_7) != k(scope=BRANCHES_7_8)


def test_any_data_change_invalidates():
    assert k(version=V1) != k(version=V2)


def test_filters_and_arguments_are_part_of_the_key():
    day = Filters(date_from=date(2026, 9, 23), date_to=date(2026, 9, 23))
    assert k(f=day) != k()
    assert k(f=Filters(division_id=1)) != k(f=Filters(division_id=2))
    assert k(f=Filters(product_codes=["CAIBC"])) != k()
    assert k(limit=25) != k(limit=1)
    assert k(method="AnalyticsRepo.leakage") != k()
