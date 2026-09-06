"""End-to-end demo: simulate an outbreak, generate anonymous reports from
it, and feed them to the UNCHANGED detection engine, once per simulated
day.

    python -m simulation.detection_demo

Prints, per seed and per day: the true infection count (ground truth --
never seen by the detector), how many reports were submitted that day,
whether detection fired, which detector, and the disclosed scope if any.
Then a summary of TWO delays -- time-to-first-FIRE and
time-to-first-DISCLOSURE -- and the full list of distinct scopes disclosed
over the run (scope stability, config.SIBLING_SWITCH_MARGIN, keeps this
list short).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simulation.config import DEFAULT_RUN_DAYS, DEFAULT_SMOKE_SEEDS  # noqa: E402
from simulation.pipeline import DailyRecord, run_with_detection  # noqa: E402


def _detector_label(record: DailyRecord) -> str:
    if record.relative_fired and record.absolute_fired:
        return "both"
    if record.relative_fired:
        return "relative"
    if record.absolute_fired:
        return "absolute"
    return "-"


def _print_run(seed: int, days: int) -> None:
    result = run_with_detection(seed=seed, days=days)

    header = (
        f"{'day':>3}  {'true_infected':>13}  {'reports_today':>13}  "
        f"{'fired':>5}  {'detector':>8}  disclosed_scope"
    )
    print(f"SEED {seed}")
    print(header)
    print("-" * len(header))

    outbreak_started_day: int | None = None

    for record in result.daily_records:
        if outbreak_started_day is None and record.true_infected_count > 0:
            outbreak_started_day = record.day

        print(
            f"{record.day:>3}  {record.true_infected_count:>13}  "
            f"{record.reports_submitted_today:>13}  "
            f"{str(record.detection_fired):>5}  {_detector_label(record):>8}  "
            f"{record.disclosed_scope_id or '-'}"
        )

    last = result.daily_records[-1]
    fired_day = last.first_fired_day
    disclosed_day = last.first_disclosed_day
    distinct_scopes = result.distinct_disclosed_scopes()

    print()
    if outbreak_started_day is None:
        print("  outbreak never took hold: nobody was ever infected")
    else:
        print(f"  outbreak began (ground truth)   : day {outbreak_started_day}")

    if fired_day is None:
        print("  detector never fired in the run")
    else:
        print(f"  time-to-first-FIRE              : day {fired_day}"
              + (f"  (delay {fired_day - outbreak_started_day} day(s) from outbreak start)"
                 if outbreak_started_day is not None else ""))

    if disclosed_day is None:
        print("  detector never disclosed a scope in the run")
    else:
        print(f"  time-to-first-DISCLOSURE        : day {disclosed_day}"
              + (f"  (delay {disclosed_day - outbreak_started_day} day(s) from outbreak start)"
                 if outbreak_started_day is not None else ""))

    if fired_day is not None and disclosed_day is not None:
        print(f"  cost of the privacy policy      : {disclosed_day - fired_day} day(s) "
              f"(fired but could not yet be described)")

    print(f"  distinct scopes ever disclosed  : {len(distinct_scopes)} {distinct_scopes}")
    print()


def main() -> None:
    for seed in DEFAULT_SMOKE_SEEDS:
        _print_run(seed, DEFAULT_RUN_DAYS)


if __name__ == "__main__":
    main()
