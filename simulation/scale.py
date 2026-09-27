"""Scale validation: does the pipeline still behave at 500 / 1,000 / 2,000
people with four scope levels (campus > building > floor > suite)?

The population builder was already parametric; what was never exercised was
a structure with more than one building, so the BUILDING scope always
equalled the CAMPUS scope and the hierarchy had three DISTINCT levels. The
specs below give four distinct levels at every size. No engine, gate or
simulator logic is touched -- this module only builds bigger structures,
runs the existing pipeline over a seeded sweep, and CHECKS the results
against the gate formulas independently of the engine that produced them.

    python -m simulation.scale            # prints the table
    python -m scripts.stress_tests        # writes results/scale.json too

Every number here is a property of this simulator with CHOSEN parameters
(see config.py); it says whether the machinery scales, not what a real
building would do.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from statistics import mean, median

from microcluster.config import DEFAULT_DISCLOSURE_CONFIG
from microcluster.models import ScopeLevel

from .config import DEFAULT_RUN_DAYS
from .experiments import reduce_run, summarize_setting
from .infection import InfectionState
from .pipeline import run_with_detection
from .population import StructureSpec

__all__ = ["SCALE_SPECS", "SizeReport", "measure_size", "run_scale_validation"]

# (buildings, floors per building, suites per floor, agents per suite).
# Suite size stays 25 so the suite-level gates are identical at every size
# and any change is attributable to the HIERARCHY growing, not the suite.
SCALE_SPECS: dict[int, StructureSpec] = {
    150: StructureSpec(1, 2, 3, 25),    # the shipped baseline (3 distinct levels)
    500: StructureSpec(2, 2, 5, 25),
    1000: StructureSpec(2, 4, 5, 25),
    2000: StructureSpec(4, 4, 5, 25),
}


@dataclass
class SizeReport:
    n_agents: int
    n_suites: int
    n_distinct_populations: int      # distinct declared populations across the hierarchy
    n_runs: int
    seconds_per_run: float

    # plausibility of the simulated epidemic
    established_fraction: float
    median_attack_rate: float | None          # of ALL agents, established runs
    median_attack_rate_in_touched: float | None  # of the buildings that got any case
    median_buildings_touched: float | None     # buildings with >= 1 ever-infected
    peaks_and_declines_fraction: float | None  # established runs whose curve turns down

    # evidence gate vs its formula
    scope_evaluations_checked: int
    threshold_formula_violations: int          # engine threshold != max(5, ceil(sqrt n))
    pass_flag_violations: int                  # stat_pass != (qualifying >= threshold)
    selected_without_both_gates: int
    thresholds_by_level: dict[str, int] = field(default_factory=dict)

    # privacy gate
    roster_refusals: int = 0                   # stat PASS but privacy FAIL (scope-days)
    roster_refusal_levels: dict[str, int] = field(default_factory=dict)
    runs_with_a_roster_refusal: int = 0

    # timing (established runs that disclosed)
    n_established: int = 0
    n_disclosed: int = 0
    mean_fire_delay: float | None = None
    mean_disclosure_delay: float | None = None
    mean_gap: float | None = None
    infections_before_disclosure: float | None = None       # unbiased
    infections_before_disclosure_pct: float | None = None   # of all agents
    finest_level_histogram: dict[str, int] = field(default_factory=dict)
    false_alarm_rate: float | None = None
    fizzle_rate: float = 0.0
    relative_fired_days: int = 0
    absolute_fired_days: int = 0
    errors: int = 0


def _ceil_sqrt(n: int) -> int:
    root = math.isqrt(n)
    return root if root * root == n else root + 1


def measure_size(
    n_agents: int, seeds: list[int], *, days: int = DEFAULT_RUN_DAYS
) -> SizeReport:
    spec = SCALE_SPECS[n_agents]
    floor = DEFAULT_DISCLOSURE_CONFIG.statistical_gate_floor
    outcomes = []
    attack_rates: list[float] = []
    attack_touched: list[float] = []
    buildings_touched: list[int] = []
    peaked = established = 0
    checked = thr_bad = flag_bad = sel_bad = 0
    thresholds: dict[str, int] = {}
    roster = roster_runs = 0
    roster_levels: dict[str, int] = {}
    rel_days = abs_days = 0
    errors = 0
    n_suites = 0
    populations_seen: set[int] = set()
    t0 = time.perf_counter()

    for seed in seeds:
        try:
            run = run_with_detection(seed=seed, days=days, spec=spec)
        except Exception:  # a component failing outright is a RESULT, not a crash
            errors += 1
            continue
        sim, records = run.simulation, run.daily_records
        n_suites = sum(1 for s in sim.registry.scopes.values() if s.level is ScopeLevel.SUITE)
        populations_seen = {s.population for s in sim.registry.scopes.values()}
        outcome = reduce_run(seed, sim, records)
        outcomes.append(outcome)

        if outcome.established:
            established += 1
            attack_rates.append(outcome.total_infections / len(sim.agents))
            final = sim.history[-1]
            touched = {
                a.suite_id.rsplit("-F", 1)[0]
                for a in final.agents
                if a.state is not InfectionState.SUSCEPTIBLE
            }
            buildings_touched.append(len(touched))
            bpop = sim.registry.get(sorted(touched)[0]).population
            attack_touched.append(outcome.total_infections / (len(touched) * bpop))
            active = [
                s.count(InfectionState.INCUBATING) + s.count(InfectionState.SYMPTOMATIC)
                for s in sim.history
            ]
            if max(active) > 0 and active.index(max(active)) < len(active) - 1 and active[-1] < max(active):
                peaked += 1

        run_refused = False
        for rec in records:
            rel_days += rec.relative_fired
            abs_days += rec.absolute_fired
            for ev in rec.disclosure_evaluations:
                checked += 1
                expected = max(floor, _ceil_sqrt(ev.population))
                thresholds[ev.scope_level.name] = expected
                if ev.statistical_threshold != expected:
                    thr_bad += 1
                if ev.statistical_pass != (ev.qualifying_reports >= ev.statistical_threshold):
                    flag_bad += 1
                if ev.selected and not (ev.statistical_pass and ev.privacy_pass):
                    sel_bad += 1
                if ev.statistical_pass and not ev.privacy_pass:
                    roster += 1
                    run_refused = True
                    roster_levels[ev.scope_level.name] = roster_levels.get(ev.scope_level.name, 0) + 1
        roster_runs += run_refused

    elapsed = time.perf_counter() - t0
    summary = summarize_setting(outcomes, param_name="size", value=n_agents)
    finest: dict[str, int] = {}
    for o in outcomes:
        if o.established and o.finest_disclosed_level is not None:
            name = o.finest_disclosed_level.name
            finest[name] = finest.get(name, 0) + 1

    def _pct(x: float | None) -> float | None:
        return None if x is None else x / n_agents * 100

    return SizeReport(
        n_agents=n_agents,
        n_suites=n_suites,
        n_distinct_populations=len(populations_seen),
        n_runs=len(outcomes),
        seconds_per_run=elapsed / max(1, len(seeds)),
        established_fraction=(established / len(outcomes)) if outcomes else 0.0,
        median_attack_rate=median(attack_rates) if attack_rates else None,
        median_attack_rate_in_touched=median(attack_touched) if attack_touched else None,
        median_buildings_touched=median(buildings_touched) if buildings_touched else None,
        peaks_and_declines_fraction=(peaked / established) if established else None,
        scope_evaluations_checked=checked,
        threshold_formula_violations=thr_bad,
        pass_flag_violations=flag_bad,
        selected_without_both_gates=sel_bad,
        thresholds_by_level=thresholds,
        roster_refusals=roster,
        roster_refusal_levels=roster_levels,
        runs_with_a_roster_refusal=roster_runs,
        n_established=summary.n_established,
        n_disclosed=summary.n_disclosed,
        mean_fire_delay=summary.mean_fire_delay,
        mean_disclosure_delay=summary.mean_disclosure_delay,
        mean_gap=summary.mean_gap,
        infections_before_disclosure=summary.mean_infections_before_disclosure_unbiased,
        infections_before_disclosure_pct=_pct(summary.mean_infections_before_disclosure_unbiased),
        finest_level_histogram=finest,
        false_alarm_rate=summary.false_alarm_rate,
        fizzle_rate=1 - (established / len(outcomes)) if outcomes else 0.0,
        relative_fired_days=rel_days,
        absolute_fired_days=abs_days,
        errors=errors,
    )


def run_scale_validation(
    seeds: list[int] | None = None, sizes: tuple[int, ...] = (150, 500, 1000, 2000)
) -> list[SizeReport]:
    seed_list = seeds if seeds is not None else list(range(1, 201))
    return [measure_size(n, seed_list) for n in sizes]


def _f(v: float | None, d: int = 1) -> str:
    return "n/a" if v is None else f"{v:.{d}f}"


def format_reports(reports: list[SizeReport]) -> str:
    lines = ["SCALE VALIDATION (same pipeline, same gates, bigger structures)", ""]
    for r in reports:
        lines += [
            f"--- {r.n_agents} agents, {r.n_suites} suites, {r.n_distinct_populations} distinct scope populations "
            f"({r.n_runs} runs, {r.seconds_per_run:.2f}s/run, {r.errors} errors)",
            f"  epidemic : established {r.established_fraction:.0%}, median attack rate "
            f"{_f(None if r.median_attack_rate is None else r.median_attack_rate * 100)}% of all agents, "
            f"{_f(None if r.median_attack_rate_in_touched is None else r.median_attack_rate_in_touched * 100)}% of the building(s) touched, "
            f"median buildings touched {_f(r.median_buildings_touched)}, "
            f"peak-then-decline {_f(None if r.peaks_and_declines_fraction is None else r.peaks_and_declines_fraction * 100, 0)}%",
            f"  evidence : {r.scope_evaluations_checked} scope evaluations checked; formula violations "
            f"{r.threshold_formula_violations}, pass-flag violations {r.pass_flag_violations}, "
            f"selected-without-both-gates {r.selected_without_both_gates}; thresholds {r.thresholds_by_level}",
            f"  privacy  : roster refusals {r.roster_refusals} in {r.runs_with_a_roster_refusal} runs, by level {r.roster_refusal_levels}",
            f"  timing   : fire day {_f(r.mean_fire_delay)}, disclosure day {_f(r.mean_disclosure_delay)}, gap {_f(r.mean_gap)}, "
            f"infected before disclosure {_f(r.infections_before_disclosure)} "
            f"({_f(r.infections_before_disclosure_pct)}% of agents); disclosed {r.n_disclosed}/{r.n_established}; "
            f"false-alarm rate {_f(None if r.false_alarm_rate is None else r.false_alarm_rate * 100, 0)}%",
            f"  finest level named (established runs): {r.finest_level_histogram}",
            "",
        ]
    return "\n".join(lines)


def main() -> None:
    print(format_reports(run_scale_validation()))


if __name__ == "__main__":
    main()
