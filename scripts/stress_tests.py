"""Run the two limitation-closing stress tests and cache them as JSON.

    python -m scripts.stress_tests             # both (a few minutes)
    python -m scripts.stress_tests --scale     # scale validation only
    python -m scripts.stress_tests --realism   # reporting-realism only

Writes results/scale.json and results/reporting_realism.json. They are
committed for the docs to cite; the API does not serve them, and
``scripts.precompute_results`` (the three shipped panels) is unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simulation.realism import (  # noqa: E402
    VARIANTS,
    format_sweep,
    run_realism_sweep,
    run_sensitivity_grid,
)
from simulation.scale import format_reports, run_scale_validation  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
SEEDS = list(range(1, 501))


def _write(name: str, payload: dict) -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"  wrote {path.relative_to(RESULTS_DIR.parent)}")


def build_scale() -> dict:
    reports = run_scale_validation(SEEDS)
    print(format_reports(reports))
    return {"seeds": len(SEEDS), "days": 30, "sizes": [asdict(r) for r in reports]}


def build_realism() -> dict:
    sweep = run_realism_sweep(SEEDS)
    print(format_sweep(sweep))
    grid = run_sensitivity_grid(SEEDS)
    return {"seeds": len(SEEDS), "days": 30, "variants": sweep, "grid": grid,
            "variant_names": list(VARIANTS)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale", action="store_true")
    parser.add_argument("--realism", action="store_true")
    args = parser.parse_args()
    both = not (args.scale or args.realism)
    if args.scale or both:
        t = time.time()
        _write("scale", build_scale())
        print(f"  {time.time() - t:.0f}s")
    if args.realism or both:
        t = time.time()
        _write("reporting_realism", build_realism())
        print(f"  {time.time() - t:.0f}s")


if __name__ == "__main__":
    main()
