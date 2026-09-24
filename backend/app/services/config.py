"""Global rate configuration maintenance (plan §4.5, D3).

The global layer supplies the default for each of the three rate components.
A product override wins per component; `NULL` on a product component means
inherit from here. That makes this table small and consequential: one row
decides the liquidity and other cost of every product that does not override
them.

Edits are applied directly by an HO administrator -- there is no maker-checker
staging on this path. The `status`/`maker_id`/`checker_id` columns are kept
because the audit trail and the effective-dated history are the control that
replaces it: nothing is overwritten silently, and every change lands in
`audit_log` inside the same transaction.

Two edit paths exist because a rate change and a typo are different events:

`set_rates`  closes the open version and opens version+1 from a date. Figures
             already published keep pointing at the version that priced them.
`correct`    rewrites the current version in place, and is refused once any
             calculated row references it. This is for a value that was wrong
             from the start, where a second version would assert a rate change
             that never happened.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.domain.types import DayCountBasis
from app.models import CalculationRun, GlobalRateConfig, Product
from app.repositories.rates import load_product_overrides
from app.services import audit

#: Distinguishes "leave this component as it is" from "set it to NULL".
KEEP: Final = object()

#: Components the global layer defaults. `benchmark_rate` may legitimately be
#: NULL -- see `GlobalRateConfig` -- but the other two may not: a NULL there
#: turns every product without an override into a ConfigMissingError.
REQUIRED_COMPONENTS: Final = ("liquidity_cost", "other_cost")


class ConfigError(Exception):
    """Invalid configuration operation."""


class ConfigInUse(ConfigError):
    """The version being corrected has already priced published figures."""

    def __init__(self, version: int, runs: int, rows: int) -> None:
        super().__init__(
            f"Version {version} has been used by {runs} completed "
            f"calculation{'' if runs == 1 else 's'} ({rows:,} rows) and cannot "
            f"be corrected in place. Create a new effective-dated version instead."
        )
        self.version = version
        self.runs = runs
        self.rows = rows


def _rate(value: Any, field: str) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ConfigError(f"{field} is not a valid rate: {value!r}.") from exc


#: The scale of the `Rate` column. Snapshots are quantised to it so an audit
#: diff reads `0.300000 -> 0.350000` rather than comparing a value fresh from
#: the form against one already round-tripped through the database.
RATE_SCALE: Final = Decimal("0.000001")


def _shown(value: Decimal | None) -> str | None:
    return None if value is None else str(value.quantize(RATE_SCALE))


def snapshot(cfg: GlobalRateConfig) -> dict[str, Any]:
    """The shape the audit trail stores. Strings, so the JSONB diff is exact."""
    return {
        "version": cfg.version,
        "benchmark_rate": _shown(cfg.benchmark_rate),
        "liquidity_cost": _shown(cfg.liquidity_cost),
        "other_cost": _shown(cfg.other_cost),
        "day_count_basis": cfg.day_count_basis.value if cfg.day_count_basis else None,
        "effective_from": cfg.effective_from.isoformat(),
        "effective_to": cfg.effective_to.isoformat() if cfg.effective_to else None,
        "note": cfg.note,
    }


class GlobalConfigService:
    def __init__(self, session: Session, *, actor_id: int | None = None,
                 actor_username: str | None = None) -> None:
        self.s = session
        self.actor_id = actor_id
        self.actor_username = actor_username

    # --- reads ------------------------------------------------------------ #

    def in_force(self, on: date | None = None) -> GlobalRateConfig | None:
        """The approved version in force on a date, or None."""
        when = on or date.today()
        return self.s.scalar(
            select(GlobalRateConfig)
            .where(GlobalRateConfig.status == "APPROVED")
            .where(GlobalRateConfig.effective_from <= when)
            .where(or_(GlobalRateConfig.effective_to.is_(None),
                       GlobalRateConfig.effective_to > when))
            .order_by(GlobalRateConfig.effective_from.desc())
            .limit(1)
        )

    def open_version(self) -> GlobalRateConfig | None:
        """The latest open-ended version -- the one an edit builds on."""
        return self.s.scalar(
            select(GlobalRateConfig)
            .where(GlobalRateConfig.status == "APPROVED")
            .where(GlobalRateConfig.effective_to.is_(None))
            .order_by(GlobalRateConfig.version.desc())
            .limit(1)
        )

    def history(self, limit: int = 100) -> list[GlobalRateConfig]:
        return list(self.s.scalars(
            select(GlobalRateConfig)
            .order_by(GlobalRateConfig.effective_from.desc(),
                      GlobalRateConfig.version.desc())
            .limit(limit)
        ))

    def priced_by(self, version: int) -> tuple[int, int]:
        """Completed runs and rows this version priced, as (runs, rows).

        Read from `calculation_runs` rather than the fact table: the run records
        the configuration version it used (`global_config_id` holds the version,
        see `pipeline`), and counting a few hundred runs beats a sequential scan
        of a partitioned table holding millions of rows per day.
        """
        row = self.s.execute(
            select(func.count(),
                   func.coalesce(func.sum(CalculationRun.rows_out), 0))
            .select_from(CalculationRun)
            .where(CalculationRun.global_config_id == version)
            .where(CalculationRun.status == "COMPLETED")
        ).one()
        return int(row[0] or 0), int(row[1] or 0)

    def products_missing_benchmark(self, on: date) -> list[str]:
        """Active products with no benchmark of their own, on a date.

        A product benchmark always wins over the global one, so these are
        exactly the products that depend on the global benchmark being set. If
        it is NULL they resolve to nothing -- deliberately an error rather than
        a zero spread -- which is why clearing it is refused while this list is
        non-empty.
        """
        overrides = load_product_overrides(self.s, on)
        codes = self.s.scalars(
            select(Product.product_code)
            .where(Product.is_active.is_(True))
            .order_by(Product.product_code)
        )
        return [
            code for code in codes
            if (o := overrides.get(code)) is None or o.benchmark_rate is None
        ]

    def _assert_benchmark_resolvable(self, values: dict, on: date) -> None:
        """A NULL global benchmark is only valid if every product overrides it."""
        if values["benchmark_rate"] is not None:
            return
        missing = self.products_missing_benchmark(on)
        if missing:
            raise ConfigError(
                f"Benchmark rate is required: "
                f"{', '.join(missing)} "
                f"{'has' if len(missing) == 1 else 'have'} no product benchmark "
                f"and would not be priceable. Set a benchmark on "
                f"{'that product' if len(missing) == 1 else 'those products'} "
                f"first, or enter a global benchmark."
            )

    # --- writes ----------------------------------------------------------- #

    def _resolve(self, base: GlobalRateConfig | None, changes: dict[str, Any]) -> dict:
        """Apply the supplied changes over the current values."""
        out: dict[str, Any] = {}
        for field in ("benchmark_rate", "liquidity_cost", "other_cost"):
            supplied = changes.get(field, KEEP)
            if supplied is KEEP:
                out[field] = getattr(base, field) if base else None
            else:
                out[field] = _rate(supplied, field)

        basis = changes.get("day_count_basis", KEEP)
        if basis is KEEP:
            out["day_count_basis"] = (base.day_count_basis if base
                                      else DayCountBasis.ACT_365)
        else:
            out["day_count_basis"] = (DayCountBasis(basis) if isinstance(basis, str)
                                      else basis)

        for field in REQUIRED_COMPONENTS:
            if out[field] is None:
                raise ConfigError(
                    f"{field.replace('_', ' ').capitalize()} is required. "
                    f"Without it, products that do not override it cannot be "
                    f"priced."
                )
        return out

    def set_rates(self, *, effective_from: date | None = None,
                  note: str | None = None, **changes: Any) -> GlobalRateConfig:
        """Open a new effective-dated version from a date onwards.

        Closing rather than overwriting is what keeps a historical figure
        explainable: the fact row that priced in March still points at the
        version that was in force in March. A version that would start on or
        after the new date -- a backdated change landing before the latest
        version -- is marked SUPERSEDED, kept in the history but no longer in
        force. Days already uploaded are then reported for recalculation.
        """
        start = effective_from or date.today()
        current = self.open_version()
        values = self._resolve(current, changes)
        self._assert_benchmark_resolvable(values, start)

        before = snapshot(current) if current is not None else None

        G = GlobalRateConfig
        approved = list(self.s.scalars(
            select(G).where(G.status == "APPROVED").order_by(G.effective_from)))
        superseded = [c for c in approved if c.effective_from >= start]
        for c in superseded:
            c.status = "SUPERSEDED"
            c.updated_by = self.actor_id
        for c in approved:
            if c.effective_from < start and (c.effective_to is None
                                             or c.effective_to > start):
                c.effective_to = start
                c.updated_by = self.actor_id
        # Written before the new row so the no-overlap constraint sees them.
        self.s.flush()

        if before is not None and superseded:
            before["superseded_versions"] = [c.version for c in superseded]
        version = (self.s.scalar(select(func.max(G.version))) or 0) + 1

        cfg = GlobalRateConfig(
            version=version,
            effective_from=start,
            effective_to=None,
            status="APPROVED",
            maker_id=self.actor_id,
            approved_at=datetime.now(timezone.utc),
            note=note or "Updated by a head-office administrator.",
            created_by=self.actor_id,
            **values,
        )
        self.s.add(cfg)
        self.s.flush()

        audit.record(
            self.s, action="CONFIG_RATE_VERSION", entity_type="global_rate_config",
            entity_id=f"v{version}",
            before=before, after=snapshot(cfg),
            actor_user_id=self.actor_id, actor_username=self.actor_username,
        )
        return cfg

    def correct(self, *, note: str | None = None, **changes: Any) -> GlobalRateConfig:
        """Rewrite the current version in place, if nothing has priced on it."""
        current = self.open_version()
        if current is None:
            raise ConfigError("There is no open configuration version to correct.")
        runs, rows = self.priced_by(current.version)
        if runs:
            raise ConfigInUse(current.version, runs, rows)

        before = snapshot(current)
        values = self._resolve(current, changes)
        start = changes.get("effective_from") or current.effective_from
        self._assert_benchmark_resolvable(values, start)

        # Decide before touching the row. A path that mutates and then raises
        # would leave the change to be undone by the caller's rollback, which
        # is a guarantee worth not depending on.
        unchanged = (
            all(getattr(current, f) == v for f, v in values.items())
            and start == current.effective_from
            and (not note or note == current.note)
        )
        if unchanged:
            raise ConfigError("No changes supplied.")

        for field, value in values.items():
            setattr(current, field, value)
        current.effective_from = start
        if note:
            current.note = note
        current.updated_by = self.actor_id
        self.s.flush()
        after = snapshot(current)

        audit.record(
            self.s, action="CONFIG_RATE_CORRECT", entity_type="global_rate_config",
            entity_id=f"v{current.version}",
            before=before, after=after,
            actor_user_id=self.actor_id, actor_username=self.actor_username,
        )
        return current
