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

A single call to :func:`evaluate` is still exactly that: one instant's
gate table. Called in a SEQUENCE (e.g. once a day), it additionally offers
SCOPE STABILITY -- pass the previous call's winning scope id as
``prior_disclosed_scope_id`` and evaluate() prefers to keep disclosing that
scope, or a coarser ancestor of it, rather than hopping to a different
scope on a small night-to-night difference in count (see
``config.SIBLING_SWITCH_MARGIN``). Passing no prior id (the default) makes
a single call behave exactly as if stability did not exist.
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
    stability_note: str | None = None,
) -> str:
    if selected:
        return stability_note or "Disclosed: finest scope passing both the statistical and privacy gates."
    if eligible:
        return stability_note or "Eligible: passes both gates, but a finer scope was disclosed."

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


def _stable_selection(
    gate_rows: list[dict],
    registry: ScopeRegistry,
    prior_disclosed_scope_id: str | None,
    config: DisclosureConfig,
) -> tuple[str | None, dict[str, str]]:
    """Pick the winner with scope stability applied, and any reason-text
    overrides that result from it.

    Returns ``(selected_id, stability_notes)``. When there is no usable
    prior scope this round, ``stability_notes`` is empty and
    ``selected_id`` is exactly the plain finest-eligible pick -- a single
    call with no ``prior_disclosed_scope_id`` is unaffected by any of this.
    """
    by_id = {row["scope"].id: row for row in gate_rows}
    eligible_ids = {sid for sid, row in by_id.items() if row["eligible"]}
    finest_eligible_id = next(
        (row["scope"].id for row in gate_rows if row["eligible"]), None
    )

    lineage_ids: set[str] = set()
    if prior_disclosed_scope_id is not None and prior_disclosed_scope_id in by_id:
        lineage_ids = {
            scope.id
            for scope in registry.chain_to_root(prior_disclosed_scope_id)
            if scope.id in by_id
        }
    lineage_eligible_ids = [sid for sid in lineage_ids if sid in eligible_ids]

    if not lineage_eligible_ids:
        # No usable incumbent (or ancestor of one) this round: plain
        # finest-eligible selection, identical to having no stability rule.
        return finest_eligible_id, {}

    stable_id = min(
        lineage_eligible_ids,
        key=lambda sid: _fineness_key(
            by_id[sid]["scope"].level, by_id[sid]["scope"].population, sid
        ),
    )
    stable_count = by_id[stable_id]["qualifying"]
    margin = config.sibling_switch_margin

    challengers = sorted(
        (
            row
            for sid, row in by_id.items()
            if row["eligible"] and sid not in lineage_ids and row["qualifying"] > stable_count + margin
        ),
        key=lambda row: _fineness_key(row["scope"].level, row["scope"].population, row["scope"].id),
    )

    notes: dict[str, str] = {}
    if challengers:
        winner = challengers[0]
        selected_id = winner["scope"].id
        notes[selected_id] = (
            f"Disclosed: qualifying count ({winner['qualifying']}) exceeded the "
            f"previously disclosed scope's ({stable_count}) by more than the "
            f"switch margin ({margin}); disclosure moved here."
        )
    else:
        selected_id = stable_id
        if stable_id == prior_disclosed_scope_id:
            notes[selected_id] = (
                "Disclosed: kept disclosing the same scope as before for "
                f"stability; no other scope exceeded it by the switch margin "
                f"({margin})."
            )
        else:
            notes[selected_id] = (
                "Disclosed: the previously disclosed scope no longer "
                "qualifies; fell back to a coarser ancestor of it for "
                "stability rather than switching to a different scope."
            )

    # Annotate scopes that lost specifically to the margin, or to a finer
    # scope within the same kept lineage.
    for sid, row in by_id.items():
        if sid == selected_id or not row["eligible"]:
            continue
        if sid in lineage_ids:
            notes[sid] = (
                "Eligible: passes both gates, but a finer scope in the same "
                "disclosure lineage was selected instead."
            )
        elif row["qualifying"] <= stable_count + margin:
            notes[sid] = (
                f"Eligible: passes both gates, but qualifying count "
                f"({row['qualifying']}) did not exceed the disclosed scope's "
                f"({stable_count}) by the required switch margin ({margin}); "
                f"kept the existing disclosure instead of switching here."
            )
        # else: eligible, outside the lineage, cleared the margin, but a
        # finer challenger won -- falls through to the default "a finer
        # scope was disclosed" reason.

    return selected_id, notes


def evaluate(
    registry: ScopeRegistry,
    qualifying_scope_counts: dict[str, int],
    *,
    config: DisclosureConfig = DEFAULT_DISCLOSURE_CONFIG,
    prior_disclosed_scope_id: str | None = None,
) -> DisclosureResult:
    """Evaluate both gates for every candidate scope and select a winner.

    ``qualifying_scope_counts`` maps a scope id to the number of qualifying
    reports in that scope's subtree (produced by the detection engine).
    Only scopes appearing as keys are candidates.

    Without ``prior_disclosed_scope_id``, the winner is simply the finest
    eligible scope (rule 9). With it, scope stability applies: the winner
    stays within the prior scope's own lineage (itself or a coarser
    ancestor of it) unless some other scope's qualifying count exceeds it
    by more than ``config.sibling_switch_margin`` -- see the module
    docstring.
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

    selected_id, stability_notes = _stable_selection(
        gate_rows, registry, prior_disclosed_scope_id, config
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
                stability_note=stability_notes.get(row["scope"].id),
            ),
        )
        for row in gate_rows
    )

    return DisclosureResult(evaluations=evaluations, disclosed_scope_id=selected_id)
