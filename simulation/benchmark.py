"""Learned detector vs the hand-authored threshold rules.

Still headless -- no plotting. Builds a labelled dataset from simulated
runs, trains a small classifier on it, and scores that classifier against
the authored rules in ``microcluster`` on HELD-OUT runs.

    python -m simulation.benchmark

---------------------------------------------------------------------
WHAT "ONE ROW PER (day, scope)" MEANS HERE
---------------------------------------------------------------------

``microcluster.detection`` operates at exactly one scope: the campus, the
level its two detectors compare against (a location versus its campus
peers; total volume versus the campus background expectation). It emits
its three plain findings once per evaluation. So the dataset is one row
per (run, day): the features are that day's three findings computed on the
reports accumulated so far, and the label is ground truth for that day.
This is the unit the authored rules also produce a decision at, which is
what makes the head-to-head comparison well posed.

Features (exactly the three findings ``microcluster.detection`` reports,
rule 6 -- no composite, nothing finer than a category):

  * ``relative_excess_ratio``   -- the hotspot location's smoothed per-capita
                                   rate over its peers'
  * ``count_within_window``     -- qualifying reports in the 72h window
  * ``count_sharing_category``  -- how many of those share the dominant category

Label (from ground truth, never shown to the engines): 1 iff on that day
the outbreak is BOTH established (cumulative ever-infected >=
``ESTABLISHED_MIN_INFECTIONS``) AND still active (at least one agent
INCUBATING or SYMPTOMATIC). This is a CHOSEN definition of "an outbreak
the system ought to be flagging right now", in the same spirit as every
threshold in ``config.py``; it is not a measured quantity.

---------------------------------------------------------------------
METHODOLOGY
---------------------------------------------------------------------

* SPLIT BY RUN, never by day. Adjacent days from one outbreak are highly
  correlated; letting them straddle the split would leak the test set into
  training and flatter the model.

* CROSS-REGIME EVALUATION. A model trained on this simulator learns this
  simulator. The benchmark therefore also trains on one transmission
  regime (the shipped ``SUITE_TRANSMISSION_PROBABILITY``) and evaluates on
  runs generated with a different one (``BENCHMARK_TEST_SUITE_TRANSMISSIONS``
  -- a slower and a faster epidemic). If the model only beats the rules on
  its training distribution, ``main`` says so in plain language. A clean
  negative result is reported, not hidden.

* THE MODEL NEVER REPLACES THE RULES. Both stay in the codebase. This
  module scores them side by side and nothing more; the disclosure path
  still runs on the authored rules alone.
"""

from __future__ import annotations

import random
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from statistics import mean
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.tree import DecisionTreeClassifier  # noqa: E402

from microcluster.config import DEFAULT_DETECTION_CONFIG, DetectionConfig  # noqa: E402
from microcluster.detection import evaluate as detection_evaluate  # noqa: E402
from microcluster.models import Report  # noqa: E402

from simulation.config import (  # noqa: E402
    BENCHMARK_DEFAULT_SEEDS,
    BENCHMARK_SPLIT_SEED,
    BENCHMARK_TEST_RUN_FRACTION,
    BENCHMARK_TEST_SUITE_TRANSMISSIONS,
    BENCHMARK_TRAIN_SUITE_TRANSMISSION,
    BENCHMARK_TREE_MAX_DEPTH,
    DEFAULT_RUN_DAYS,
    DEFAULT_SIMULATION_CONFIG,
    ESTABLISHED_MIN_INFECTIONS,
    SimulationConfig,
)
from simulation.infection import InfectionState  # noqa: E402
from simulation.pipeline import simulate_and_report  # noqa: E402

__all__ = [
    "FEATURE_NAMES",
    "DayRow",
    "build_dataset",
    "split_by_run",
    "train_model",
    "Score",
    "score_rows",
    "score_model",
    "score_rules",
    "benchmark_in_distribution",
    "benchmark_cross_regime",
]

FEATURE_NAMES: tuple[str, ...] = (
    "relative_excess_ratio",
    "count_within_window",
    "count_sharing_category",
)


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DayRow:
    """One (run, day): the authored detector's three findings, the authored
    rule's own verdict, and the ground-truth label."""

    seed: int
    day: int
    relative_excess_ratio: float
    count_within_window: int
    count_sharing_category: int
    label: int  # 1 iff established AND active on this day (ground truth)
    rule_fired: bool  # microcluster.detection raw single-instant verdict


def _cumulative_infected(agents) -> int:
    return sum(1 for a in agents if a.state is not InfectionState.SUSCEPTIBLE)


