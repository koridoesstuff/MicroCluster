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

Both detectors are scored on the same subset -- within-window reports in
the *dominant category* -- so that whatever trips a detector is exactly
what the disclosure engine goes on to describe, never a superset of it.

Its other job is to hand the disclosure engine an *aggregate* view --
per-scope qualifying report counts -- so that the disclosure engine never
touches individual records (rule 10).

All reports passed to :func:`evaluate` must resolve to scopes at a single
``ScopeLevel``; see that function's docstring.

A single call to :func:`evaluate` is still a pure, single-instant
computation -- ``raw_fired`` is recomputed from nothing but this call's
reports. ``fired`` (the field disclosure and everything downstream acts
on) additionally applies HYSTERESIS across a *sequence* of calls, threaded
explicitly via ``HysteresisState`` (see that class and
``config.HYSTERESIS_MIN_FIRED_DAYS`` / ``HYSTERESIS_RELEASE_THRESHOLD``).
Passing no state (the default) makes a single call behave exactly as if
hysteresis did not exist.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .config import DEFAULT_DETECTION_CONFIG, DetectionConfig
from .models import Category, Report, ScopeLevel, ScopeRegistry

__all__ = [
    "DetectionFindings",
    "DetectionResult",
    "HysteresisState",
    "evaluate",
]


@dataclass(frozen=True)
class DetectionFindings:
    """The three findings, reported plainly and separately (rule 6)."""

    relative_excess_ratio: float
    count_within_window: int
    count_sharing_category: int


@dataclass(frozen=True)
class HysteresisState:
    """Carries hysteresis across a SEQUENCE of :func:`evaluate` calls (one
    per day, say). Immutable: each call returns the next state as part of
    its :class:`DetectionResult`; the caller threads it into the following
    call. The default, ``HysteresisState()``, is "not currently active" --
    passing it (or nothing) makes hysteresis a no-op.
    """

    active: bool = False
    consecutive_days: int = 0


@dataclass(frozen=True)
class DetectionResult:
    fired: bool
    raw_fired: bool
    relative_detector_fired: bool
    absolute_detector_fired: bool
    findings: DetectionFindings
    hysteresis_state: HysteresisState

    # Context for the findings and for disclosure.
    dominant_category: Category | None
    hotspot_location_id: str | None
    absolute_expected: float
    window_start: datetime
    window_end: datetime

    # Aggregate handed to the disclosure engine (rule 10): for every scope
    # that contains at least one qualifying report, how many qualifying
    # reports it contains. "Qualifying" == within the detection window and
    # sharing the dominant category. Both detectors are scored on the same
    # dominant-category subset, so whatever fires is what this table (and
    # therefore the disclosure) describes.
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
    dominant_category: Category | None,
) -> tuple[bool, float, str | None]:
    """Compare each reporting location's per-capita rate against the pooled
    per-capita rate of everyone else in the campus (its contemporaneous
    peers). Returns (fired, excess_ratio_of_hotspot, hotspot_location_id).

    The excess ratio is computed on TOTAL within-window volume at each
    location -- "is this location busier than its peers" is a volume
    question. The minimum-cluster-size gate
    (``config.min_relative_cluster_reports``), however, counts only the
    hotspot's reports **in the dominant category**. A location whose extra
    volume is really three unrelated illnesses therefore does not clear the
    gate: what fires is what the disclosure engine will describe.

    Both rates are additively smoothed by ``config.relative_smoothing`` so
    a quiet peer group cannot drive the ratio to infinity (see
    ``config.RELATIVE_SMOOTHING``).

    Assumes every report resolves to a scope at the SAME hierarchy level
    (``evaluate`` enforces this): peer population is
    ``campus_population - location_population``, which is only correct when
    report locations do not nest inside one another.
    """
    total = len(window_reports)
    campus_population = registry.campus_population()
    if total == 0:
        return (False, 0.0, None)

    per_location = Counter(r.location_id for r in window_reports)
    per_location_dominant: Counter[str] = Counter(
        r.location_id for r in window_reports if r.category == dominant_category
    )
    k = config.relative_smoothing

    best_ratio = 0.0
    hotspot: str | None = None
    hotspot_dominant_count = 0

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
            hotspot_dominant_count = per_location_dominant[location_id]

    fired = (
        hotspot is not None
        and best_ratio >= config.relative_excess_ratio
        and hotspot_dominant_count >= config.min_relative_cluster_reports
    )
    return (fired, best_ratio, hotspot)


def _run_absolute_detector(
    window_reports: list[Report],
    registry: ScopeRegistry,
    config: DetectionConfig,
    dominant_category: Category | None,
) -> tuple[bool, float]:
    """Compare the within-window count of DOMINANT-CATEGORY reports against
    the background expectation for the whole declared campus population.
    Returns (fired, expected_count).

    Only dominant-category reports are counted. A spike built from several
    unrelated illnesses therefore cannot fire this detector and then leave
    the disclosure engine describing only one category's slice of it -- the
    thing that fires is the thing that gets described. If campus-wide
    elevation across mixed categories is worth flagging, it should be an
    explicit, separately reported signal, not a side effect of this one.

    ``expected`` is still ``BACKGROUND_RATE * campus_population``, the
    whole-population background rather than a per-category one, which makes
    this a deliberately conservative test. Give ``BACKGROUND_RATE`` a
    per-category value when tuning it against real baseline data.
    """
    expected = config.background_rate * registry.campus_population()
    observed = sum(1 for r in window_reports if r.category == dominant_category)
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


