"""What the intake submission cap actually buys against report injection.

An attacker wants the system to disclose a cluster that is not real, at a
scope of their choosing. They fabricate reports: a fixed category, tagged
to suites under the target scope, all inside one detection window, each
carrying a ``session_id`` the attacker picks freely.

This module measures the cost of that attack with and without
``microcluster.intake``'s per-session cap in force. The result is
deliberately unflattering: the cap does not reduce the number of
fabricated reports required, it only forces the attacker to spread them
across ``ceil(reports / session_cap)`` sessions instead of one. A
``session_id`` is an unauthenticated, client-chosen string, so that is a
near-zero cost for a determined attacker. The cap stops a naive
single-session flood and nothing more.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timezone

from microcluster.config import DEFAULT_INTAKE_CONFIG, IntakeConfig
from microcluster.engine import analyze
from microcluster.models import CHECKLIST, Category, Onset, Report, ScopeLevel, ScopeRegistry
from simulation.population import StructureSpec, build_population

_WINDOW_INSTANT = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
_FAKE_CATEGORY = Category.GASTROINTESTINAL
_FAKE_SYMPTOM = CHECKLIST[_FAKE_CATEGORY][0]

# Cap per suite when the target is a FLOOR, so no single suite clears its
# own (finer) statistical gate and the disclosure that appears is the
# floor -- not a suite the attacker did not aim at. ceil(sqrt(25)) = 5, so
# 4 per suite is the most that keeps every suite gate failing.
_PER_SUITE_MAX_FOR_FLOOR = 4


@dataclass(frozen=True)
class InjectionResult:
    target_scope_id: str
    target_level: str
    target_population: int

    reports_to_disclose: int          # fabricated reports needed, cap or no cap
    sessions_without_cap: int         # = 1
    sessions_with_cap: int            # = ceil(reports / session_submission_cap)
    session_cap: int

    single_session_attack_succeeds: bool   # attacker uses ONE session, cap on
    multi_session_attack_succeeds: bool     # attacker uses ceil(k/cap) sessions, cap on


def _suites_under(registry: ScopeRegistry, scope_id: str) -> list[str]:
    target = registry.get(scope_id)
    if target.level is ScopeLevel.SUITE:
        return [scope_id]
    return sorted(
        s.id for s in registry.scopes.values()
        if s.level is ScopeLevel.SUITE and registry.contains(scope_id, s.id)
    )


def _fabricate(
    suites: list[str], n_reports: int, per_suite_max: int, session_ids: list[str | None]
) -> list[Report]:
    reports: list[Report] = []
    per_suite = {s: 0 for s in suites}
    si = 0
    while len(reports) < n_reports:
        suite = suites[si % len(suites)]
        si += 1
        if per_suite[suite] >= per_suite_max:
            if all(per_suite[s] >= per_suite_max for s in suites):
                break
            continue
        per_suite[suite] += 1
        reports.append(
            Report(
                category=_FAKE_CATEGORY,
                symptom=_FAKE_SYMPTOM,
                onset=Onset.TODAY,
                location_id=suite,
                submitted_at=_WINDOW_INSTANT,
                session_id=session_ids[len(reports) % len(session_ids)],
            )
        )
    return reports


def _discloses_target(
    reports: list[Report], registry: ScopeRegistry, target_scope_id: str,
    intake_config: IntakeConfig | None,
) -> bool:
    result = analyze(reports, registry, now=_WINDOW_INSTANT, intake_config=intake_config)
    return result.disclosure.disclosed_scope_id == target_scope_id


def measure_injection(
    target_scope_id: str = "C-B1-F2",
    *,
    intake_config: IntakeConfig = DEFAULT_INTAKE_CONFIG,
    max_reports: int = 60,
) -> InjectionResult:
    """Measure the injection attack against ``target_scope_id`` (a FLOOR by
    default -- the representative mid scope, declared population 75)."""
    _, registry = build_population(spec=StructureSpec(), rng=random.Random(0))
    target = registry.get(target_scope_id)
    suites = _suites_under(registry, target_scope_id)
    per_suite_max = (
        max_reports if target.level is ScopeLevel.SUITE else _PER_SUITE_MAX_FOR_FLOOR
    )
    cap = intake_config.session_submission_cap

    # 1. reports needed when the attacker is NOT rate-limited (one session,
    #    or none): smallest k whose fabricated reports name the target.
    reports_needed = 0
    for k in range(1, max_reports + 1):
        fab = _fabricate(suites, k, per_suite_max, session_ids=[None])
        if len(fab) < k:
            break  # ran out of room under per_suite_max
        if _discloses_target(fab, registry, target_scope_id, intake_config=None):
            reports_needed = k
            break
    if reports_needed == 0:
        raise RuntimeError(f"could not manufacture a disclosure at {target_scope_id}")

    sessions_with_cap = math.ceil(reports_needed / cap)

    # 2. cap ON, attacker uses ONE session -> only `cap` reports survive.
    one_session = _fabricate(
        suites, reports_needed, per_suite_max, session_ids=["attacker-1"]
    )
    single_ok = _discloses_target(
        one_session, registry, target_scope_id, intake_config=intake_config
    )

    # 3. cap ON, attacker uses ceil(k/cap) sessions -> all reports survive.
    sids: list[str | None] = [
        f"attacker-{i // cap}" for i in range(reports_needed)
    ]
    many_sessions = _fabricate(suites, reports_needed, per_suite_max, session_ids=sids)
    multi_ok = _discloses_target(
        many_sessions, registry, target_scope_id, intake_config=intake_config
    )

    return InjectionResult(
        target_scope_id=target_scope_id,
        target_level=target.level.name,
        target_population=target.population,
        reports_to_disclose=reports_needed,
        sessions_without_cap=1,
        sessions_with_cap=sessions_with_cap,
        session_cap=cap,
        single_session_attack_succeeds=single_ok,
        multi_session_attack_succeeds=multi_ok,
    )


def format_result(r: InjectionResult) -> str:
    return "\n".join([
        "=" * 78,
        f"REPORT-INJECTION ATTACK   target {r.target_scope_id} "
        f"({r.target_level}, declared population {r.target_population})",
        "=" * 78,
        "",
        f"  fabricated reports to manufacture the disclosure : {r.reports_to_disclose}",
        f"    (the statistical gate for this scope; the cap does not change it)",
        "",
        f"  sources needed, NO per-session cap               : "
        f"{r.sessions_without_cap}",
        f"  sources needed, per-session cap = {r.session_cap}              : "
        f"{r.sessions_with_cap}   (= ceil({r.reports_to_disclose} / {r.session_cap}))",
        "",
        f"  cap on, attacker uses 1 session  -> disclosure?  : "
        f"{'YES' if r.single_session_attack_succeeds else 'NO (attack blocked)'}",
        f"  cap on, attacker uses {r.sessions_with_cap} sessions -> disclosure?  : "
        f"{'YES (attack succeeds)' if r.multi_session_attack_succeeds else 'NO'}",
        "",
        "HONEST READ",
        "  The cap stops a single-session flood. It does not stop the attack: a",
        f"  session_id is a free, unauthenticated string, and ceil(k / {r.session_cap}) of them",
        "  is a near-zero cost. Injection is possible for any attacker willing to",
        "  rotate sessions. Closing this needs identity or session binding, which the",
        "  system deliberately does not have.",
    ])


def main() -> None:
    print(format_result(measure_injection()))


if __name__ == "__main__":
    main()