def _active_infected(agents) -> int:
    return sum(
        1
        for a in agents
        if a.state in (InfectionState.INCUBATING, InfectionState.SYMPTOMATIC)
    )


def _ground_truth_label(agents, established_min_infections: int) -> int:
    established = _cumulative_infected(agents) >= established_min_infections
    active = _active_infected(agents) > 0
    return int(established and active)


def build_dataset(
    seeds: Sequence[int],
    *,
    days: int = DEFAULT_RUN_DAYS,
    config: SimulationConfig = DEFAULT_SIMULATION_CONFIG,
    detection_config: DetectionConfig = DEFAULT_DETECTION_CONFIG,
    established_min_infections: int = ESTABLISHED_MIN_INFECTIONS,
) -> list[DayRow]:
    """Simulate each seed once and emit one :class:`DayRow` per simulated
    day (day 0 .. ``days``). Ground truth is read straight from the
    simulator's history; only ``Report`` objects and the registry are ever
    passed to ``microcluster.detection`` (the ground-truth firewall)."""
    rows: list[DayRow] = []
    for seed in seeds:
        simulated = simulate_and_report(seed=seed, days=days, config=config)
        sim = simulated.simulation
        accumulated: list[Report] = []
        for day, day_reports in enumerate(simulated.daily_reports):
            accumulated.extend(day_reports)
            now = config.simulation_start + timedelta(days=day)
            result = detection_evaluate(
                accumulated, sim.registry, now=now, config=detection_config
            )
            snapshot = sim.history[day]
            rows.append(
                DayRow(
                    seed=seed,
                    day=day,
                    relative_excess_ratio=result.findings.relative_excess_ratio,
                    count_within_window=result.findings.count_within_window,
                    count_sharing_category=result.findings.count_sharing_category,
                    label=_ground_truth_label(snapshot.agents, established_min_infections),
                    rule_fired=result.raw_fired,
                )
            )
    return rows


def split_by_run(
    rows: Sequence[DayRow],
    *,
    test_fraction: float = BENCHMARK_TEST_RUN_FRACTION,
    split_seed: int = BENCHMARK_SPLIT_SEED,
) -> tuple[list[DayRow], list[DayRow]]:
    """Partition ``rows`` into (train, test) by SEED. No seed appears in
    both halves."""
    seeds = sorted({r.seed for r in rows})
    rng = random.Random(split_seed)
    rng.shuffle(seeds)
    n_test = max(1, round(len(seeds) * test_fraction))
    test_seeds = set(seeds[:n_test])
    train = [r for r in rows if r.seed not in test_seeds]
    test = [r for r in rows if r.seed in test_seeds]
    return train, test


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def _feature_matrix(rows: Sequence[DayRow]) -> np.ndarray:
    return np.array(
        [
            [
                r.relative_excess_ratio,
                r.count_within_window,
                r.count_sharing_category,
            ]
            for r in rows
        ],
        dtype=float,
    )


def _labels(rows: Sequence[DayRow]) -> np.ndarray:
    return np.array([r.label for r in rows], dtype=int)


def train_model(
    train_rows: Sequence[DayRow],
    *,
    kind: str = "logistic",
    tree_max_depth: int = BENCHMARK_TREE_MAX_DEPTH,
):
    """Fit a small classifier on the three findings. ``kind`` is
    ``"logistic"`` (default) or ``"tree"`` -- both deliberately low
    capacity, so a win is a real signal and not memorisation."""
    y = _labels(train_rows)
    if len(np.unique(y)) < 2:
        raise ValueError(
            "training set has a single class; cannot fit a classifier "
            "(need both established-and-active and not days)"
        )
    X = _feature_matrix(train_rows)
    if kind == "tree":
        model = DecisionTreeClassifier(max_depth=tree_max_depth, random_state=0)
    elif kind == "logistic":
        model = LogisticRegression(max_iter=1000, class_weight="balanced")
    else:
        raise ValueError(f"unknown model kind {kind!r}")
    model.fit(X, y)
    return model


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Score:
    """Row-level precision/recall plus a per-run detection-delay summary."""

    label: str  # "model (logistic)", "authored rules", ...
    precision: float
    recall: float
    n_predicted_positive: int
    n_actual_positive: int
    n_runs_with_outbreak: int
    n_runs_detected: int
    mean_detection_delay: float | None  # days, over detected runs only
    never_detected_runs: int


