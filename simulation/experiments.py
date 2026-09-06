"""Experiment runner: statistics over many simulated outbreaks.

Still headless -- no plotting, no API, no frontend. Runs the pipeline
across many random seeds, sweeping the DISCLOSURE gates one at a time,
and prints the delay-versus-infections relationship as a plain data
table.

    python -m simulation.experiments

---------------------------------------------------------------------
WHY THE DISCLOSURE GATES, NOT THE DETECTION THRESHOLD
---------------------------------------------------------------------

An earlier version of this runner swept ``ABSOLUTE_EXCESS_RATIO`` (the
detection threshold) and found time-to-disclosure completely invariant to
it -- 14.1 days across every setting. The detector fires well before the
disclosure engine will name anything anyway, so it is the DISCLOSURE
gates, not detection, that set the timing of the first public statement.
So this runner sweeps those, holding detection config at its defaults.

Each disclosure gate ultimately compares an INTEGER qualifying-report
count (or a declared population) against a threshold, so a parameter only
changes behaviour when it crosses a discrete boundary. In the default
structure the scope populations are 25 / 75 / 150 (suite / floor /
building = campus, one building) and ``ceil(sqrt(n))`` is 5 / 9 / 13. The
swept ranges (``config.*_SWEEP``) are deliberately wide enough that
adjacent settings land in different regimes; ``adjacent_duplicate_rows``
flags any that still collapse to an identical row.

---------------------------------------------------------------------
METHODOLOGICAL CHOICE: establishment conditioning
---------------------------------------------------------------------

A single seeded index case is a stochastic branching process (see
``simulation/config.py`` next to ``SUITE_TRANSMISSION_PROBABILITY``): a
real fraction of runs fail to take off at all, purely by chance, before
the detector or the disclosure policy ever get a say. An outbreak counts
as ESTABLISHED once its cumulative (ever-infected) case count reaches
``config.ESTABLISHED_MIN_INFECTIONS``.

Mixing fizzled runs in with established ones would swamp every other
statistic with take-off variance. Standard practice in stochastic
epidemic simulation: report the fade-out (fizzle) rate on its own, then
condition every other statistic on establishment.

The one number NOT conditioned on establishment is the FALSE-ALARM RATE:
the fraction of NON-established runs where the detector fired anyway. It
is the cost side of a loose detector and belongs in the headline results,
not a footnote. Detection is fixed here, so it is a single number.

---------------------------------------------------------------------
READING ``gap`` (policy cost)
---------------------------------------------------------------------

``gap = disclosure_delay - fire_delay``. On its own it is ambiguous: it
shrinks when disclosure gets FASTER (good) or when detection gets SLOWER
(bad). Both delays are printed side by side, over the same subset of runs,
so the two cases cannot be confused -- and because detection config is
held fixed across every sweep, ``fire_delay`` is the control: any movement
in ``gap`` between rows is disclosure timing, not detection.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Callable, Iterable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from microcluster.config import (  # noqa: E402
    DEFAULT_DETECTION_CONFIG,
    DEFAULT_DISCLOSURE_CONFIG,
    DisclosureConfig,
)
from microcluster.disclosure import statistical_threshold  # noqa: E402
from microcluster.models import ScopeLevel  # noqa: E402

from simulation.config import (  # noqa: E402
    DEFAULT_EXPERIMENT_SEEDS,
    DEFAULT_RUN_DAYS,
    ESTABLISHED_MIN_INFECTIONS,
    MAX_REPORT_FRACTION_SWEEP,
    MIN_SCOPE_POPULATION_SWEEP,
    STATISTICAL_GATE_FLOOR_SWEEP,
)
from simulation.infection import InfectionState  # noqa: E402
from simulation.pipeline import (  # noqa: E402
    DailyRecord,
    SimulatedReports,
    analyze_report_stream,
    run_with_detection,
    simulate_and_report,
)
from simulation.simulator import Simulation  # noqa: E402

__all__ = [
    "RunOutcome",
    "SettingSummary",
    "DisclosureSweep",
    "SweepResults",
    "run_once",
    "reduce_run",
    "summarize_setting",
    "fizzle_rate",
    "false_alarm_rate_at_defaults",
    "overall_mean_fire_delay",
    "adjacent_duplicate_rows",
    "degenerate_reason_for",
    "run_disclosure_sweeps",
    "DISCLOSURE_SWEEPS",
]


def degenerate_reason_for(
    config: DisclosureConfig, scope_populations: Iterable[int]
) -> str | None:
    """If NO scope in ``scope_populations`` can pass both gates at ANY
    achievable qualifying count under ``config``, return a one-line reason
    the configuration is structurally impossible; otherwise ``None``.

    This is not a data point -- it is a setting under which the disclosure
    engine can never say anything regardless of the outbreak. A scope of
    declared population ``n`` is disclosable for some count iff::

        n >= min_scope_population
        and  max(statistical_gate_floor, ceil(sqrt(n)))  <=  floor(n * max_report_fraction)

    (the statistical gate's requirement must fit under the privacy gate's
    fraction cap). MIN_SCOPE_POPULATION greater than the whole campus is
    the obvious case; a very low MAX_REPORT_FRACTION is another.
    """
    pops = sorted(set(scope_populations))
    for n in pops:
        if n < config.min_scope_population:
            continue
        need = statistical_threshold(n, config)
        allowed = math.floor(n * config.max_report_fraction)
        if need <= allowed:
            return None
    biggest = pops[-1] if pops else 0
    if all(n < config.min_scope_population for n in pops):
        return (
            f"min_scope_population={config.min_scope_population} exceeds every "
            f"declared scope population (largest is {biggest}); the privacy "
            f"gate can never pass"
        )
    return (
        f"no scope population in {pops} admits a qualifying count that clears "
        f"the statistical gate while staying under max_report_fraction="
        f"{config.max_report_fraction:g}"
    )


# ---------------------------------------------------------------------------
# Per-run outcome
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunOutcome:
    """Ground truth and detection/disclosure outcome for one simulated seed."""

    seed: int
    established: bool
    total_infections: int  # cumulative ever-infected at the end of the run (day 30)
    peak_infected: int  # largest simultaneous (INCUBATING + SYMPTOMATIC) count
    first_fired_day: int | None
    first_disclosed_day: int | None
    infections_at_first_disclosure: int | None  # cumulative ever-infected on that day
    finest_disclosed_level: ScopeLevel | None  # deepest level named anywhere in the run

    @property
    def policy_cost(self) -> int | None:
        if self.first_fired_day is None or self.first_disclosed_day is None:
            return None
        return self.first_disclosed_day - self.first_fired_day


def _cumulative_infected(simulation: Simulation, day_index: int) -> int:
    snapshot = simulation.history[day_index]
    return sum(1 for a in snapshot.agents if a.state is not InfectionState.SUSCEPTIBLE)


def reduce_run(
    seed: int,
    simulation: Simulation,
    daily_records: list[DailyRecord],
    *,
    established_min_infections: int = ESTABLISHED_MIN_INFECTIONS,
) -> RunOutcome:
    """Collapse one simulated + analysed run into a :class:`RunOutcome`."""
    total_infections = _cumulative_infected(simulation, -1)
    peak_infected = max(
        s.count(InfectionState.INCUBATING) + s.count(InfectionState.SYMPTOMATIC)
        for s in simulation.history
    )

    last = daily_records[-1]
    fire_day = last.first_fired_day
    disclose_day = last.first_disclosed_day

    infections_at_disclosure = (
        _cumulative_infected(simulation, disclose_day) if disclose_day is not None else None
    )

    finest_level: ScopeLevel | None = None
    for record in daily_records:
        if record.disclosed_scope_id is None:
            continue
        level = simulation.registry.get(record.disclosed_scope_id).level
        finest_level = level if finest_level is None else max(finest_level, level)

    return RunOutcome(
        seed=seed,
        established=total_infections >= established_min_infections,
        total_infections=total_infections,
        peak_infected=peak_infected,
        first_fired_day=fire_day,
        first_disclosed_day=disclose_day,
        infections_at_first_disclosure=infections_at_disclosure,
        finest_disclosed_level=finest_level,
    )


def run_once(
    seed: int,
    *,
    days: int = DEFAULT_RUN_DAYS,
    detection_config=DEFAULT_DETECTION_CONFIG,
    disclosure_config: DisclosureConfig = DEFAULT_DISCLOSURE_CONFIG,
    established_min_infections: int = ESTABLISHED_MIN_INFECTIONS,
) -> RunOutcome:
    """Run one seed end to end (convenience wrapper over the pipeline)."""
    run = run_with_detection(
        seed=seed,
        days=days,
        detection_config=detection_config,
        disclosure_config=disclosure_config,
    )
    return reduce_run(
        seed,
        run.simulation,
        run.daily_records,
        established_min_infections=established_min_infections,
    )


# ---------------------------------------------------------------------------
# Aggregation for one sweep setting
# ---------------------------------------------------------------------------


def _mean(values: list[float]) -> float | None:
    return mean(values) if values else None


@dataclass(frozen=True)
class SettingSummary:
    """Aggregate statistics for one value of one swept disclosure parameter.

    ``mean_*`` fields are over ESTABLISHED runs only (the disclosure-timing
    ones additionally only over established runs that actually disclosed).
    ``false_alarm_rate`` is over NON-established runs only.
    """

    param_name: str
    value: float

    n_runs: int
    n_established: int
    n_non_established: int
    n_fired: int  # established runs that ever fired  (detection-only; constant per sweep)
    n_disclosed: int  # established runs that ever disclosed  (varies with the parameter)

    mean_total_infections: float | None  # day-30 cumulative; detection/disclosure-independent

    # All four over the SAME subset: established runs that disclosed.
    mean_fire_delay: float | None
    mean_disclosure_delay: float | None
    mean_gap: float | None  # disclosure_delay - fire_delay  == mean policy cost
    mean_infections_at_disclosure: float | None  # CONDITIONAL on disclosure (survivorship)

    # Over ALL established runs, disclosed or not: infections that were
    # never disclosed before the run ended. A run that disclosed
    # contributes its infection count at first disclosure; a run that never
    # disclosed contributes its full day-30 total (none of its infections
    # were ever disclosed). This is the unbiased companion to
    # ``mean_infections_at_disclosure``.
    mean_infections_before_disclosure_unbiased: float | None
    disclosed_fraction: float | None  # n_disclosed / n_established -- the selection made visible

    finest_disclosed_level: ScopeLevel | None

    n_false_alarms: int
    false_alarm_rate: float | None

    # A structurally impossible configuration (see degenerate_reason_for):
    # no scope can pass both gates at any count. Not a data point.
    degenerate: bool = False
    degenerate_reason: str = ""

    def regime_key(self) -> tuple:
        """The disclosure-dependent outcome, for spotting duplicate regimes
        (adjacent settings the integer arithmetic did not separate)."""
        return (
            self.n_disclosed,
            self.mean_disclosure_delay,
            self.mean_gap,
            self.mean_infections_at_disclosure,
            self.finest_disclosed_level,
        )


def summarize_setting(
    outcomes: list[RunOutcome],
    *,
    param_name: str,
    value: float,
    degenerate: bool = False,
    degenerate_reason: str = "",
) -> SettingSummary:
    established = [o for o in outcomes if o.established]
    non_established = [o for o in outcomes if not o.established]

    fired = [o for o in established if o.first_fired_day is not None]
    disclosed = [o for o in established if o.first_disclosed_day is not None]
    false_alarms = [o for o in non_established if o.first_fired_day is not None]

    # Unbiased: every established run contributes, a non-disclosing one at
    # its full day-30 total (none of its infections were ever disclosed).
    infections_before_disclosure = [
        o.infections_at_first_disclosure
        if o.first_disclosed_day is not None
        else o.total_infections
        for o in established
    ]

    finest: ScopeLevel | None = None
    for o in disclosed:
        if o.finest_disclosed_level is not None:
            finest = (
                o.finest_disclosed_level
                if finest is None
                else max(finest, o.finest_disclosed_level)
            )

    return SettingSummary(
        param_name=param_name,
        value=value,
        n_runs=len(outcomes),
        n_established=len(established),
        n_non_established=len(non_established),
        n_fired=len(fired),
        n_disclosed=len(disclosed),
        mean_total_infections=_mean([o.total_infections for o in established]),
        mean_fire_delay=_mean([o.first_fired_day for o in disclosed]),
        mean_disclosure_delay=_mean([o.first_disclosed_day for o in disclosed]),
        mean_gap=_mean([o.policy_cost for o in disclosed]),
        mean_infections_at_disclosure=_mean(
            [o.infections_at_first_disclosure for o in disclosed]
        ),
        mean_infections_before_disclosure_unbiased=_mean(infections_before_disclosure),
        disclosed_fraction=(len(disclosed) / len(established)) if established else None,
        finest_disclosed_level=finest,
        n_false_alarms=len(false_alarms),
        false_alarm_rate=(len(false_alarms) / len(non_established)) if non_established else None,
        degenerate=degenerate,
        degenerate_reason=degenerate_reason,
    )


def fizzle_rate(outcomes: list[RunOutcome]) -> float:
    """Fraction of runs that never established. Independent of both engine
    configs -- reported once, not per row."""
    if not outcomes:
        return 0.0
    return 1 - sum(o.established for o in outcomes) / len(outcomes)


def false_alarm_rate_at_defaults(outcomes: list[RunOutcome]) -> tuple[int, int, float | None]:
    """(n_false_alarms, n_non_established, rate) over a baseline (default
    config) outcome set. Detection is fixed for every sweep, so this
    single number is the false-alarm rate everywhere below."""
    non_established = [o for o in outcomes if not o.established]
    alarms = [o for o in non_established if o.first_fired_day is not None]
    rate = (len(alarms) / len(non_established)) if non_established else None
    return len(alarms), len(non_established), rate


def overall_mean_fire_delay(outcomes: list[RunOutcome]) -> float | None:
    """Mean fire delay over ALL established runs that fired (not just the
    ones that went on to disclose). The detection-side control value."""
    return _mean(
        [o.first_fired_day for o in outcomes if o.established and o.first_fired_day is not None]
    )


def adjacent_duplicate_rows(summaries: list[SettingSummary]) -> list[tuple[float, float]]:
    """Pairs of adjacent setting values whose disclosure-dependent outcome
    is identical -- the range is too fine for the integer arithmetic
    underneath at that point."""
    dupes: list[tuple[float, float]] = []
    for earlier, later in zip(summaries, summaries[1:]):
        # Degenerate rows are labelled IMPOSSIBLE in the output, not
        # compared as data -- two of them side by side is not a
        # duplicate-regime problem.
        if earlier.degenerate or later.degenerate:
            continue
        if earlier.regime_key() == later.regime_key():
            dupes.append((earlier.value, later.value))
    return dupes


# ---------------------------------------------------------------------------
# The three sweeps
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DisclosureSweep:
    param_name: str
    default_value: float  # the shipped default, for context in the output
    values: tuple
    config_for: Callable[[float], DisclosureConfig]
    note: str = ""


DISCLOSURE_SWEEPS: tuple[DisclosureSweep, ...] = (
    DisclosureSweep(
        "MIN_SCOPE_POPULATION",
        20,
        MIN_SCOPE_POPULATION_SWEEP,
        lambda v: DisclosureConfig(min_scope_population=int(v)),
        note="privacy gate n >= this; scope populations are 25 / 75 / 150.",
    ),
    DisclosureSweep(
        "STATISTICAL_GATE_FLOOR",
        5,
        STATISTICAL_GATE_FLOOR_SWEEP,
        lambda v: DisclosureConfig(statistical_gate_floor=int(v)),
        note="statistical gate qualifying >= max(this, ceil(sqrt(n))); ceil(sqrt) is 5 / 9 / 13.",
    ),
    DisclosureSweep(
        "MAX_REPORT_FRACTION",
        0.5,
        MAX_REPORT_FRACTION_SWEEP,
        lambda v: DisclosureConfig(max_report_fraction=float(v)),
        note=(
            "privacy gate qualifying/n <= this. The shipped default (0.5) lands in "
            "the SAME regime as 0.25 and is not shown: suite report fractions never "
            "approach it, so it never binds. It only bites below ~0.2."
        ),
    ),
)


@dataclass
class SweepResults:
    fizzle_rate: float
    false_alarms: int
    non_established: int
    false_alarm_rate: float | None
    control_fire_delay: float | None  # mean fire delay, all established fired runs
    n_established: int
    n_fired: int
    mean_total_infections: float | None
    sweeps: dict[str, list[SettingSummary]]


def run_disclosure_sweeps(
    seeds: Sequence[int] | None = None,
    *,
    n_seeds: int = DEFAULT_EXPERIMENT_SEEDS,
    days: int = DEFAULT_RUN_DAYS,
    sweeps: Sequence[DisclosureSweep] = DISCLOSURE_SWEEPS,
) -> SweepResults:
    """Simulate every seed ONCE, then replay the analysis for every value
    of every disclosure sweep on that shared report stream."""
    seed_list = list(seeds) if seeds is not None else list(range(1, n_seeds + 1))
    simulated: dict[int, SimulatedReports] = {
        seed: simulate_and_report(seed=seed, days=days) for seed in seed_list
    }

    sample_registry = next(iter(simulated.values())).simulation.registry
    scope_populations = tuple(
        sorted({s.population for s in sample_registry.scopes.values()})
    )

    def outcomes_for(disclosure_config: DisclosureConfig) -> list[RunOutcome]:
        return [
            reduce_run(
                seed,
                sr.simulation,
                analyze_report_stream(sr, disclosure_config=disclosure_config),
            )
            for seed, sr in simulated.items()
        ]

    baseline = outcomes_for(DEFAULT_DISCLOSURE_CONFIG)
    alarms, non_est, alarm_rate = false_alarm_rate_at_defaults(baseline)

    sweep_summaries: dict[str, list[SettingSummary]] = {}
    for sweep in sweeps:
        rows: list[SettingSummary] = []
        for value in sweep.values:
            disclosure_config = sweep.config_for(value)
            reason = degenerate_reason_for(disclosure_config, scope_populations)
            rows.append(
                summarize_setting(
                    outcomes_for(disclosure_config),
                    param_name=sweep.param_name,
                    value=value,
                    degenerate=reason is not None,
                    degenerate_reason=reason or "",
                )
            )
        sweep_summaries[sweep.param_name] = rows

    return SweepResults(
        fizzle_rate=fizzle_rate(baseline),
        false_alarms=alarms,
        non_established=non_est,
        false_alarm_rate=alarm_rate,
        control_fire_delay=overall_mean_fire_delay(baseline),
        n_established=sum(o.established for o in baseline),
        n_fired=sum(
            1 for o in baseline if o.established and o.first_fired_day is not None
        ),
        mean_total_infections=_mean(
            [o.total_infections for o in baseline if o.established]
        ),
        sweeps=sweep_summaries,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _fmt(value: float | None, decimals: int = 1) -> str:
    return "n/a" if value is None else f"{value:.{decimals}f}"


def _level_name(level: ScopeLevel | None) -> str:
    return "none" if level is None else level.name


def _print_sweep(sweep: DisclosureSweep, summaries: list[SettingSummary]) -> None:
    print(f"--- Sweep: {sweep.param_name} (default {sweep.default_value:g}; detection fixed) ---")
    if sweep.note:
        print(f"    {sweep.note}")

    columns = [
        ("value", 7),
        ("disc_frac", 9),
        ("inf<disc", 9),
        ("inf@disc", 9),
        ("disc_delay", 10),
        ("fire_delay", 10),
        ("gap", 6),
        ("finest_lvl", 10),
    ]
    header = "  ".join(f"{name:>{width}}" for name, width in columns)
    print(header)
    print("-" * len(header))
    for s in summaries:
        if s.degenerate:
            print(f"{s.value:>7g}  IMPOSSIBLE -- {s.degenerate_reason}")
            continue
        frac = (
            "n/a"
            if s.disclosed_fraction is None
            else f"{s.n_disclosed}/{s.n_established}"
        )
        row = [
            f"{s.value:g}",
            frac,
            _fmt(s.mean_infections_before_disclosure_unbiased),
            _fmt(s.mean_infections_at_disclosure),
            _fmt(s.mean_disclosure_delay),
            _fmt(s.mean_fire_delay),
            _fmt(s.mean_gap),
            _level_name(s.finest_disclosed_level),
        ]
        print("  ".join(f"{value:>{width}}" for value, (_, width) in zip(row, columns)))

    dupes = adjacent_duplicate_rows(summaries)
    if dupes:
        pairs = ", ".join(f"{a:g}<->{b:g}" for a, b in dupes)
        print(
            f"    NOTE: adjacent settings produced identical rows ({pairs}). "
            f"{sweep.param_name} acts on integer counts; these values did not "
            f"cross a discrete boundary between them."
        )
    print()


def main() -> None:
    results = run_disclosure_sweeps()
    n_seeds = next(iter(results.sweeps.values()))[0].n_runs
    bar = "=" * 78

    print(bar)
    print(f"{n_seeds} seeds, {DEFAULT_RUN_DAYS}-day runs, default structure, DETECTION FIXED AT DEFAULTS")
    print(f"established = cumulative infections >= {ESTABLISHED_MIN_INFECTIONS} (ESTABLISHED_MIN_INFECTIONS)")
    print(bar)
    print()
    print(f"  FIZZLE RATE (outbreak never established) :  {results.fizzle_rate * 100:.1f}%   "
          f"({results.non_established}/{n_seeds} runs)")
    print()
    fa = "n/a" if results.false_alarm_rate is None else f"{results.false_alarm_rate * 100:.1f}%"
    print(f"  >>> FALSE-ALARM RATE at shipped defaults :  {fa}   "
          f"({results.false_alarms}/{results.non_established} non-established runs fired anyway) <<<")
    print(f"      This is a real weakness of the shipped detector, not a footnote.")
    print(f"      With the default ABSOLUTE_EXCESS_RATIO, three in five outbreaks that")
    print(f"      never established still trip the detector. Sweeping the DISCLOSURE")
    print(f"      gates below cannot touch it -- it is a detection-side cost, and it is")
    print(f"      the same number under every disclosure setting.")
    print()
    print(f"  established runs                  : {results.n_established} of {n_seeds}")
    print(f"  ...of which the detector fired    : {results.n_fired}")
    print(f"  mean day-30 cumulative infections : {_fmt(results.mean_total_infections)}  "
          f"(disclosure-independent by construction -- this is why day-30")
    print(f"                                      totals cannot be the outcome axis)")
    print(f"  CONTROL mean fire delay          :  {_fmt(results.control_fire_delay)} days  "
          f"(all established runs that fired)")
    print()
    print("  Column key for the sweep tables:")
    print("    disc_frac  established runs that ever disclosed / all established runs")
    print("               (the selection: shrinks as the gate tightens)")
    print("    inf<disc   UNBIASED. Mean, over ALL established runs, of infections never")
    print("               disclosed before the run ended: a run that disclosed contributes")
    print("               its count at first disclosure, a run that never disclosed")
    print("               contributes its full day-30 total.")
    print("    inf@disc   CONDITIONAL on disclosure. Mean infections at first disclosure")
    print("               over only the runs that disclosed -- under a tight gate those are")
    print("               systematically the largest outbreaks, so this understates the cost.")
    print("    disc_delay mean days to first disclosure   } over the same subset:")
    print("    fire_delay mean days to first fire          } established runs that disclosed")
    print("    gap        disc_delay - fire_delay, the privacy-policy window (== mean policy cost)")
    print("    finest_lvl finest scope level ever disclosed at this setting")
    print("    a row marked IMPOSSIBLE is a structurally degenerate configuration, not data.")
    print()
    print("  gap alone is ambiguous (it shrinks if disclosure speeds up OR detection slows)")
    print("  -- but detection is fixed here, so fire_delay is flat and every move in gap is")
    print("  disclosure timing. Read disc_delay and fire_delay together, never gap alone.")
    print()

    sweeps_by_name = {s.param_name: s for s in DISCLOSURE_SWEEPS}
    for param_name, summaries in results.sweeps.items():
        _print_sweep(sweeps_by_name[param_name], summaries)


if __name__ == "__main__":
    main()
