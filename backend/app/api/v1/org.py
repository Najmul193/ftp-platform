"""Organisation and branch master routes (HO admin)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import DbDep, ScopeDep, UserDep, require
from app.api.schemas import (
    BranchCreate, BranchOut, BranchUpdate, BranchUsageOut, DistrictOut, DivisionOut,
)
from app.models import Branch, District, Division
from app.services.branches import BranchError, BranchInUse, BranchService

router = APIRouter(tags=["organisation"])

_view = Depends(require("MASTER_BRANCH_VIEW"))
_edit = Depends(require("MASTER_BRANCH_EDIT"))


def _svc(db, user: UserDep) -> BranchService:
    return BranchService(db, actor_id=user.id, actor_username=user.username)


@router.get("/divisions", response_model=list[DivisionOut], dependencies=[_view])
def list_divisions(db: DbDep):
    return list(db.scalars(select(Division).order_by(Division.code)))


@router.get("/districts", response_model=list[DistrictOut], dependencies=[_view])
def list_districts(db: DbDep, division_id: int | None = None):
    stmt = select(District).order_by(District.code)
    if division_id:
        stmt = stmt.where(District.division_id == division_id)
    return list(db.scalars(stmt))


@router.get("/branches", response_model=list[BranchOut], dependencies=[_view])
def list_branches(
    db: DbDep, scope: ScopeDep,
    division_id: int | None = None,
    district_id: int | None = None,
    category: str | None = None,
    include_inactive: bool = Query(False),
):
    """Scope-filtered: a branch user sees only their own branch here too."""
    stmt = select(Branch).order_by(Branch.branch_code)
    if not scope.unrestricted:
        stmt = stmt.where(Branch.id.in_(scope.branch_ids or [-1]))
    if division_id:
        stmt = stmt.where(Branch.division_id == division_id)
    if district_id:
        stmt = stmt.where(Branch.district_id == district_id)
    if category:
        stmt = stmt.where(Branch.category == category)
    if not include_inactive:
        stmt = stmt.where(Branch.is_active.is_(True))
    return list(db.scalars(stmt))


@router.post("/branches", response_model=BranchOut,
             status_code=status.HTTP_201_CREATED, dependencies=[_edit])
def create_branch(body: BranchCreate, db: DbDep, user: UserDep):
    """Add a branch. `division_id` is derived from the district by trigger."""
    try:
        return _svc(db, user).create(
            branch_code=body.branch_code, branch_name=body.branch_name,
            district_code=body.district_code, category=body.category,
            opened_on=body.opened_on, udf=body.udf,
        )
    except BranchError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/branches/{branch_code}", response_model=BranchOut, dependencies=[_view])
def get_branch(branch_code: str, db: DbDep, user: UserDep):
    try:
        return _svc(db, user).get(branch_code)
    except BranchError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.get("/branches/{branch_code}/usage", response_model=BranchUsageOut,
            dependencies=[_view])
def branch_usage(branch_code: str, db: DbDep, user: UserDep):
    """How much history points at this branch, and whether it can be deleted.

    The UI calls this before offering Delete, so the choice between delete and
    deactivate is made with the row counts visible rather than by trial.
    """
    svc = _svc(db, user)
    try:
        branch = svc.get(branch_code)
    except BranchError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    u = svc.usage(branch)
    deletable = u.total == 0
    return BranchUsageOut(
        branch_code=branch_code, fact_rows=u.fact_rows, bank_rows=u.bank_rows,
        aggregate_rows=u.aggregate_rows, deletable=deletable,
        note=("No history references this branch, so it can be deleted outright."
              if deletable else
              "This branch has history. Deleting it would orphan published "
              "figures, so deactivate it instead to retain the audit trail."),
    )


@router.patch("/branches/{branch_code}", response_model=BranchOut, dependencies=[_edit])
def update_branch(branch_code: str, body: BranchUpdate, db: DbDep, user: UserDep):
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no changes supplied")
    try:
        return _svc(db, user).update(branch_code, **changes)
    except BranchError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.delete("/branches/{branch_code}", dependencies=[_edit])
def delete_branch(branch_code: str, db: DbDep, user: UserDep,
                  cascade_unused: bool = Query(False)):
    """Permanently remove a branch that has no history.

    Returns 409 with the referencing row counts when history exists, rather than
    cascading -- a cascade would silently restate every published total that
    included this branch.
    """
    try:
        return _svc(db, user).delete(branch_code, cascade_unused=cascade_unused)
    except BranchInUse as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"message": str(exc), "counts": exc.counts,
             "alternative": f"POST /branches/{branch_code}/deactivate"},
        ) from exc
    except BranchError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.post("/branches/{branch_code}/deactivate", response_model=BranchOut,
             dependencies=[_edit])
def deactivate_branch(branch_code: str, db: DbDep, user: UserDep,
                      reason: str | None = None):
    """Retire a branch, keeping every past figure intact and explainable."""
    try:
        return _svc(db, user).deactivate(branch_code, reason=reason)
    except BranchError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.post("/branches/{branch_code}/reactivate", response_model=BranchOut,
             dependencies=[_edit])
def reactivate_branch(branch_code: str, db: DbDep, user: UserDep):
    try:
        return _svc(db, user).reactivate(branch_code)
    except BranchError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