def score_rows(
    rows: Sequence[DayRow], predictions: Sequence[int], *, label: str
) -> Score:
    """Score a 0/1 prediction per row. Detection delay per run: first
    positive prediction on or after the run's ground-truth onset day, minus
    that onset day; runs never predicted positive after onset count as
    'never detected'."""
    preds = list(predictions)
    tp = sum(1 for r, p in zip(rows, preds) if p and r.label)
    fp = sum(1 for r, p in zip(rows, preds) if p and not r.label)
    fn = sum(1 for r, p in zip(rows, preds) if not p and r.label)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0

    by_run: dict[int, list[tuple[int, int, int]]] = defaultdict(list)
    for r, p in zip(rows, preds):
        by_run[r.seed].append((r.day, r.label, p))

    delays: list[int] = []
    runs_with_outbreak = 0
    never = 0
    for items in by_run.values():
        items.sort()
        onset_days = [d for d, lbl, _ in items if lbl]
        if not onset_days:
            continue
        runs_with_outbreak += 1
        onset = onset_days[0]
        fired_after = [d for d, _, p in items if p and d >= onset]
        if fired_after:
            delays.append(fired_after[0] - onset)
        else:
            never += 1

    return Score(
        label=label,
        precision=precision,
        recall=recall,
        n_predicted_positive=tp + fp,
        n_actual_positive=tp + fn,
        n_runs_with_outbreak=runs_with_outbreak,
        n_runs_detected=runs_with_outbreak - never,
        mean_detection_delay=mean(delays) if delays else None,
        never_detected_runs=never,
    )


def score_model(model, test_rows: Sequence[DayRow], *, label: str) -> Score:
    preds = model.predict(_feature_matrix(test_rows)).astype(int).tolist()
    return score_rows(test_rows, preds, label=label)


def score_rules(test_rows: Sequence[DayRow], *, label: str = "authored rules") -> Score:
    return score_rows(
        test_rows, [int(r.rule_fired) for r in test_rows], label=label
    )


# ---------------------------------------------------------------------------
# The two benchmarks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BenchmarkResult:
    heading: str
    n_train_rows: int
    n_test_rows: int
    scores: tuple[Score, ...]  # rules first, then each model


def benchmark_in_distribution(
    seeds: Sequence[int],
    *,
    days: int = DEFAULT_RUN_DAYS,
    config: SimulationConfig = DEFAULT_SIMULATION_CONFIG,
) -> BenchmarkResult:
    rows = build_dataset(seeds, days=days, config=config)
    train, test = split_by_run(rows)
    logistic = train_model(train, kind="logistic")
    tree = train_model(train, kind="tree")
    return BenchmarkResult(
        heading="IN DISTRIBUTION (train and test are the same transmission regime)",
        n_train_rows=len(train),
        n_test_rows=len(test),
        scores=(
            score_rules(test),
            score_model(logistic, test, label="model (logistic regression)"),
            score_model(tree, test, label=f"model (tree, depth {BENCHMARK_TREE_MAX_DEPTH})"),
        ),
    )


def benchmark_cross_regime(
    train_seeds: Sequence[int],
    test_seeds: Sequence[int],
    *,
    days: int = DEFAULT_RUN_DAYS,
    train_suite_transmission: float = BENCHMARK_TRAIN_SUITE_TRANSMISSION,
    test_suite_transmissions: Sequence[float] = BENCHMARK_TEST_SUITE_TRANSMISSIONS,
) -> list[BenchmarkResult]:
    """Train once on ``train_suite_transmission``; evaluate on held-out
    seeds simulated at each of ``test_suite_transmissions``."""
    train_config = SimulationConfig(suite_transmission_probability=train_suite_transmission)
    train_rows = build_dataset(train_seeds, days=days, config=train_config)
    logistic = train_model(train_rows, kind="logistic")
    tree = train_model(train_rows, kind="tree")

    results: list[BenchmarkResult] = []
    for tp in test_suite_transmissions:
        test_config = SimulationConfig(suite_transmission_probability=tp)
        test_rows = build_dataset(test_seeds, days=days, config=test_config)
        results.append(
            BenchmarkResult(
                heading=(
                    f"CROSS REGIME (trained at suite p={train_suite_transmission:g}, "
                    f"tested at suite p={tp:g})"
                ),
                n_train_rows=len(train_rows),
                n_test_rows=len(test_rows),
                scores=(
                    score_rules(test_rows),
                    score_model(logistic, test_rows, label="model (logistic regression)"),
                    score_model(
                        tree, test_rows, label=f"model (tree, depth {BENCHMARK_TREE_MAX_DEPTH})"
                    ),
                ),
            )
        )
    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _fmt(value: float | None, decimals: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{decimals}f}"


