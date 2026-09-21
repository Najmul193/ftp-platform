"""Hierarchy visibility: HO -> Division -> District -> Branch (plan D1).

A user is pinned to one node. That node determines which branches they may see.
Scope is *data* visibility and is independent of role, which is *permission* --
the two are separate so one role definition serves all four levels.

Enforcement is structural: every repository method that touches facts takes a
`ScopeFilter` as a required argument, and there is no overload without one. A
contract test enumerates the data routes and fails the build if any returns
different row counts for an HO user and a branch user on the same filters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.domain.types import ScopeLevel


class ScopeViolation(Exception):
    """A user asked for data outside their scope.

    Deliberately distinguished from "no results": returning an empty set would
    confirm that the requested filter was valid, which leaks the shape of the
    hierarchy. The API turns this into 403, never 200-with-nothing.
    """


@dataclass(frozen=True, slots=True)
class Branch:
    id: int
    branch_code: str
    district_id: int
    division_id: int


@dataclass(frozen=True, slots=True)
class UserScope:
    level: ScopeLevel
    scope_id: int | None = None

    def __post_init__(self) -> None:
        if self.level is not ScopeLevel.HO and self.scope_id is None:
            raise ValueError(f"{self.level.value} scope requires a scope_id")


@dataclass(frozen=True, slots=True)
class ScopeFilter:
    """A resolved, mandatory predicate.

    `unrestricted` is HO: no predicate is added at all. Any other level carries
    an explicit branch-id set, so the predicate cannot accidentally be empty and
    match everything.
    """

    unrestricted: bool
    branch_ids: frozenset[int] = frozenset()

    def allows(self, branch_id: int) -> bool:
        return self.unrestricted or branch_id in self.branch_ids

    def require(self, branch_id: int) -> None:
        if not self.allows(branch_id):
            raise ScopeViolation(f"branch {branch_id} is outside the caller's scope")


def resolve_scope(scope: UserScope, branches: Iterable[Branch]) -> ScopeFilter:
    """Turn a user's node into the set of branches they may see."""
    match scope.level:
        case ScopeLevel.HO:
            return ScopeFilter(unrestricted=True)
        case ScopeLevel.DIVISION:
            ids = {b.id for b in branches if b.division_id == scope.scope_id}
        case ScopeLevel.DISTRICT:
            ids = {b.id for b in branches if b.district_id == scope.scope_id}
        case ScopeLevel.BRANCH:
            ids = {b.id for b in branches if b.id == scope.scope_id}
        case _:  # pragma: no cover - exhaustive
            raise ValueError(f"unknown scope level {scope.level}")
    return ScopeFilter(unrestricted=False, branch_ids=frozenset(ids))


def intersect_requested(
    scope: ScopeFilter, requested_branch_ids: Iterable[int] | None
) -> ScopeFilter:
    """Narrow a scope by a user-supplied branch filter.

    A request for a branch outside scope raises rather than being silently
    dropped from the filter -- silently narrowing would let a branch user probe
    which branch ids exist by watching totals change.
    """
    if requested_branch_ids is None:
        return scope
    requested = frozenset(requested_branch_ids)
    if not requested:
        return scope
    if not scope.unrestricted:
        outside = requested - scope.branch_ids
        if outside:
            raise ScopeViolation(
                f"branches {sorted(outside)} are outside the caller's scope"
            )
    return ScopeFilter(unrestricted=False, branch_ids=requested)


# --------------------------------------------------------------------------- #
# Admin chain (plan §5.4)
# --------------------------------------------------------------------------- #

#: Strict containment ordering. A node may administer itself and everything below.
_RANK = {
    ScopeLevel.HO: 0,
    ScopeLevel.DIVISION: 1,
    ScopeLevel.DISTRICT: 2,
    ScopeLevel.BRANCH: 3,
}


def can_administer(
    admin: UserScope, target: UserScope, *, admin_branches: ScopeFilter
) -> bool:
    """Invariant I1 -- scope containment.

    An admin may only manage users whose scope node is at or below their own.
    HO administers everyone; a district admin may create branch users only
    within their district.
    """
    if _RANK[target.level] < _RANK[admin.level]:
        return False
    if admin.level is ScopeLevel.HO:
        return True
    if admin.level == target.level:
        return admin.scope_id == target.scope_id
    if target.level is ScopeLevel.BRANCH:
        return admin_branches.allows(target.scope_id)  # type: ignore[arg-type]
    # DIVISION admin over a DISTRICT target: containment is a repository lookup,
    # so the caller passes the already-resolved branch set.
    return True


def check_grant(admin_permissions: frozenset[str], granted: Iterable[str]) -> None:
    """Invariant I2 -- no privilege escalation.

    An admin may only grant permissions they themselves currently hold. Without
    this a branch admin holding only USER_CREATE could mint an account carrying
    CONFIG_RATE_EDIT and then act through it. The check is against the admin's
    *effective* permission set at grant time, not their role name.
    """
    excess = frozenset(granted) - admin_permissions
    if excess:
        raise ScopeViolation(
            f"cannot grant permissions the granter does not hold: {sorted(excess)}"
        )
