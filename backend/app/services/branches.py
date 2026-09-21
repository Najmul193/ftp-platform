"""Branch master maintenance for the HO administrator (plan §4.2).

Delete semantics
----------------
A branch code is referenced permanently by fact rows, so deleting one that has
data would orphan history and silently change every published total that
included it. The service therefore offers two operations and picks between them
honestly:

* ``delete`` -- a true row delete, allowed **only** when nothing references the
  branch. This is the "I typed it wrong, remove it" case.
* ``deactivate`` -- the branch stops accepting new data and disappears from
  pickers, but its history stays intact and auditable.

`delete` on a branch that has data raises `BranchInUse` naming the row counts,
rather than cascading. Deactivation is offered as the alternative.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.types import BranchCategory
from app.models import (
    AggDailyBranch, BankDailyAccountData, Branch, District, Division,
    FtpCalculationResult,
)
from app.services import audit


class BranchError(Exception):
    """Invalid branch operation."""


class BranchInUse(BranchError):
    """Hard delete refused because history references this branch."""

    def __init__(self, branch_code: str, counts: dict[str, int]) -> None:
        detail = ", ".join(f"{v:,} {k}" for k, v in counts.items() if v)
        super().__init__(
            f"branch {branch_code} cannot be deleted because it is referenced by "
            f"{detail}. Deactivate it instead to retain history."
        )
        self.branch_code = branch_code
        self.counts = counts


@dataclass(frozen=True, slots=True)
class BranchUsage:
    fact_rows: int
    bank_rows: int
    aggregate_rows: int

    @property
    def total(self) -> int:
        return self.fact_rows + self.bank_rows + self.aggregate_rows

    def as_dict(self) -> dict[str, int]:
        return {
            "calculated fact rows": self.fact_rows,
            "raw bank rows": self.bank_rows,
            "aggregate rows": self.aggregate_rows,
        }


def _snapshot(b: Branch) -> dict[str, Any]:
    return {
        "branch_code": b.branch_code,
        "branch_name": b.branch_name,
        "district_id": b.district_id,
        "division_id": b.division_id,
        "category": b.category.value if b.category else None,
        "opened_on": b.opened_on.isoformat() if b.opened_on else None,
        "is_active": b.is_active,
        "udf": b.udf,
    }


class BranchService:
    def __init__(self, session: Session, *, actor_id: int | None = None,
                 actor_username: str | None = None) -> None:
        self.s = session
        self.actor_id = actor_id
        self.actor_username = actor_username

    # ------------------------------------------------------------------ #
    # Read
    # ------------------------------------------------------------------ #

    def get(self, branch_code: str) -> Branch:
        b = self.s.scalar(select(Branch).filter_by(branch_code=branch_code))
        if b is None:
            raise BranchError(f"branch {branch_code!r} does not exist")
        return b

    def usage(self, branch: Branch) -> BranchUsage:
        """How much history points at this branch."""
        return BranchUsage(
            fact_rows=self.s.scalar(
                select(func.count()).select_from(FtpCalculationResult)
                .where(FtpCalculationResult.branch_id == branch.id)
            ) or 0,
            bank_rows=self.s.scalar(
                select(func.count()).select_from(BankDailyAccountData)
                .where(BankDailyAccountData.branch_code == branch.branch_code)
            ) or 0,
            aggregate_rows=self.s.scalar(
                select(func.count()).select_from(AggDailyBranch)
                .where(AggDailyBranch.branch_id == branch.id)
            ) or 0,
        )

    # ------------------------------------------------------------------ #
    # Create
    # ------------------------------------------------------------------ #

    def create(
        self,
        *,
        branch_code: str,
        branch_name: str,
        district_code: str,
        category: BranchCategory | str,
        opened_on: date | None = None,
        udf: dict | None = None,
    ) -> Branch:
        """Add a branch. `division_id` is derived by trigger from the district."""
        branch_code = branch_code.strip()
        if not branch_code:
            raise BranchError("branch_code is required")

        if self.s.scalar(select(Branch).filter_by(branch_code=branch_code)):
            raise BranchError(f"branch {branch_code!r} already exists")

        district = self.s.scalar(select(District).filter_by(code=district_code))
        if district is None:
            raise BranchError(f"district {district_code!r} does not exist")
        if not district.is_active:
            raise BranchError(f"district {district_code!r} is inactive")

        category = BranchCategory(category) if isinstance(category, str) else category

        branch = Branch(
            branch_code=branch_code,
            branch_name=branch_name.strip(),
            district_id=district.id,
            category=category,
            opened_on=opened_on,
            udf=udf or {},
            created_by=self.actor_id,
        )
        self.s.add(branch)
        self.s.flush()
        self.s.refresh(branch)   # pick up the trigger-derived division_id

        audit.record(
            self.s, action="CREATE", entity_type="branch", entity_id=branch_code,
            after=_snapshot(branch),
            actor_user_id=self.actor_id, actor_username=self.actor_username,
        )
        return branch

    # ------------------------------------------------------------------ #
    # Update
    # ------------------------------------------------------------------ #

    def update(self, branch_code: str, **changes: Any) -> Branch:
        """Change a branch's parameters.

        `branch_code` itself is immutable once history exists: it is the natural
        key carried on every fact row, so renaming it would detach that history.
        """
        branch = self.get(branch_code)
        before = _snapshot(branch)

        if "branch_code" in changes and changes["branch_code"] != branch_code:
            if self.usage(branch).total:
                raise BranchError(
                    "branch_code cannot change once the branch has history; "
                    "it is the key every fact row carries"
                )
            branch.branch_code = changes["branch_code"].strip()

        if "branch_name" in changes:
            branch.branch_name = changes["branch_name"].strip()
        if "category" in changes:
            c = changes["category"]
            branch.category = BranchCategory(c) if isinstance(c, str) else c
        if "opened_on" in changes:
            branch.opened_on = changes["opened_on"]
        if "udf" in changes:
            branch.udf = changes["udf"]
        if "is_active" in changes:
            branch.is_active = bool(changes["is_active"])

        if "district_code" in changes:
            district = self.s.scalar(
                select(District).filter_by(code=changes["district_code"])
            )
            if district is None:
                raise BranchError(f"district {changes['district_code']!r} does not exist")
            # Moving a branch re-parents its future data. Historical facts keep
            # the division/district they were calculated under, which is correct:
            # a past month's rollup must not change because of a reorganisation.
            branch.district_id = district.id

        branch.updated_by = self.actor_id
        self.s.flush()
        self.s.refresh(branch)

        audit.record(
            self.s, action="UPDATE", entity_type="branch", entity_id=branch.branch_code,
            before=before, after=_snapshot(branch),
            actor_user_id=self.actor_id, actor_username=self.actor_username,
        )
        return branch

    # ------------------------------------------------------------------ #
    # Delete / deactivate
    # ------------------------------------------------------------------ #

    def delete(self, branch_code: str, *, cascade_unused: bool = False) -> dict:
        """Permanently remove a branch that has no history.

        Raises `BranchInUse` when anything references it. That is deliberate:
        cascading would silently change every published total that included the
        branch, and there is no way to undo it.

        Args:
            cascade_unused: also remove empty aggregate rows, which can linger
                after a superseded batch. Never touches fact or bank rows.
        """
        branch = self.get(branch_code)
        usage = self.usage(branch)

        if cascade_unused and usage.fact_rows == 0 and usage.bank_rows == 0:
            self.s.execute(
                AggDailyBranch.__table__.delete().where(
                    AggDailyBranch.branch_id == branch.id
                )
            )
            usage = self.usage(branch)

        if usage.total:
            raise BranchInUse(branch_code, usage.as_dict())

        before = _snapshot(branch)
        self.s.delete(branch)
        self.s.flush()

        audit.record(
            self.s, action="DELETE", entity_type="branch", entity_id=branch_code,
            before=before,
            actor_user_id=self.actor_id, actor_username=self.actor_username,
        )
        return {"branch_code": branch_code, "deleted": True}

    def deactivate(self, branch_code: str, *, reason: str | None = None) -> Branch:
        """Retire a branch that has history.

        It stops accepting new data (rule V003 rejects it) and drops out of
        pickers, but every past figure remains intact and explainable.
        """
        branch = self.get(branch_code)
        before = _snapshot(branch)
        branch.is_active = False
        branch.updated_by = self.actor_id
        self.s.flush()

        audit.record(
            self.s, action="DEACTIVATE", entity_type="branch", entity_id=branch_code,
            before=before, after={**_snapshot(branch), "reason": reason},
            actor_user_id=self.actor_id, actor_username=self.actor_username,
        )
        return branch

    def reactivate(self, branch_code: str) -> Branch:
        branch = self.get(branch_code)
        before = _snapshot(branch)
        branch.is_active = True
        branch.updated_by = self.actor_id
        self.s.flush()
        audit.record(
            self.s, action="REACTIVATE", entity_type="branch", entity_id=branch_code,
            before=before, after=_snapshot(branch),
            actor_user_id=self.actor_id, actor_username=self.actor_username,
        )
        return branch
