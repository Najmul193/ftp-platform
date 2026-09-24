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
chooses, per date, to restate them or to keep the figures already published.
Either way the rates now in force price every later upload, and the choice is
audited. A kept date is remembered against the exact rates in force for it, so
a further rate change touching that date surfaces it again: recalculation is
whole-day, and a new decision is needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.errors import ConfigMissingError
from app.models import (
    BankDailyAccountData, CalculationRun, FtpCalculationResult, SystemSetting,
)
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
    #: The published figures were deliberately kept on the earlier rates.
    kept: bool = False
    kept_by: str | None = None
    kept_at: str | None = None


#: system_settings key holding the dates kept on earlier rates:
#: {"YYYY-MM-DD": {"rates": <fingerprint>, "by": username, "at": iso time}}.
KEPT_KEY = "rate_restatement_kept"


def _fingerprint(book: RateBook) -> str:
    """The rate versions in force for a date, as one comparable string."""
    overrides = ",".join(f"{code}:{r.version}"
                         for code, r in sorted(book.overrides.items()))
    return f"g{book.global_rates.version}|{overrides}"


def _kept(session: Session) -> SystemSetting | None:
    return session.scalar(select(SystemSetting).filter_by(key=KEPT_KEY))


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

    kept_row = _kept(session)
    kept = kept_row.value if kept_row else {}

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
            entry = out.get(on)
            if entry is None:
                mark = kept.get(on.isoformat())
                entry = out[on] = StaleDate(on)
                if mark and mark.get("rates") == _fingerprint(book):
                    entry.kept = True
                    entry.kept_by, entry.kept_at = mark.get("by"), mark.get("at")

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

    def keep(self, dates: list[date], reason: str | None = None) -> dict:
        """Keep the published figures for stale dates on their earlier rates.

        Nothing is recalculated. The rates now in force still price every
        later upload, including a re-upload of one of these dates.
        """
        if not dates:
            raise RestatementError("No dates supplied.")
        wanted = sorted(set(dates))
        stale = {s.business_date: s for s in stale_dates(self.s)}
        not_stale = [d for d in wanted if d not in stale]
        if not_stale:
            raise RestatementError(
                "These dates are already priced on the rates in force: "
                + ", ".join(d.isoformat() for d in not_stale))

        row = _kept(self.s)
        if row is None:
            row = SystemSetting(
                key=KEPT_KEY, value={},
                description="Dates whose published figures were kept on the "
                            "rates in force before a backdated rate change.",
                created_by=self.actor_id)
            self.s.add(row)
        value = dict(row.value or {})
        at = datetime.now(UTC).isoformat()
        for d in wanted:
            value[d.isoformat()] = {"rates": _fingerprint(RateBook(self.s, d)),
                                    "by": self.actor_username, "at": at}
        # A new dict, so the JSONB column is seen as changed.
        row.value = value
        row.updated_by = self.actor_id
        self.s.flush()

        audit.record(
            self.s, action="RATE_RESTATE_KEPT", entity_type="calculation_run",
            entity_id=f"{wanted[0].isoformat()}..{wanted[-1].isoformat()}",
            after={"dates": [d.isoformat() for d in wanted],
                   "products": sorted({p for d in wanted for p in stale[d].products}),
                   "rows": sum(stale[d].rows for d in wanted), "reason": reason},
            actor_user_id=self.actor_id, actor_username=self.actor_username,
        )
        return {"dates_kept": wanted}

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
