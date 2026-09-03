"""Shared test fixtures: a reference scope registry and report builders."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from microcluster.models import (
    CHECKLIST,
    Category,
    Onset,
    Report,
    Scope,
    ScopeLevel,
    ScopeRegistry,
)

# A fixed evaluation instant so every test is deterministic.
NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)


def standard_registry() -> ScopeRegistry:
    """Campus n=2000: five buildings of 400; building B1 has three floors
    (~130 each); floor F1 has five suites (~26 each)."""
    scopes: dict[str, Scope] = {}

    def add(scope: Scope) -> None:
        scopes[scope.id] = scope

    add(Scope("C", "Campus", ScopeLevel.CAMPUS, population=2000))
    for b in range(1, 6):
        add(Scope(f"B{b}", f"Building {b}", ScopeLevel.BUILDING, 400, parent_id="C"))

    add(Scope("F1", "Bldg 1 / Floor 1", ScopeLevel.FLOOR, 130, parent_id="B1"))
    add(Scope("F2", "Bldg 1 / Floor 2", ScopeLevel.FLOOR, 130, parent_id="B1"))
    add(Scope("F3", "Bldg 1 / Floor 3", ScopeLevel.FLOOR, 140, parent_id="B1"))

    for s in range(1, 6):
        add(Scope(f"S{s}", f"Bldg 1 / Fl 1 / Suite {s}", ScopeLevel.SUITE, 26, parent_id="F1"))

    return ScopeRegistry(scopes)


def small_registry_floor18() -> ScopeRegistry:
    """A campus with a floor of declared population 18 whose parent
    building is declared 25. Used for the privacy-refusal scenario."""
    return ScopeRegistry(
        {
            "C": Scope("C", "Campus", ScopeLevel.CAMPUS, population=300),
            "B": Scope("B", "Annex building", ScopeLevel.BUILDING, 25, parent_id="C"),
            "F": Scope("F", "Annex / top floor", ScopeLevel.FLOOR, 18, parent_id="B"),
        }
    )


def roster_registry() -> ScopeRegistry:
    """A large campus (n=2000) with one small declared group (n=25).
    Used for the "disclosure would be a roster" scenario: enough reports
    to clear the statistical gate and the population minimum, but so many
    relative to n=25 that naming the group names its members."""
    return ScopeRegistry(
        {
            "C": Scope("C", "Campus", ScopeLevel.CAMPUS, population=2000),
            "G": Scope("G", "Studio group", ScopeLevel.SUITE, 25, parent_id="C"),
        }
    )


def single_scope_registry(n: int) -> ScopeRegistry:
    """A campus-only registry of declared population ``n``. Used for the
    across-populations gate table."""
    return ScopeRegistry({"C": Scope("C", f"Campus n={n}", ScopeLevel.CAMPUS, population=n)})


def report(
    location_id: str,
    *,
    category: Category = Category.RESPIRATORY,
    hours_ago: float = 1.0,
    onset: Onset = Onset.TODAY,
    now: datetime = NOW,
) -> Report:
    """One report at ``location_id``, submitted ``hours_ago`` before
    ``now``. Symptom is the first in the category's checklist -- it is
    never used for matching, so its value does not matter to the engines."""
    return Report(
        category=category,
        symptom=CHECKLIST[category][0],
        onset=onset,
        location_id=location_id,
        submitted_at=now - timedelta(hours=hours_ago),
    )


def reports(location_id: str, count: int, **kwargs) -> list[Report]:
    return [report(location_id, **kwargs) for _ in range(count)]
