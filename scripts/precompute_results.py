"""Run the three heavy analyses once and cache their outputs as JSON.

    python -m scripts.precompute_results

Writes results/disclosure_sweep.json, results/benchmark.json and
results/adversarial.json. Those files are committed and served by the API
so nothing heavy runs on request. Re-run this when the underlying policy
constants or the model change.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adversarial.selftest import run_self_test  # noqa: E402
from simulation.benchmark import (  # noqa: E402
    DayRow,
    benchmark_cross_regime,
    benchmark_in_distribution,
    split_by_run,
)
from simulation.config import (  # noqa: E402
    BENCHMARK_DEFAULT_SEEDS,
    BENCHMARK_TEST_SUITE_TRANSMISSIONS,
    DEFAULT_EXPERIMENT_SEEDS,
    DEFAULT_RUN_DAYS,
)
from simulation.experiments import run_disclosure_sweeps  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"

ADVERSARIAL_SEEDS = 200


def _write(name: str, payload: dict) -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"  wrote {path.relative_to(RESULTS_DIR.parent)}")


def build_disclosure_sweep() -> dict:
    results = run_disclosure_sweeps()
    sweeps: dict[str, dict] = {}
    for name, summaries in results.sweeps.items():
        rows = []
        for s in summaries:
            rows.append(
                {
                    "value": s.value,
                    "degenerate": s.degenerate,
                    "degenerate_reason": s.degenerate_reason,
                    "n_disclosed": s.n_disclosed,
                    "n_established": s.n_established,
                    "disc_delay": s.mean_disclosure_delay,
                    "fire_delay": s.mean_fire_delay,
                    "gap": s.mean_gap,
                    "inf_before_disclosure_unbiased": s.mean_infections_before_disclosure_unbiased,
                    "inf_at_disclosure_conditional": s.mean_infections_at_disclosure,
                    "finest_level": (
                        s.finest_disclosed_level.name if s.finest_disclosed_level else None
                    ),
                }
            )
        sweeps[name] = {"rows": rows}
    return {
        "seeds": DEFAULT_EXPERIMENT_SEEDS,
        "days": DEFAULT_RUN_DAYS,
        "fizzle_rate": results.fizzle_rate,
        "false_alarm_rate": results.false_alarm_rate,
        "control_fire_delay": results.control_fire_delay,
        "primary_sweep": "STATISTICAL_GATE_FLOOR",
        "sweeps": sweeps,
    }


def _score_dict(score) -> dict:
    return {
        "precision": round(score.precision, 3),
        "recall": round(score.recall, 3),
        "delay": (
            None if score.mean_detection_delay is None else round(score.mean_detection_delay, 2)
        ),
    }


def build_benchmark() -> dict:
    all_seeds = list(range(1, BENCHMARK_DEFAULT_SEEDS + 1))
    in_dist = benchmark_in_distribution(all_seeds)
    train_seeds, test_seeds = split_by_run(
        [DayRow(s, 0, 0.0, 0, 0, 0, False) for s in all_seeds]
    )
    train_ids = sorted({r.seed for r in train_seeds})
    test_ids = sorted({r.seed for r in test_seeds})
    cross = benchmark_cross_regime(train_ids, test_ids)

    cross_regime = []
    model_still_wins = True
    for res, tp in zip(cross, BENCHMARK_TEST_SUITE_TRANSMISSIONS):
        rules, model = res.scores[0], res.scores[1]
        cross_regime.append(
            {
                "label": f"suite p={tp:g}",
                "rules": _score_dict(rules),
                "model": _score_dict(model),
            }
        )
        if not (model.recall > rules.recall + 0.02):
            model_still_wins = False

    if model_still_wins:
        cross_conclusion = (
            "The model's small recall and latency edge survives the shift in "
            "transmission probability: it is not purely memorised. The edge is still "
            "small and still bought with lower precision, and it is still a model of "
            "this simulator."
        )
    else:
        cross_conclusion = (
            "The model's advantage does not hold once the transmission probability "
            "differs from training. Reported as a negative result: the classifier "
            "mostly learned this simulator."
        )

    return {
        "seeds": BENCHMARK_DEFAULT_SEEDS,
        "days": DEFAULT_RUN_DAYS,
        "in_distribution": {
            "rules": _score_dict(in_dist.scores[0]),
            "model": _score_dict(in_dist.scores[1]),
        },
        "conclusion": (
            "In distribution the learned model is marginally faster and catches a few "
            "more real outbreak-days, at a cost of about three points of precision on a "
            "detector that already over-alarms. The authored threshold rules ship; the "
            "model is kept only as this benchmark."
        ),
        "cross_regime": cross_regime,
        "cross_regime_conclusion": cross_conclusion,
    }


def build_adversarial() -> dict:
    s = run_self_test(n_seeds=ADVERSARIAL_SEEDS)
    return {
        "seeds": s.n_runs,
        "days": s.days,
        "same_scope_pairs": s.same_scope_pairs,
        "exact_one_person_pins": s.exact_one_person_pinned,
        "band_one_person_pins": s.band_one_person_pinned,
        "exact_direction_known": s.exact_direction_known,
        "band_direction_known": s.band_direction_known,
        "band_median_possible_deltas": (
            None
            if s.band_median_possible_values == float("inf")
            else round(s.band_median_possible_values)
        ),
        "wandering_on_mean": round(s.wandering_on_mean, 2),
        "wandering_off_mean": round(s.wandering_off_mean, 2),
        "wandering_on_max": s.wandering_on_max,
        "wandering_off_max": s.wandering_off_max,
        "residual": s.band_residual,
    }


def main() -> None:
    steps = (
        ("disclosure_sweep", build_disclosure_sweep),
        ("benchmark", build_benchmark),
        ("adversarial", build_adversarial),
    )
    for name, build in steps:
        start = time.time()
        print(f"{name} ...", flush=True)
        _write(name, build())
        print(f"  {time.time() - start:.0f}s")


if __name__ == "__main__":
    main()
