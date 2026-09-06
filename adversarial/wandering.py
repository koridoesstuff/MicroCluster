"""What scope wandering leaks: distinct groups named across a run.

Every distinct scope the system ever discloses is a group the observer
learns about. Scope stability (config.SIBLING_SWITCH_MARGIN) exists to
keep that set small. This measures it against the same run analysed with
stability threading turned off.
"""

from __future__ import annotations

from dataclasses import dataclass

from simulation.pipeline import DailyRecord, SimulatedReports, analyze_report_stream


@dataclass(frozen=True)
class WanderingOutcome:
    stability_on: int
    stability_off: int
    names_on: tuple[str, ...]
    names_off: tuple[str, ...]


def _distinct_named(records: list[DailyRecord]) -> list[str]:
    seen: list[str] = []
    for record in records:
        sid = record.disclosed_scope_id
        if sid is not None and sid not in seen:
            seen.append(sid)
    return seen


def measure_wandering(simulated: SimulatedReports) -> WanderingOutcome:
    on = _distinct_named(analyze_report_stream(simulated))
    off = _distinct_named(
        analyze_report_stream(simulated, thread_scope_stability=False)
    )
    return WanderingOutcome(len(on), len(off), tuple(on), tuple(off))
