"""Detection engine: is anything unusual happening?

Two independent detectors (rule 3), either of which can fire:

  * relative -- a location unusual versus its contemporaneous peers
  * absolute -- overall activity unusual versus a configured background
    rate (``config.BACKGROUND_RATE``, rule 4)

The engine reports three plain findings and never combines them into a
composite score (rule 6):

  * ``relative_excess_ratio``
  * ``count_within_window``
  * ``count_sharing_category``

Its other job is to hand the disclosure engine an *aggregate* view --
per-scope qualifying report counts -- so that the disclosure engine never
touches individual records (rule 10).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .config import DEFAULT_DETECTION_CONFIG, DetectionConfig
from .models import Category, Report, ScopeRegistry

__all__ = [
    "DetectionFindings",
    "DetectionResult",
    "evaluate",
]


@dataclass(frozen=True)
class DetectionFindings:
    """The three findings, reported plainly and separately (rule 6)."""

    relative_excess_ratio: float
    count_within_window: int
    count_sharing_category: int


@dataclass(frozen=True)
class DetectionResult:
    fired: bool
    relative_detector_fired: bool
    absolute_detector_fired: bool
    findings: DetectionFindings

    # Context for the findings and for disclosure.
    dominant_category: Category | None
    hotspot_location_id: str | None
    absolute_expected: float
    window_start: datetime
    window_end: datetime

    # Aggregate handed to the disclosure engine (rule 10): for every scope
    # that contains at least one qualifying report, how many qualifying
    # reports it contains. "Qualifying" == within the detection window and
    # sharing the dominant category.
    qualifying_scope_counts: dict[str, int]


def _now(now: datetime | None) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


def _within_window(
    reports: list[Report], window_start: datetime, window_end: datetime
) -> list[Report]:
    return [r for r in reports if window_start <= r.submitted_at <= window_end]


def _dominant_category(window_reports: list[Report]) -> Category | None:
    """The category with the most within-window reports. Ties broken
    deterministically by category name so the result never depends on
    input ordering."""
    if not window_reports:
        return None
    counts = Counter(r.category for r in window_reports)
    top = max(counts.values())
    return sorted((c for c, n in counts.items() if n == top), key=lambda c: c.value)[0]


def _run_relative_detector(
    window_reports: list[Report],
    registry: ScopeRegistry,
    config: DetectionConfig,
) -> tuple[bool, float, str | None]:
    """Compare each reporting location's per-capita rate against the pooled
    per-capita rate of everyone else in the campus (its contemporaneous
    peers). Returns (fired, excess_ratio_of_hotspot, hotspot_location_id).

    Both rates are additively smoothed by ``config.relative_smoothing`` so
    a quiet peer group cannot drive the ratio to infinity (see
    ``config.RELATIVE_SMOOTHING``).
    """
    total = len(window_reports)
    campus_population = registry.campus_population()
    if total == 0:
        return (False, 0.0, None)

    per_location = Counter(r.location_id for r in window_reports)
    k = config.relative_smoothing

    best_ratio = 0.0
    hotspot: str | None = None
    hotspot_count = 0

    for location_id, loc_count in per_location.items():
        loc_population = registry.get(location_id).population
        peer_population = campus_population - loc_population
        peer_count = total - loc_count
        if peer_population <= 0:
            # This location IS the whole comparison set; there are no peers
            # to be unusual against. Skip it for the relative detector.
            continue

        # Additively smoothed rates on both sides (rule: named constant).
        loc_rate = (loc_count + k) / (loc_population + k)
        peer_rate = (peer_count + k) / (peer_population + k)
        ratio = loc_rate / peer_rate

        if ratio > best_ratio:
            best_ratio = ratio
            hotspot = location_id
            hotspot_count = loc_count

    fired = (
        hotspot is not None
        and best_ratio >= config.relative_excess_ratio
        and hotspot_count >= config.min_relative_cluster_reports
    )
    return (fired, best_ratio, hotspot)


def _run_absolute_detector(
    window_reports: list[Report],
    registry: ScopeRegistry,
    config: DetectionConfig,
) -> tuple[bool, float]:
    """Compare the raw within-window count against the background
    expectation for the whole declared campus population. Returns
    (fired, expected_count)."""
    expected = config.background_rate * registry.campus_population()
    observed = len(window_reports)
    fired = observed >= expected * config.absolute_excess_ratio
    return (fired, expected)


def _qualifying_scope_counts(
    window_reports: list[Report],
    registry: ScopeRegistry,
    dominant_category: Category | None,
) -> dict[str, int]:
    """For each scope containing at least one qualifying report, the count
    of qualifying reports in its subtree. Qualifying == within window and
    sharing the dominant category."""
    counts: Counter[str] = Counter()
    if dominant_category is None:
        return {}
    for report in window_reports:
        if report.category != dominant_category:
            continue
        for scope in registry.chain_to_root(report.location_id):
            counts[scope.id] += 1
    return dict(counts)


def evaluate(
    reports: list[Report],
    registry: ScopeRegistry,
    *,
    now: datetime | None = None,
    config: DetectionConfig = DEFAULT_DETECTION_CONFIG,
) -> DetectionResult:
    """Run both detectors and assemble the findings.

    ``now`` defaults to the current UTC time; pass it explicitly for
    deterministic evaluation.
    """
    window_end = _now(now)
    window_start = window_end - timedelta(hours=config.detection_window_hours)

    for report in reports:
        # Fail loudly on an unknown location rather than silently dropping
        # a report from the denominator-free count.
        registry.get(report.location_id)

    window_reports = _within_window(reports, window_start, window_end)

    dominant = _dominant_category(window_reports)
    count_within_window = len(window_reports)
    count_sharing_category = (
        sum(1 for r in window_reports if r.category == dominant) if dominant else 0
    )

    relative_fired, excess_ratio, hotspot = _run_relative_detector(
        window_reports, registry, config
    )
    absolute_fired, expected = _run_absolute_detector(window_reports, registry, config)

    findings = DetectionFindings(
        relative_excess_ratio=excess_ratio,
        count_within_window=count_within_window,
        count_sharing_category=count_sharing_category,
    )

    return DetectionResult(
        fired=relative_fired or absolute_fired,
        relative_detector_fired=relative_fired,
        absolute_detector_fired=absolute_fired,
        findings=findings,
        dominant_category=dominant,
        hotspot_location_id=hotspot,
        absolute_expected=expected,
        window_start=window_start,
        window_end=window_end,
        qualifying_scope_counts=_qualifying_scope_counts(
            window_reports, registry, dominant
        ),
    )
