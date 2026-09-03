"""Print the six reference scenarios and their evaluation tables.

    python -m microcluster.demo

This is a read-only illustration of the two engines. It builds the same
fixtures the tests use.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from microcluster.disclosure import DisclosureResult  # noqa: E402
from microcluster.engine import AnalysisResult, analyze  # noqa: E402
from microcluster.models import Category  # noqa: E402
from tests.fixtures import (  # noqa: E402
    NOW,
    reports,
    small_registry_floor18,
    standard_registry,
)


def _fmt_detection(result: AnalysisResult) -> str:
    d = result.detection
    f = d.findings
    fired = []
    if d.relative_detector_fired:
        fired.append("RELATIVE")
    if d.absolute_detector_fired:
        fired.append("ABSOLUTE")
    lines = [
        f"  detection fired : {d.fired}  ({' + '.join(fired) if fired else 'neither detector'})",
        f"  findings        : relative_excess_ratio = {f.relative_excess_ratio:.2f}"
        f" (hotspot {d.hotspot_location_id})",
        f"                    count_within_window   = {f.count_within_window}"
        f"  (absolute expectation {d.absolute_expected:.1f})",
        f"                    count_sharing_category= {f.count_sharing_category}"
        f"  (category {d.dominant_category.value if d.dominant_category else '-'})",
    ]
    return "\n".join(lines)


def _fmt_table(disc: DisclosureResult) -> str:
    if not disc.evaluations:
        return "  (disclosure engine did not run -- nothing detected)"
    header = (
        f"  {'scope':<26} {'lvl':<8} {'n':>5} {'q':>4} "
        f"{'stat>=':>7} {'stat':>5} {'n>=20':>6} {'frac':>6} {'frac<=':>7} "
        f"{'priv':>5} {'DISCLOSE':>9}"
    )
    rows = [header, "  " + "-" * (len(header) - 2)]
    for ev in disc.evaluations:
        label = ev.scope_label if len(ev.scope_label) <= 26 else ev.scope_label[:23] + "..."
        rows.append(
            f"  {label:<26} {ev.scope_level.name:<8} {ev.population:>5} "
            f"{ev.qualifying_reports:>4} {ev.statistical_threshold:>7} "
            f"{('PASS' if ev.statistical_pass else 'FAIL'):>5} "
            f"{('PASS' if ev.min_population_pass else 'FAIL'):>6} "
            f"{ev.report_fraction:>6.2f} "
            f"{('PASS' if ev.report_fraction_pass else 'FAIL'):>7} "
            f"{('PASS' if ev.privacy_pass else 'FAIL'):>5} "
            f"{('*SELECTED*' if ev.selected else ('eligible' if ev.disclosure_eligible else 'no')):>9}"
        )
    rows.append("")
    for ev in disc.evaluations:
        rows.append(f"    {ev.scope_label}: {ev.disclosure_reason}")
    return "\n".join(rows)


def _scenario(title: str, result: AnalysisResult) -> None:
    print("=" * 78)
    print(title)
    print("=" * 78)
    print(_fmt_detection(result))
    print()
    print(_fmt_table(result.disclosure))
    disclosed = result.disclosure.disclosed()
    print()
    if disclosed is None:
        print("  >> DISCLOSED: nothing")
    else:
        print(f"  >> DISCLOSED: {disclosed.scope_label}  (n={disclosed.population}, "
              f"{disclosed.qualifying_reports} qualifying reports)")
    print()


def main() -> None:
    reg = standard_registry()

    # 1. Localized cluster -- relative fires, absolute does not.
    localized = (
        reports("S1", 9, category=Category.RESPIRATORY)
        + reports("B2", 2, category=Category.GENERAL)
        + reports("B3", 1, category=Category.GASTROINTESTINAL)
        + reports("B4", 1, category=Category.OTHER)
        + reports("B5", 1, category=Category.GENERAL)
        + reports("S3", 4, category=Category.RESPIRATORY, hours_ago=400)  # outside window
    )
    _scenario("SCENARIO 1  Localized cluster (relative fires, absolute does not)",
              analyze(localized, reg, now=NOW))

    # 2. Campus-wide rise -- absolute fires, relative does not.
    campus_wide = []
    for b in ("B1", "B2", "B3", "B4", "B5"):
        campus_wide += reports(b, 14, category=Category.RESPIRATORY)
    _scenario("SCENARIO 2  Campus-wide rise (absolute fires, relative does not)",
              analyze(campus_wide, reg, now=NOW))

    # 3. Scattered noise -- neither fires.
    scattered = (
        reports("B1", 2, category=Category.GENERAL)
        + reports("B2", 2, category=Category.RESPIRATORY)
        + reports("B3", 2, category=Category.GASTROINTESTINAL)
        + reports("B4", 2, category=Category.OTHER)
        + reports("B5", 1, category=Category.GENERAL)
        + reports("F2", 2, category=Category.RESPIRATORY)
        + reports("F3", 2, category=Category.GENERAL)
        + reports("S2", 2, category=Category.OTHER)
    )
    _scenario("SCENARIO 3  Scattered noise (neither detector fires)",
              analyze(scattered, reg, now=NOW))

    # 4. Overclaim refusal -- 7 reports, campus n=2000 -> statistical FAIL.
    overclaim = reports("B1", 7, category=Category.RESPIRATORY)
    _scenario("SCENARIO 4  Overclaim refusal (7 reports vs campus n=2000)",
              analyze(overclaim, reg, now=NOW))

    # 5. Privacy refusal -- 5 reports, floor n=18 -> statistical PASS, privacy FAIL.
    small = small_registry_floor18()
    privacy = reports("F", 5, category=Category.RESPIRATORY)
    _scenario("SCENARIO 5  Privacy refusal (5 reports, floor n=18 -> coarser scope)",
              analyze(privacy, small, now=NOW))

    # 6. Both gates across populations -- see tests/test_disclosure.py for the
    #    full parametric table; here we show the n=40 case passing both.
    from tests.fixtures import single_scope_registry

    across = reports("C", 8, category=Category.RESPIRATORY)
    _scenario("SCENARIO 6  Both gates, n=40 (statistical threshold 7, privacy ok)",
              analyze(across, single_scope_registry(40), now=NOW))

    # 7. Roster refusal -- 15 reports in a declared group of n=25: passes
    #    the statistical gate and the population minimum, refused because
    #    15/25 = 0.60 exceeds MAX_REPORT_FRACTION.
    from tests.fixtures import roster_registry

    roster = reports("G", 15, category=Category.RESPIRATORY)
    _scenario("SCENARIO 7  Roster refusal (15 reports, group n=25 -> fraction 0.60)",
              analyze(roster, roster_registry(), now=NOW))


if __name__ == "__main__":
    main()
