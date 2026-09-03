"""Disclosure engine: what, if anything, may be said, and at what scope?

Runs after detection (rule 10). It is handed an *aggregate* table --
per-scope qualifying report counts -- plus the scope registry. It never
sees an individual record.

Two separate gates (rule 8), evaluated independently, never merged into
one number:

  * statistical gate: qualifying >= max(floor, ceil(sqrt(n)))  -- up with n
  * privacy gate:     n >= MIN_SCOPE_POPULATION
                      AND qualifying / n <= MAX_REPORT_FRACTION -- down with n

Both must pass for a scope to be disclosure-eligible. The finest eligible
scope is selected (rule 9). Every candidate scope -- winner and rejected
alike -- gets a complete ``ScopeEvaluation`` record (rule 12), and the
winner is picked *from that table*, never on a separate path.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .config import DEFAULT_DISCLOSURE_CONFIG, DisclosureConfig
from .models import ScopeLevel, ScopeRegistry

__all__ = [
    "ScopeEvaluation",
    "DisclosureResult",
    "statistical_threshold",
    "evaluate",
]


def _ceil_sqrt(n: int) -> int:
    """ceil(sqrt(n)) computed in integers, so perfect squares are exact
    (float sqrt(x*x) can land just under x)."""
    root = math.isqrt(n)
    return root if root * root == n else root + 1


def statistical_threshold(n: int, config: DisclosureConfig = DEFAULT_DISCLOSURE_CONFIG) -> int:
    """The statistical gate threshold for a declared population ``n``:

        max(STATISTICAL_GATE_FLOOR, ceil(sqrt(n)))

    Scales up with n -- a bigger claim needs more evidence (rule 8). This
    is a policy shape, not a proven law (see ``config.py``).
    """
    return max(config.statistical_gate_floor, _ceil_sqrt(n))


@dataclass(frozen=True)
class ScopeEvaluation:
    """A complete evaluation record for one candidate scope (rule 12).

    A future UI renders these directly and must never recompute a gate.
    """

    scope_id: str
    scope_label: str
    scope_level: ScopeLevel
    population: int
    qualifying_reports: int

    # Statistical gate.
    statistical_threshold: int
    statistical_pass: bool

    # Privacy gate (two conditions, both required).
    min_scope_population: int
    min_population_pass: bool
    report_fraction: float
    max_report_fraction: float
    report_fraction_pass: bool
    privacy_pass: bool

    # Outcome.
    disclosure_eligible: bool
    selected: bool
    disclosure_reason: str


@dataclass(frozen=True)
class DisclosureResult:
    # Ordered finest scope first. Includes rejected scopes (rule 12).
    evaluations: tuple[ScopeEvaluation, ...]
    disclosed_scope_id: str | None

    def disclosed(self) -> ScopeEvaluation | None:
        for ev in self.evaluations:
            if ev.selected:
                return ev
        return None


def _fineness_key(ev_scope_level: ScopeLevel, population: int, scope_id: str):
    """Sort key: finest first. Deeper level wins; then smaller declared
    population; then scope id for a total, stable order."""
    return (-int(ev_scope_level), population, scope_id)


def _reason(
    *,
    selected: bool,
    eligible: bool,
    statistical_pass: bool,
    min_population_pass: bool,
    report_fraction_pass: bool,
    qualifying: int,
    threshold: int,
    n: int,
    min_pop: int,
    fraction: float,
    max_fraction: float,
) -> str:
    if selected:
        return "Disclosed: finest scope passing both the statistical and privacy gates."
    if eligible:
        return "Eligible: passes both gates, but a finer scope was disclosed."

    fails: list[str] = []
    if not statistical_pass:
        fails.append(
            f"statistical gate failed ({qualifying} qualifying reports < "
            f"required {threshold} for n={n})"
        )
    if not min_population_pass:
        fails.append(
            f"population n={n} below minimum privacy scope ({min_pop})"
        )
    if not report_fraction_pass:
        fails.append(
            f"report fraction {fraction:.2f} exceeds maximum {max_fraction:.2f} "
            f"(disclosure would name so large a share of the group that the "
            f"statement is effectively a roster)"
        )
    return "Rejected: " + "; ".join(fails)


def evaluate(
    registry: ScopeRegistry,
    qualifying_scope_counts: dict[str, int],
    *,
    config: DisclosureConfig = DEFAULT_DISCLOSURE_CONFIG,
) -> DisclosureResult:
    """Evaluate both gates for every candidate scope and select the finest
    eligible one.

    ``qualifying_scope_counts`` maps a scope id to the number of qualifying
    reports in that scope's subtree (produced by the detection engine).
    Only scopes appearing as keys are candidates.
    """
    candidates = sorted(
        qualifying_scope_counts.keys(),
        key=lambda sid: _fineness_key(
            registry.get(sid).level, registry.get(sid).population, sid
        ),
    )

    # First pass: gate results, no selection yet.
    gate_rows: list[dict] = []
    for scope_id in candidates:
        scope = registry.get(scope_id)
        n = scope.population
        qualifying = qualifying_scope_counts[scope_id]

        threshold = statistical_threshold(n, config)
        statistical_pass = qualifying >= threshold

        min_population_pass = n >= config.min_scope_population
        fraction = qualifying / n
        report_fraction_pass = fraction <= config.max_report_fraction
        privacy_pass = min_population_pass and report_fraction_pass

        gate_rows.append(
            {
                "scope": scope,
                "qualifying": qualifying,
                "threshold": threshold,
                "statistical_pass": statistical_pass,
                "min_population_pass": min_population_pass,
                "fraction": fraction,
                "report_fraction_pass": report_fraction_pass,
                "privacy_pass": privacy_pass,
                "eligible": statistical_pass and privacy_pass,
            }
        )

    # Select the finest eligible scope (candidates already finest-first).
    selected_id: str | None = next(
        (row["scope"].id for row in gate_rows if row["eligible"]), None
    )

    evaluations = tuple(
        ScopeEvaluation(
            scope_id=row["scope"].id,
            scope_label=row["scope"].label,
            scope_level=row["scope"].level,
            population=row["scope"].population,
            qualifying_reports=row["qualifying"],
            statistical_threshold=row["threshold"],
            statistical_pass=row["statistical_pass"],
            min_scope_population=config.min_scope_population,
            min_population_pass=row["min_population_pass"],
            report_fraction=row["fraction"],
            max_report_fraction=config.max_report_fraction,
            report_fraction_pass=row["report_fraction_pass"],
            privacy_pass=row["privacy_pass"],
            disclosure_eligible=row["eligible"],
            selected=(row["scope"].id == selected_id),
            disclosure_reason=_reason(
                selected=(row["scope"].id == selected_id),
                eligible=row["eligible"],
                statistical_pass=row["statistical_pass"],
                min_population_pass=row["min_population_pass"],
                report_fraction_pass=row["report_fraction_pass"],
                qualifying=row["qualifying"],
                threshold=row["threshold"],
                n=row["scope"].population,
                min_pop=config.min_scope_population,
                fraction=row["fraction"],
                max_fraction=config.max_report_fraction,
            ),
        )
        for row in gate_rows
    )

    return DisclosureResult(evaluations=evaluations, disclosed_scope_id=selected_id)