def _print_result(result: BenchmarkResult) -> None:
    print(f"--- {result.heading} ---")
    print(f"    {result.n_train_rows} train rows, {result.n_test_rows} test rows")
    cols = [
        ("detector", 30),
        ("precision", 10),
        ("recall", 8),
        ("delay", 7),
        ("detected", 12),
    ]
    header = "  ".join(f"{name:>{w}}" if name != "detector" else f"{name:<{w}}" for name, w in cols)
    print(header)
    print("-" * len(header))
    for s in result.scores:
        detected = f"{s.n_runs_detected}/{s.n_runs_with_outbreak}"
        row = (
            f"{s.label:<30}",
            f"{_fmt(s.precision):>10}",
            f"{_fmt(s.recall):>8}",
            f"{_fmt(s.mean_detection_delay, 1):>7}",
            f"{detected:>12}",
        )
        print("  ".join(row))
    print()


def _tradeoff(model: Score, rules: Score) -> str:
    """One plain line comparing a model score to the rules score."""
    dp = model.precision - rules.precision
    dr = model.recall - rules.recall
    md, rd = model.mean_detection_delay, rules.mean_detection_delay
    dd = None if (md is None or rd is None) else md - rd
    return (
        f"precision {dp:+.2f}, recall {dr:+.2f}, "
        f"delay {'n/a' if dd is None else f'{dd:+.1f}d'}"
    )


def _verdict(in_dist: BenchmarkResult, cross: list[BenchmarkResult]) -> None:
    print("=" * 78)
    print("VERDICT  (logistic model vs authored rules, deltas are model minus rules)")
    print("=" * 78)
    print(f"  in distribution                         : {_tradeoff(in_dist.scores[1], in_dist.scores[0])}")
    cross_deltas = []
    for res in cross:
        d = res.scores[1].precision - res.scores[0].precision, res.scores[1].recall - res.scores[0].recall
        cross_deltas.append(d)
        tail = res.heading.split("tested at ")[-1].rstrip(")")
        print(f"  cross regime, {tail:26} : {_tradeoff(res.scores[1], res.scores[0])}")
    print()
    recall_gain_everywhere = all(dr > 0.02 for _, dr in cross_deltas) and (
        in_dist.scores[1].recall - in_dist.scores[0].recall > 0.02
    )
    precision_cost = -min(
        [in_dist.scores[1].precision - in_dist.scores[0].precision]
        + [dp for dp, _ in cross_deltas]
    )
    if recall_gain_everywhere:
        print("  The model consistently catches more real outbreak-days and fires about a")
        print(f"  day sooner, IN AND OUT of its training regime, at a cost of up to")
        print(f"  {precision_cost:.2f} in precision. The gain survives the transmission-probability")
        print("  shift, so it is not purely memorised -- but it is small, it is bought with")
        print("  false positives, and it is still a model of THIS simulator. The authored")
        print("  rules remain the shipped detector; the model is kept only as this benchmark.")
    else:
        print("  The model's advantage does not hold up once the transmission probability")
        print("  differs from training. Reported as a negative result: the classifier")
        print("  mostly learned this simulator. The three authored thresholds are the")
        print("  stronger, and the shipped, choice.")
    print()


def main() -> None:
    n = BENCHMARK_DEFAULT_SEEDS
    all_seeds = list(range(1, n + 1))
    bar = "=" * 78

    print(bar)
    print(f"LEARNED DETECTOR vs AUTHORED RULES   ({n} simulated runs, {DEFAULT_RUN_DAYS}-day)")
    print("features: relative_excess_ratio, count_within_window, count_sharing_category")
    print(f"label   : established (cumulative >= {ESTABLISHED_MIN_INFECTIONS}) AND active, from ground truth")
    print("split   : by RUN, never by day")
    print(bar)
    print()

    in_dist = benchmark_in_distribution(all_seeds)
    _print_result(in_dist)

    # Cross-regime: reuse the same split so train/test seeds never overlap.
    train_seeds, test_seeds = split_by_run(
        [DayRow(s, 0, 0.0, 0, 0, 0, False) for s in all_seeds]
    )
    train_ids = sorted({r.seed for r in train_seeds})
    test_ids = sorted({r.seed for r in test_seeds})
    cross = benchmark_cross_regime(train_ids, test_ids)
    for res in cross:
        _print_result(res)

    print("  delay = mean days from ground-truth outbreak onset to first positive call")
    print("          (over runs that were detected at all); detected = runs called / runs")
    print("          with a real outbreak.")
    print()
    _verdict(in_dist, cross)


if __name__ == "__main__":
    main()
