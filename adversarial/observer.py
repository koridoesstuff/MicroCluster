"""What a day-by-day observer of the shipped UI can see, and nothing else."""

from __future__ import annotations

from dataclasses import dataclass

from api.bands import band
from simulation.pipeline import DailyRecord


@dataclass(frozen=True)
class DayView:
    """One day as the observer sees it.

    Exactly one of ``exact_count`` / ``band`` is populated: ``exact_count``
    for the pre-band scenario, ``band`` for the shipped one. A day with
    nothing disclosed leaves every field but ``day`` as ``None``.
    """

    day: int
    scope_id: str | None
    scope_label: str | None
    scope_level: str | None
    exact_count: int | None
    band: str | None


def _selected_evaluation(record: DailyRecord):
    for ev in record.disclosure_evaluations:
        if ev.scope_id == record.disclosed_scope_id:
            return ev
    return None


def observe(records: list[DailyRecord], *, leak_exact_counts: bool) -> list[DayView]:
    """Reduce a run's daily records to the observer's view.

    With ``leak_exact_counts=True`` the observer is handed the exact
    qualifying-report count of the disclosed scope (what the UI showed
    before banding). With ``False`` they get only the band.
    """
    views: list[DayView] = []
    for record in records:
        ev = _selected_evaluation(record)
        if ev is None:
            views.append(DayView(record.day, None, None, None, None, None))
            continue
        views.append(
            DayView(
                day=record.day,
                scope_id=ev.scope_id,
                scope_label=ev.scope_label,
                scope_level=ev.scope_level.name,
                exact_count=ev.qualifying_reports if leak_exact_counts else None,
                band=None if leak_exact_counts else band(ev.qualifying_reports),
            )
        )
    return views
