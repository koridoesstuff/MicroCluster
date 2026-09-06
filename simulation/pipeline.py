"""End-to-end wiring: simulated agents -> anonymous reports -> the
EXISTING, UNMODIFIED detection engine -> disclosure.

This module is the one place ground truth (``Simulation`` / ``Agent``
state) and the production engines (``microcluster.engine`` /
``detection`` / ``disclosure``) meet. Only ``Report`` objects and the
``ScopeRegistry`` cross that line -- see CLAUDE.md, "The ground-truth
firewall". ``DailyRecord.true_infected_count`` is the one deliberate
exception: it is ground truth kept for MEASURING the detector after the
fact, and is never part of what gets fed to it.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import timedelta

from microcluster.config import DEFAULT_DETECTION_CONFIG, DEFAULT_DISCLOSURE_CONFIG
from microcluster.config import DetectionConfig, DisclosureConfig
from microcluster.detection import HysteresisState
from microcluster.disclosure import ScopeEvaluation
from microcluster.engine import analyze
from microcluster.models import Report

from . import reporting
from .config import DEFAULT_SIMULATION_CONFIG, SimulationConfig
from .infection import InfectionState
from .population import StructureSpec
from .simulator import Simulation

__all__ = [
    "DailyRecord",
    "SimulationRun",
    "SimulatedReports",
    "simulate_and_report",
    "analyze_report_stream",
    "run_with_detection",
]


@dataclass(frozen=True)
class DailyRecord:
    """What happened on one simulated day, from both sides of the
    ground-truth firewall.

    ``first_fired_day`` / ``first_disclosed_day`` are running totals as of
    THIS day (``None`` until the first time each has happened), recorded
    here rather than left for a caller to re-derive later by scanning the
    record list. The gap between them -- time-to-first-DISCLOSURE minus
    time-to-first-FIRE -- is the measurable cost of the privacy policy:
    how long the system knew something before it was permitted to say
    where.
    """

    day: int
    true_infected_count: int  # ground truth, kept for measurement only
    reports_submitted_today: int
    reports_accumulated: int
    detection_fired: bool
    relative_fired: bool
    absolute_fired: bool
    disclosed_scope_id: str | None
    first_fired_day: int | None
    first_disclosed_day: int | None

    # The complete disclosure gate table for this day (rule 12): a
    # ScopeEvaluation for every candidate scope, winner and rejected
    # alike, exactly as disclosure.evaluate returned it. Empty on days the
    # detector did not fire (disclosure does not run). The presentation
    # layer renders these and never recomputes a gate.
    disclosure_evaluations: tuple[ScopeEvaluation, ...] = ()


@dataclass
class SimulationRun:
    simulation: Simulation
    reports: list[Report]
    daily_records: list[DailyRecord]

    def distinct_disclosed_scopes(self) -> list[str]:
        """Every distinct scope id ever disclosed over the run, in the
        order each was first named. Small and stable is the point of
        scope-stability disclosure (config.SIBLING_SWITCH_MARGIN); a long
        list here means disclosure wandered."""
        seen: list[str] = []
        for record in self.daily_records:
            scope_id = record.disclosed_scope_id
            if scope_id is not None and scope_id not in seen:
                seen.append(scope_id)
        return seen


@dataclass
class SimulatedReports:
    """One simulated run's epidemic plus the anonymous reports it produced,
    day by day -- everything EXCEPT the detection/disclosure analysis.

    Split out from :func:`run_with_detection` so an experiment can simulate
    a seed once and then replay the analysis under many different engine
    configs cheaply (see :func:`analyze_report_stream` and
    ``simulation.experiments``). The simulated epidemic and the reports
    depend on nothing in ``microcluster`` -- neither the detection nor the
    disclosure config -- so it is always safe to reuse this across configs.
    """

    simulation: Simulation
    config: SimulationConfig
    daily_reports: list[list[Report]]  # index d -> the reports generated on day d


def simulate_and_report(
    *,
    seed: int,
    days: int,
    spec: StructureSpec | None = None,
    config: SimulationConfig = DEFAULT_SIMULATION_CONFIG,
    seed_infections: int | None = None,
) -> SimulatedReports:
    """Run the simulator for ``days`` days and generate each day's
    anonymous reports, WITHOUT analysing them.

    Report generation uses its own RNG stream (``f"reporting-{seed}"``),
    independent of the simulation's own, and is interleaved with the daily
    steps exactly as :func:`run_with_detection` does it -- so the two
    produce byte-identical report streams for the same seed.
    """
    sim = Simulation(seed=seed, spec=spec, config=config, seed_infections=seed_infections)
    report_rng = random.Random(f"reporting-{seed}")

    daily_reports: list[list[Report]] = [
        reporting.generate_daily_reports(sim.agents, 0, report_rng, config)
    ]
    for _ in range(days):
        day_state = sim.step()
        daily_reports.append(
            reporting.generate_daily_reports(sim.agents, day_state.day, report_rng, config)
        )
    return SimulatedReports(simulation=sim, config=config, daily_reports=daily_reports)


def analyze_report_stream(
    simulated: SimulatedReports,
    *,
    detection_config: DetectionConfig = DEFAULT_DETECTION_CONFIG,
    disclosure_config: DisclosureConfig = DEFAULT_DISCLOSURE_CONFIG,
    thread_scope_stability: bool = True,
) -> list[DailyRecord]:
    """Replay ``microcluster.engine.analyze`` day by day over an
    already-simulated report stream, feeding the ACCUMULATED reports so
    far with ``now`` set to the simulated timestamp (never the wall
    clock). Detection hysteresis and disclosure scope stability are
    threaded day to day.

    Pure with respect to ``simulated`` -- safe to call repeatedly with
    different ``detection_config`` / ``disclosure_config`` on the same
    ``SimulatedReports``.

    ``thread_scope_stability=False`` stops threading
    ``prior_disclosed_scope_id``, so each day's disclosure is the plain
    finest-eligible pick with no continuity preference.
    """
    sim = simulated.simulation
    config = simulated.config

    all_reports: list[Report] = []
    daily_records: list[DailyRecord] = []
    hysteresis_state: HysteresisState | None = None
    prior_disclosed_scope_id: str | None = None
    first_fired_day: int | None = None
    first_disclosed_day: int | None = None

    for day, new_reports in enumerate(simulated.daily_reports):
        all_reports.extend(new_reports)
        now = config.simulation_start + timedelta(days=day)
        analysis = analyze(
            all_reports,
            sim.registry,
            now=now,
            detection_config=detection_config,
            disclosure_config=disclosure_config,
            hysteresis_state=hysteresis_state,
            prior_disclosed_scope_id=(
                prior_disclosed_scope_id if thread_scope_stability else None
            ),
        )
        hysteresis_state = analysis.detection.hysteresis_state
        # The stability "anchor" only moves when a scope is actually named
        # today; a quiet day (nothing disclosed) does not reset it, so the
        # NEXT disclosure still prefers the last-named scope's lineage.
        if analysis.disclosed_scope_id is not None:
            prior_disclosed_scope_id = analysis.disclosed_scope_id

        if first_fired_day is None and analysis.detection.fired:
            first_fired_day = day
        if first_disclosed_day is None and analysis.disclosed_scope_id is not None:
            first_disclosed_day = day

        day_state = sim.history[day]
        true_infected = day_state.count(InfectionState.INCUBATING) + day_state.count(
            InfectionState.SYMPTOMATIC
        )
        daily_records.append(
            DailyRecord(
                day=day,
                true_infected_count=true_infected,
                reports_submitted_today=len(new_reports),
                reports_accumulated=len(all_reports),
                detection_fired=analysis.detection.fired,
                relative_fired=analysis.detection.relative_detector_fired,
                absolute_fired=analysis.detection.absolute_detector_fired,
                disclosed_scope_id=analysis.disclosed_scope_id,
                first_fired_day=first_fired_day,
                first_disclosed_day=first_disclosed_day,
                disclosure_evaluations=analysis.disclosure.evaluations,
            )
        )
    return daily_records


def run_with_detection(
    *,
    seed: int,
    days: int,
    spec: StructureSpec | None = None,
    config: SimulationConfig = DEFAULT_SIMULATION_CONFIG,
    seed_infections: int | None = None,
    detection_config: DetectionConfig = DEFAULT_DETECTION_CONFIG,
    disclosure_config: DisclosureConfig = DEFAULT_DISCLOSURE_CONFIG,
) -> SimulationRun:
    """Simulate ``days`` days for ``seed``, generate the anonymous report
    stream, and analyse it day by day -- the full end-to-end pipeline.

    Equivalent to ``simulate_and_report`` followed by
    ``analyze_report_stream``; kept as one call for the common case where
    a caller wants a single run under a single set of configs.
    """
    simulated = simulate_and_report(
        seed=seed, days=days, spec=spec, config=config, seed_infections=seed_infections
    )
    daily_records = analyze_report_stream(
        simulated,
        detection_config=detection_config,
        disclosure_config=disclosure_config,
    )
    all_reports = [report for day_reports in simulated.daily_reports for report in day_reports]
    return SimulationRun(
        simulation=simulated.simulation,
        reports=all_reports,
        daily_records=daily_records,
    )
