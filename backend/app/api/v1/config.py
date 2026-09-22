"""Global rate configuration (HO admin).

This is the screen the legacy workbook never had. In `FTP1.xlsm` the liquidity
cost (0.30) and other cost (0.05) were hand-typed onto every one of ~2,880 rate
cells, which is why a single mistyped cell could price a product differently
from its neighbours with nothing to show it had happened. Here they are one
effective-dated row, edited in one place, with the change recorded.

Edits are direct: `CONFIG_RATE_EDIT` at HO scope, no separate approval step.
The controls that replace maker-checker are the version history and the audit
trail, both readable from these routes.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbDep, UserDep, require
from app.domain.types import DayCountBasis, ScopeLevel
from app.models import GlobalRateConfig
from app.services.config import (
    ConfigError, ConfigInUse, GlobalConfigService,
)

router = APIRouter(prefix="/config", tags=["config"])

_view = Depends(require("CONFIG_RATE_VIEW"))
_edit = Depends(require("CONFIG_RATE_EDIT"))


def _ho_only(user: CurrentUser) -> None:
    """The global layer prices every branch, so only HO may change it.

    A division administrator holding CONFIG_RATE_EDIT can maintain rates within
    their own scope; letting them move the global default would let them reprice
    branches they cannot even see.
    """
    if user.scope_level is not ScopeLevel.HO:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Global rate configuration applies to every branch and can only be "
            "changed by a head-office administrator.",
        )


class GlobalConfigOut(BaseModel):
    version: int
    benchmark_rate: Decimal | None
    liquidity_cost: Decimal | None
    other_cost: Decimal | None
    day_count_basis: DayCountBasis
    effective_from: date
    effective_to: date | None
    note: str | None
    #: Completed runs and rows this version priced. Non-zero runs means an
    #: in-place correction is refused, which is how the UI decides which of the
    #: two edits to offer.
    runs_priced: int
    rows_priced: int
    editable_in_place: bool


def _out(svc: GlobalConfigService, cfg: GlobalRateConfig) -> GlobalConfigOut:
    runs, rows = svc.priced_by(cfg.version)
    return GlobalConfigOut(
        version=cfg.version,
        benchmark_rate=cfg.benchmark_rate,
        liquidity_cost=cfg.liquidity_cost,
        other_cost=cfg.other_cost,
        day_count_basis=cfg.day_count_basis,
        effective_from=cfg.effective_from,
        effective_to=cfg.effective_to,
        note=cfg.note,
        runs_priced=runs,
        rows_priced=rows,
        editable_in_place=runs == 0 and cfg.effective_to is None,
    )


class GlobalConfigUpdate(BaseModel):
    """Only the fields supplied are changed; the rest carry forward.

    `benchmark_rate` is nullable on purpose: NULL means the global layer offers
    no benchmark, so every product must carry its own. That is the seeded
    posture and it is what turns a missing benchmark into a hard error instead
    of a silent zero.
    """

    benchmark_rate: Decimal | None = None
    liquidity_cost: Decimal | None = Field(default=None, ge=0)
    other_cost: Decimal | None = Field(default=None, ge=0)
    day_count_basis: DayCountBasis | None = None
    effective_from: date | None = None
    note: str | None = None


def _svc(db, user: CurrentUser) -> GlobalConfigService:
    return GlobalConfigService(db, actor_id=user.id, actor_username=user.username)


def _changes(body: GlobalConfigUpdate) -> dict:
    """Supplied fields only, so an omitted component carries forward."""
    return body.model_dump(exclude_unset=True,
                           exclude={"effective_from", "note"})


@router.get("/global", response_model=GlobalConfigOut, dependencies=[_view])
def current_global(db: DbDep, user: UserDep, on: date | None = None):
    """The global defaults in force on a date (default today)."""
    svc = _svc(db, user)
    cfg = svc.in_force(on)
    if cfg is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No approved global rate configuration is in force on "
            f"{(on or date.today()).isoformat()}.",
        )
    return _out(svc, cfg)


@router.get("/global/history", response_model=list[GlobalConfigOut],
            dependencies=[_view])
def global_history(db: DbDep, user: UserDep, limit: int = 100):
    """Every version, newest first -- the record of what priced when."""
    svc = _svc(db, user)
    return [_out(svc, cfg) for cfg in svc.history(limit)]


@router.put("/global", response_model=GlobalConfigOut, dependencies=[_edit])
def new_global_version(body: GlobalConfigUpdate, db: DbDep, user: UserDep):
    """Change the defaults from a date, keeping the previous version intact."""
    _ho_only(user)
    svc = _svc(db, user)
    try:
        cfg = svc.set_rates(
            effective_from=body.effective_from, note=body.note, **_changes(body),
        )
    except ConfigError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _out(svc, cfg)


@router.patch("/global", response_model=GlobalConfigOut, dependencies=[_edit])
def correct_global(body: GlobalConfigUpdate, db: DbDep, user: UserDep):
    """Fix the current version in place. Refused once it has priced anything."""
    _ho_only(user)
    svc = _svc(db, user)
    try:
        cfg = svc.correct(note=body.note,
                          effective_from=body.effective_from, **_changes(body))
    except ConfigInUse as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"message": str(exc), "version": exc.version,
             "runs": exc.runs, "rows": exc.rows,
             "alternative": "PUT /config/global with an effective_from date"},
        ) from exc
    except ConfigError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _out(svc, cfg)
