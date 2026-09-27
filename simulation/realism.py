"""Reporting-realism stress test.

The shipped reporting model is deliberately clean: each agent gets one fixed
probability (uniform 0.3 to 0.7), applied independently each symptomatic
day, with no memory and no feedback. Every committed result depends on it.
This module is an ALTERNATIVE, selected with
``SimulationConfig(reporting_model="realistic")``, that breaks those three
assumptions on purpose:

  * HETEROGENEITY. Baselines come from Beta(0.5, 0.5) instead of
    uniform(0.3, 0.7). Same mean (0.5), very different spread: about a third
    of agents almost never report and about a third almost always do.
  * CORRELATION. A person's probability rises after suite-mates report (the
    "everyone else is filing, so will I" effect, and worried-well filers).
    p' = 1 - (1 - p) ** (1 + gain * r), r = reports from the agent's own
    suite in the previous few days. It applies to background reports too.
  * STIGMA. Once a scope has been NAMED in a disclosure, its members report
    less (p' = p * stigma_factor) for as long as it stays named plus a
    tail. This needs a feedback loop the clean model does not have: today's
    reports depend on yesterday's disclosure, so this runner interleaves
    generation with the same daily analysis step the batch pipeline uses
    (``pipeline.StreamAnalyzer``).

The epidemic itself is untouched and, for a given seed, IDENTICAL under both
models (the simulation RNG stream never sees reporting), so every
comparison below is paired: same outbreak, different reporting behaviour.

Every constant is CHOSEN, not measured -- like the clean model it stands in
for. This tests how much the detector depends on the clean assumption; it
does not claim to describe how real residents behave.

    python -m simulation.realism
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from datetime import timedelta
from statistics import mean
from typing import Sequence

from microcluster.config import (
    DEFAULT_DETECTION_CONFIG,
    DEFAULT_DISCLOSURE_CONFIG,
    DetectionConfig,
    DisclosureConfig,
)
from microcluster.models import CHECKLIST, Onset, Report, ScopeRegistry

from .agent import Agent
from .config import (
    DEFAULT_RUN_DAYS,
    DEFAULT_SIMULATION_CONFIG,
    REPORTING_MODEL_REALISTIC,
    SimulationConfig,
)
from .experiments import RunOutcome, reduce_run, summarize_setting
from .infection import InfectionState
from .pipeline import SimulationRun, StreamAnalyzer, run_with_detection
from .population import StructureSpec
from .reporting import _non_outbreak_categories, _onset_for
from .simulator import Simulation

__all__ = [
    "RealismConfig",
    "VARIANTS",
    "run_realistic",
    "run_realism_sweep",
]


@dataclass(frozen=True)
class RealismConfig:
    """Which realism effects are on, and how strong. All CHOSEN figures."""

    heterogeneity: bool = True
    correlation: bool = True
    stigma: bool = True

    # Beta(a, b) per-agent baseline. a = b = 0.5 keeps the clean model's
    # mean of 0.5 but makes it bimodal (U-shaped).
    baseline_beta_a: float = 0.5
    baseline_beta_b: float = 0.5

    # p' = 1 - (1 - p) ** (1 + gain * r); r counts reports from the agent's
    # own suite in the previous ``correlation_window_days`` days, capped.
    correlation_gain: float = 0.5
    correlation_window_days: int = 3
    correlation_max_reports: int = 4

    # Inside a scope that has been named: p' = p * stigma_factor, for as
    # long as it stays named and ``stigma_days`` after it was last named.
    stigma_factor: float = 0.5
    stigma_days: int = 7


DEFAULT_REALISM_CONFIG = RealismConfig()

# The full model and each effect alone, for attribution.
VARIANTS: dict[str, RealismConfig | None] = {
    "clean (shipped)": None,
    "realistic (all three)": DEFAULT_REALISM_CONFIG,
    "heterogeneity only": RealismConfig(heterogeneity=True, correlation=False, stigma=False),
    "correlation only": RealismConfig(heterogeneity=False, correlation=True, stigma=False),
    "stigma only": RealismConfig(heterogeneity=False, correlation=False, stigma=True),
}


class _State:
    """What the generator remembers between days."""

    def __init__(self, registry: ScopeRegistry, realism: RealismConfig) -> None:
        self.realism = realism
        self._lineage: dict[str, tuple[str, ...]] = {}
        self._registry = registry
        self.suite_reports_by_day: dict[str, dict[int, int]] = {}
        self.named_until: dict[str, int] = {}

    def lineage(self, suite_id: str) -> tuple[str, ...]:
        got = self._lineage.get(suite_id)
        if got is None:
            got = tuple(s.id for s in self._registry.chain_to_root(suite_id))
            self._lineage[suite_id] = got
        return got

    def recent_suite_reports(self, suite_id: str, day: int) -> int:
        by_day = self.suite_reports_by_day.get(suite_id)
        if not by_day:
            return 0
        window = self.realism.correlation_window_days
        total = sum(by_day.get(d, 0) for d in range(day - window, day))
        return min(total, self.realism.correlation_max_reports)

    def note_reports(self, day: int, reports: Sequence[Report]) -> None:
        for r in reports:
            d = self.suite_reports_by_day.setdefault(r.location_id, {})
            d[day] = d.get(day, 0) + 1

    def note_disclosed(self, day: int, scope_id: str | None) -> None:
        if scope_id is not None:
            self.named_until[scope_id] = day + self.realism.stigma_days

    def suppressed(self, suite_id: str, day: int) -> bool:
        return any(self.named_until.get(s, -1) >= day for s in self.lineage(suite_id))


def _effective(p: float, suite_id: str, day: int, state: _State) -> float:
    rc = state.realism
    if rc.correlation:
        r = state.recent_suite_reports(suite_id, day)
        if r:
            p = 1.0 - (1.0 - p) ** (1.0 + rc.correlation_gain * r)
    if rc.stigma and state.suppressed(suite_id, day):
        p *= rc.stigma_factor
    return p


def _generate_daily_reports(
    agents: list[Agent],
    day: int,
    rng: random.Random,
    config: SimulationConfig,
    state: _State,
) -> list[Report]:
    """Same structure as ``reporting.generate_daily_reports`` (same
    categories, same one-outbreak-report-per-episode rule, same suite-only
    location); only the probabilities differ."""
    submitted_at = config.simulation_start + timedelta(days=day)
    noise_categories = _non_outbreak_categories(config.outbreak_category)
    reports: list[Report] = []
    for agent in agents:
        if agent.state is InfectionState.SYMPTOMATIC:
            if agent.has_reported:
                continue
            p = _effective(agent.reporting_probability, agent.suite_id, day, state)
            if rng.random() < p:
                symptom = rng.choice(CHECKLIST[config.outbreak_category])
                reports.append(
                    Report(
                        category=config.outbreak_category,
                        symptom=symptom,
                        onset=_onset_for(day - agent.state_changed_day),
                        location_id=agent.suite_id,
                        submitted_at=submitted_at,
                    )
                )
                agent.has_reported = True
            continue
        noise = _effective(config.background_noise_daily_rate, agent.suite_id, day, state)
        if rng.random() < noise:
            category = rng.choice(noise_categories)
            reports.append(
                Report(
                    category=category,
                    symptom=rng.choice(CHECKLIST[category]),
                    onset=rng.choice(list(Onset)),
                    location_id=agent.suite_id,
                    submitted_at=submitted_at,
                )
            )
    return reports


def run_realistic(
    *,
    seed: int,
    days: int,
    spec: StructureSpec | None = None,
    config: SimulationConfig = DEFAULT_SIMULATION_CONFIG,
    seed_infections: int | None = None,
    detection_config: DetectionConfig = DEFAULT_DETECTION_CONFIG,
    disclosure_config: DisclosureConfig = DEFAULT_DISCLOSURE_CONFIG,
    realism: RealismConfig = DEFAULT_REALISM_CONFIG,
) -> SimulationRun:
    """Simulate + report + analyse one run under the realistic model."""
    sim = Simulation(seed=seed, spec=spec, config=config, seed_infections=seed_infections)
    if realism.heterogeneity:
        # own stream: never perturbs the epidemic's RNG
        baseline_rng = random.Random(f"realism-baseline-{seed}")
        for agent in sim.agents:
            agent.reporting_probability = baseline_rng.betavariate(
                realism.baseline_beta_a, realism.baseline_beta_b
            )
    rng = random.Random(f"reporting-{seed}")
    state = _State(sim.registry, realism)
    analyzer = StreamAnalyzer(
        sim, config, detection_config=detection_config, disclosure_config=disclosure_config
    )

    all_reports: list[Report] = []
    records = []
    for day in range(days + 1):
        if day > 0:
            sim.step()
        todays = _generate_daily_reports(sim.agents, day, rng, config, state)
        state.note_reports(day, todays)
        all_reports.extend(todays)
        record = analyzer.step(day, todays)
        state.note_disclosed(day, record.disclosed_scope_id)
        records.append(record)
    return SimulationRun(simulation=sim, reports=all_reports, daily_records=records)


# ---------------------------------------------------------------------------
# The paired sweep
# ---------------------------------------------------------------------------


def _continuity(records) -> float | None:
    """Of the days from first disclosure to the end of the run, the share on
    which something was still being disclosed."""
    first = records[-1].first_disclosed_day
    if first is None:
        return None
    tail = records[first:]
    return sum(1 for r in tail if r.disclosed_scope_id is not None) / len(tail)


def run_realism_sweep(
    seeds: Sequence[int] | None = None,
    *,
    days: int = DEFAULT_RUN_DAYS,
    spec: StructureSpec | None = None,
) -> dict[str, dict]:
    seed_list = list(seeds) if seeds is not None else list(range(1, 501))
    out: dict[str, dict] = {}
    for name, realism in VARIANTS.items():
        outcomes: list[RunOutcome] = []
        continuity: list[float] = []
        reports_total: list[int] = []
        for seed in seed_list:
            if realism is None:
                run = run_with_detection(seed=seed, days=days, spec=spec)
            else:
                run = run_realistic(
                    seed=seed,
                    days=days,
                    spec=spec,
                    config=replace(DEFAULT_SIMULATION_CONFIG, reporting_model=REPORTING_MODEL_REALISTIC),
                    realism=realism,
                )
            outcome = reduce_run(seed, run.simulation, run.daily_records)
            outcomes.append(outcome)
            reports_total.append(len(run.reports))
            if outcome.established:
                c = _continuity(run.daily_records)
                if c is not None:
                    continuity.append(c)
        s = summarize_setting(outcomes, param_name="reporting_model", value=0)
        non_est = [o for o in outcomes if not o.established]
        false_disclosures = [o for o in non_est if o.first_disclosed_day is not None]
        out[name] = {
            "n_runs": s.n_runs,
            "n_established": s.n_established,
            "n_disclosed": s.n_disclosed,
            "disclosed_fraction": s.disclosed_fraction,
            "fire_delay": s.mean_fire_delay,
            "disclosure_delay": s.mean_disclosure_delay,
            "gap": s.mean_gap,
            "infections_before_disclosure": s.mean_infections_before_disclosure_unbiased,
            "false_alarm_rate": s.false_alarm_rate,
            "false_disclosure_rate": (len(false_disclosures) / len(non_est)) if non_est else None,
            "disclosure_continuity": mean(continuity) if continuity else None,
            "mean_reports_per_run": mean(reports_total),
            "finest_level": s.finest_disclosed_level.name if s.finest_disclosed_level else None,
        }
    return out


GRID_BETA = (None, 2.0, 0.5, 0.25)        # None = the clean uniform(0.3, 0.7) baseline
GRID_GAIN = (0.0, 0.25, 0.5, 1.0)         # correlation strength; 0 = none


def run_sensitivity_grid(
    seeds: Sequence[int] | None = None, *, days: int = DEFAULT_RUN_DAYS
) -> list[dict]:
    """Heterogeneity x correlation grid (stigma on throughout). The full
    model above is one cell. Its point: the timing metrics can look robust
    only because opposing effects cancel, so show how far they move when the
    strengths are changed."""
    seed_list = list(seeds) if seeds is not None else list(range(1, 501))
    cfg = replace(DEFAULT_SIMULATION_CONFIG, reporting_model=REPORTING_MODEL_REALISTIC)
    rows: list[dict] = []
    for beta in GRID_BETA:
        for gain in GRID_GAIN:
            realism = RealismConfig(
                heterogeneity=beta is not None,
                correlation=gain > 0,
                stigma=True,
                baseline_beta_a=beta or 0.5,
                baseline_beta_b=beta or 0.5,
                correlation_gain=gain,
            )
            outcomes = []
            for seed in seed_list:
                run = run_realistic(seed=seed, days=days, config=cfg, realism=realism)
                outcomes.append(reduce_run(seed, run.simulation, run.daily_records))
            s = summarize_setting(outcomes, param_name="grid", value=0)
            non_est = [o for o in outcomes if not o.established]
            rows.append(
                {
                    "beta": beta,
                    "correlation_gain": gain,
                    "disclosure_delay": s.mean_disclosure_delay,
                    "infections_before_disclosure": s.mean_infections_before_disclosure_unbiased,
                    "false_alarm_rate": s.false_alarm_rate,
                    "false_disclosure_rate": (
                        sum(1 for o in non_est if o.first_disclosed_day is not None) / len(non_est)
                        if non_est else None
                    ),
                }
            )
    return rows


def _f(v, d=2, pct=False):
    if v is None:
        return "n/a"
    return f"{v * 100:.0f}%" if pct else f"{v:.{d}f}"


def format_sweep(results: dict[str, dict]) -> str:
    head = (
        f"{'model':<24}{'fire d':>8}{'disc d':>8}{'gap':>7}{'inf<disc':>10}"
        f"{'discl%':>8}{'false-alarm':>13}{'false-disc':>12}{'continuity':>12}{'reports':>9}"
    )
    lines = ["REPORTING-REALISM STRESS TEST (paired: same outbreaks, different reporting)", "", head]
    for name, r in results.items():
        lines.append(
            f"{name:<24}{_f(r['fire_delay'],1):>8}{_f(r['disclosure_delay'],1):>8}{_f(r['gap'],1):>7}"
            f"{_f(r['infections_before_disclosure'],1):>10}{_f(r['disclosed_fraction'],pct=True):>8}"
            f"{_f(r['false_alarm_rate'],pct=True):>13}{_f(r['false_disclosure_rate'],pct=True):>12}"
            f"{_f(r['disclosure_continuity'],pct=True):>12}{_f(r['mean_reports_per_run'],0):>9}"
        )
    return "\n".join(lines)


def main() -> None:
    print(format_sweep(run_realism_sweep()))


if __name__ == "__main__":
    main()