def _apply_hysteresis(
    raw_fired: bool,
    count_within_window: int,
    prior: HysteresisState,
    config: DetectionConfig,
) -> tuple[bool, HysteresisState]:
    """Turn this instant's raw fired/not-fired into a hysteresis-aware
    ``fired`` plus the state to pass into the next call.

    Rules (config.HYSTERESIS_MIN_FIRED_DAYS / HYSTERESIS_RELEASE_THRESHOLD):

    * Raw fired -> always fired; the active streak continues (or starts).
    * Raw not fired, and not currently active -> stays not fired. Nothing
      to hold.
    * Raw not fired, but currently active -> HOLD fired True, UNLESS
      either the window has clearly emptied out (count_within_window at or
      below the release threshold: release immediately) or the minimum
      hold duration has already been served (release on schedule).
    """
    if raw_fired:
        streak = prior.consecutive_days + 1 if prior.active else 1
        return True, HysteresisState(active=True, consecutive_days=streak)

    if not prior.active:
        return False, HysteresisState(active=False, consecutive_days=0)

    if count_within_window <= config.hysteresis_release_threshold:
        return False, HysteresisState(active=False, consecutive_days=0)

    if prior.consecutive_days < config.hysteresis_min_fired_days:
        return True, HysteresisState(
            active=True, consecutive_days=prior.consecutive_days + 1
        )

    return False, HysteresisState(active=False, consecutive_days=0)


def evaluate(
    reports: list[Report],
    registry: ScopeRegistry,
    *,
    now: datetime | None = None,
    config: DetectionConfig = DEFAULT_DETECTION_CONFIG,
    hysteresis_state: HysteresisState | None = None,
) -> DetectionResult:
    """Run both detectors and assemble the findings.

    ``now`` defaults to the current UTC time; pass it explicitly for
    deterministic evaluation.

    **Mixed-level assumption (enforced).** Every report must resolve to a
    scope at the *same* ``ScopeLevel``. The relative detector derives a
    location's peer population as ``campus_population -
    location_population``; that subtraction is only correct when report
    locations are siblings, not nested (a floor inside a building it also
    receives reports for would be double-counted). If reports arrive at
    more than one level this function raises ``ValueError`` -- normalise
    them to a single level upstream. Handling true nesting is left for a
    later change.

    ``hysteresis_state`` is the ``HysteresisState`` returned by the
    PREVIOUS call in a sequence (e.g. yesterday's); omit it (or pass
    ``None``) for a one-off evaluation, which is equivalent to always
    starting "not active". The next state to thread into the following
    call is returned on the result as ``hysteresis_state``.
    """
    window_end = _now(now)
    window_start = window_end - timedelta(hours=config.detection_window_hours)

    report_levels: set[ScopeLevel] = set()
    for report in reports:
        # ``registry.get`` fails loudly on an unknown location; we also
        # collect the scope level of every report here.
        report_levels.add(registry.get(report.location_id).level)
    if len(report_levels) > 1:
        raise ValueError(
            "detection.evaluate requires every report to be filed at the "
            "same scope level; got "
            f"{sorted(level.name for level in report_levels)}. The relative "
            "detector computes peer population as campus_population minus the "
            "reporting location's population, which is only correct when "
            "report locations do not nest. Normalise reports to one level "
            "before calling."
        )

    window_reports = _within_window(reports, window_start, window_end)

    dominant = _dominant_category(window_reports)
    count_within_window = len(window_reports)
    count_sharing_category = (
        sum(1 for r in window_reports if r.category == dominant) if dominant else 0
    )

    relative_fired, excess_ratio, hotspot = _run_relative_detector(
        window_reports, registry, config, dominant
    )
    absolute_fired, expected = _run_absolute_detector(
        window_reports, registry, config, dominant
    )

    findings = DetectionFindings(
        relative_excess_ratio=excess_ratio,
        count_within_window=count_within_window,
        count_sharing_category=count_sharing_category,
    )

    raw_fired = relative_fired or absolute_fired
    fired, next_hysteresis_state = _apply_hysteresis(
        raw_fired, count_within_window, hysteresis_state or HysteresisState(), config
    )

    return DetectionResult(
        fired=fired,
        raw_fired=raw_fired,
        relative_detector_fired=relative_fired,
        absolute_detector_fired=absolute_fired,
        findings=findings,
        hysteresis_state=next_hysteresis_state,
        dominant_category=dominant,
        hotspot_location_id=hotspot,
        absolute_expected=expected,
        window_start=window_start,
        window_end=window_end,
        qualifying_scope_counts=_qualifying_scope_counts(
            window_reports, registry, dominant
        ),
    )
