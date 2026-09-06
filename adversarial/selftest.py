"""Run the adversarial self-test across many seeds and summarise."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, median
from typing import Sequence

from simulation.config import DEFAULT_RUN_DAYS
from simulation.pipeline import analyze_report_stream, simulate_and_report

from .differencing import attack
from .observer import observe
from .wandering import measure_wandering

DEFAULT_SEEDS = 200


@dataclass(frozen=True)
class SelfTestSummary:
    n_runs: int
    days: int

    same_scope_pairs: int
    exact_one_person_pinned: int
    band_one_person_pinned: int
    exact_direction_known: int
    band_direction_known: int
    band_median_possible_values: float
    band_residual: str

    wandering_on_mean: float
    wandering_off_mean: float
    wandering_on_max: int
    wandering_off_max: int


def run_self_test(
    seeds: Sequence[int] | None = None,
    *,
    n_seeds: int = DEFAULT_SEEDS,
    days: int = DEFAULT_RUN_DAYS,
) -> SelfTestSummary:
    seed_list = list(seeds) if seeds is not None else list(range(1, n_seeds + 1))

    pairs = 0
    exact_pins = band_pins = 0
    exact_dir = band_dir = 0
    band_spans: list[float] = []
    band_residual = "no consecutive same-scope disclosures in any run"
    wander_on: list[int] = []
    wander_off: list[int] = []

    for seed in seed_list:
        simulated = simulate_and_report(seed=seed, days=days)
        records = analyze_report_stream(simulated)

        exact = attack(observe(records, leak_exact_counts=True), mode="exact")
        band = attack(observe(records, leak_exact_counts=False), mode="band")

        pairs += exact.same_scope_pairs
        exact_pins += exact.one_person_pinned
        band_pins += band.one_person_pinned
        exact_dir += exact.direction_known
        band_dir += band.direction_known
        if band.same_scope_pairs and band.median_possible_values != float("inf"):
            band_spans.append(band.median_possible_values)
            band_residual = band.residual

        w = measure_wandering(simulated)
        wander_on.append(w.stability_on)
        wander_off.append(w.stability_off)

    return SelfTestSummary(
        n_runs=len(seed_list),
        days=days,
        same_scope_pairs=pairs,
        exact_one_person_pinned=exact_pins,
        band_one_person_pinned=band_pins,
        exact_direction_known=exact_dir,
        band_direction_known=band_dir,
        band_median_possible_values=median(band_spans) if band_spans else float("inf"),
        band_residual=band_residual,
        wandering_on_mean=mean(wander_on) if wander_on else 0.0,
        wandering_off_mean=mean(wander_off) if wander_off else 0.0,
        wandering_on_max=max(wander_on) if wander_on else 0,
        wandering_off_max=max(wander_off) if wander_off else 0,
    )


def format_summary(s: SelfTestSummary) -> str:
    lines = [
        "=" * 78,
        f"ADVERSARIAL SELF-TEST   ({s.n_runs} runs, {s.days}-day)",
        "observer sees only: the disclosed scope, and its report count as the UI shows it",
        "=" * 78,
        "",
        "DIFFERENCING ATTACK",
        f"  consecutive same-scope disclosures            : {s.same_scope_pairs} day-pairs",
        "",
        f"  >>> pre-band (EXACT counts) one-person pins   : {s.exact_one_person_pinned}",
        f"  >>> shipped  (BANDS)        one-person pins   : {s.band_one_person_pinned}",
        "",
        f"  exact  : overnight change forced to a known sign on {s.exact_direction_known}/{s.same_scope_pairs} pairs",
        f"  bands  : overnight change forced to a known sign on {s.band_direction_known}/{s.same_scope_pairs} pairs",
        f"  bands  : residual per pair -- {s.band_residual}",
        f"           median count of still-possible overnight deltas : "
        f"{_fmt(s.band_median_possible_values)}",
        "",
        "SCOPE WANDERING   (distinct groups named across a run)",
        f"  scope stability ON   : mean {s.wandering_on_mean:.2f}   max {s.wandering_on_max}",
        f"  scope stability OFF  : mean {s.wandering_off_mean:.2f}   max {s.wandering_off_max}",
        "",
        "HONEST READ",
        "  Bands remove the one-person differencing pin entirely. They do NOT make the",
        "  observer learn nothing: the named group is still named, its activity is still",
        "  bracketed to a band, and on many pairs the direction of change is still forced.",
        "  Scope stability shrinks the set of groups ever named but does not hide the",
        "  lineage the disclosure walks. This is leakage reduced, not leakage removed.",
    ]
    return "\n".join(lines)


def _fmt(value: float) -> str:
    return "unbounded" if value == float("inf") else f"{value:.0f}"


def main() -> None:
    print(format_summary(run_self_test()))


if __name__ == "__main__":
    main()
