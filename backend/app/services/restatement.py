"""Recalculating dates that were priced on rates since superseded.

A rate version can be opened with an effective date in the past. That changes
which rates *apply* to days already uploaded, but not the figures stored for
them: those were computed once, at upload, and each fact row records the
configuration versions it used. Until the date is recalculated the dashboard
and the rate history disagree.

Staleness is detected rather than flagged. A date is stale when the versions
stamped on its current facts differ from the versions the rate book resolves
for that date today. That catches product and global changes alike, and it
clears itself once the date is recalculated or re-uploaded -- there is no flag
to forget to reset.

Recalculation is never automatic. An administrator sees the stale dates and
chooses to restate them; the run and the reason are audited.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.errors import ConfigMissingError
from app.models import BankDailyAccountData, CalculationRun, FtpCalculationResult
from app.repositories.rates import RateBook
from app.services import audit
from app.services.pipeline import UploadPipeline, _ref


class RestatementError(Exception):
    """The requested dates cannot be recalculated."""


@dataclass
class StaleDate:
    business_date: date
    products: list[str] = field(default_factory=list)
    rows: int = 0
    #: Set when the rates for the date cannot be resolved at all; such a date
    #: would fail to recalculate, so it is reported but not offered.
    blocked_by: str | None = None


def stale_dates(session: Session) -> list[StaleDate]:
    """Dates whose current figures were priced on superseded rate versions.

    One grouped read over the current facts -- a row per date, product and
    version pair -- then one rate book per date to compare against.
    """
    F = FtpCalculationResult
    groups = session.execute(
        select(F.business_date, F.product_code,
               F.global_config_version, F.product_config_version,
               func.count())
        .where(F.is_current.is_(True))
        .group_by(F.business_date, F.product_code,
                  F.global_config_version, F.product_config_version)
        .order_by(F.business_date)
    ).all()

    out: dict[date, StaleDate] = {}
    books: dict[date, RateBook | str] = {}
    for on, code, g_ver, p_ver, n in groups:
        if on not in books:
            try:
                books[on] = RateBook(session, on)
            except ConfigMissingError as exc:
                books[on] = str(exc)
        book = books[on]

        if isinstance(book, str):
            entry = out.setdefault(on, StaleDate(on, blocked_by=book))
        else:
            override = book.overrides.get(code)
            in_force = override.version if override else None
            if g_ver == book.global_rates.version and p_ver == in_force:
                continue
            entry = out.setdefault(on, StaleDate(on))

        if code not in entry.products:
            entry.products.append(code)
        entry.rows += n

    return list(out.values())


class RestatementService:
    def __init__(self, session: Session, *, actor_id: int | None = None,
                 actor_username: str | None = None) -> None:
        self.s = session
        self.actor_id = actor_id
        self.actor_username = actor_username

    def recalculate(self, dates: list[date], reason: str | None = None) -> dict:
        """Rebuild the facts and aggregates for stale dates.

        Only dates currently reported stale are accepted, so this cannot be
        used to rerun arbitrary days.
        """
        if not dates:
            raise RestatementError("No dates supplied.")
        wanted = sorted(set(dates))

        stale = {s.business_date: s for s in stale_dates(self.s)}
        not_stale = [d for d in wanted if d not in stale]
        if not_stale:
            raise RestatementError(
                "These dates are already priced on the rates in force and need "
                "no recalculation: "
                + ", ".join(d.isoformat() for d in not_stale))
        blocked = [stale[d] for d in wanted if stale[d].blocked_by]
        if blocked:
            raise RestatementError(
                "Rates cannot be resolved for "
                + "; ".join(f"{s.business_date.isoformat()} ({s.blocked_by})"
                            for s in blocked))

        B = BankDailyAccountData
        empty = [
            d for d in wanted
            if not self.s.scalar(
                select(func.count()).select_from(B)
                .where(B.business_date == d).where(B.is_current.is_(True)))
        ]
        if empty:
            raise RestatementError(
                "No current uploaded rows remain for "
                + ", ".join(d.isoformat() for d in empty))

        before = {d.isoformat(): {"products": stale[d].products,
                                  "rows": stale[d].rows} for d in wanted}

        run = CalculationRun(
            run_ref=_ref("RUN"), trigger_type="MANUAL",
            business_date_from=wanted[0], business_date_to=wanted[-1],
            status="RUNNING", started_at=datetime.now(UTC),
            initiated_by=self.actor_id,
        )
        self.s.add(run)
        self.s.flush()

        pipe = UploadPipeline(self.s, actor_id=self.actor_id,
                              actor_username=self.actor_username)
        pipe.recalculate(run, wanted)
        pipe.refresh_aggregates(run, wanted)

        audit.record(
            self.s, action="RATE_RESTATE", entity_type="calculation_run",
            entity_id=run.run_ref, before=before,
            after={"dates": [d.isoformat() for d in wanted],
                   "rows": run.rows_out, "reason": reason},
            actor_user_id=self.actor_id, actor_username=self.actor_username,
        )
        return {"run_ref": run.run_ref, "dates_recalculated": wanted,
                "rows": run.rows_out}
