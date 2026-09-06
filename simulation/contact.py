"""Contact model: tiered transmission on a single day.

Contact is not suite-only. An infectious agent can transmit to a
susceptible agent that shares its SUITE, its FLOOR (different suite, same
floor), or its BUILDING (different floor, same building) -- at three
decreasing per-contact probabilities. Which scope an agent's suite sits
under is read from the ``ScopeRegistry`` (see :func:`suite_ancestor_ids`),
never hard-coded from id strings.
"""

from __future__ import annotations

import random
from collections import Counter

from microcluster.models import ScopeLevel, ScopeRegistry

from .agent import Agent
from .config import SimulationConfig
from .infection import INFECTIOUS_STATES, InfectionState


def suite_ancestor_ids(registry: ScopeRegistry, suite_id: str) -> tuple[str, str]:
    """Return ``(floor_id, building_id)`` for ``suite_id``, read from the
    registry's own hierarchy rather than assumed from id strings.

    If the registry has no FLOOR scope above this suite, ``floor_id``
    falls back to ``suite_id`` itself (so the floor tier contributes
    nothing, rather than guessing a structure that is not there). If it
    also has no BUILDING scope, ``building_id`` falls back to whatever
    ``floor_id`` resolved to, for the same reason.
    """
    by_level = {scope.level: scope.id for scope in registry.chain_to_root(suite_id)}
    floor_id = by_level.get(ScopeLevel.FLOOR, suite_id)
    building_id = by_level.get(ScopeLevel.BUILDING, floor_id)
    return floor_id, building_id


def new_infections(
    agents_by_suite: dict[str, list[Agent]],
    floor_of_suite: dict[str, str],
    building_of_suite: dict[str, str],
    rng: random.Random,
    config: SimulationConfig,
) -> tuple[list[Agent], list[Agent]]:
    """Given every agent grouped by suite and their CURRENT states, return
    the susceptible agents that become infected today, across all three
    contact tiers, as ``(within_suite, cross_suite)``.

    For a susceptible agent in a given suite, every infectious agent is one
    of three kinds of contact: a suite-mate, a floor-mate in a different
    suite, or a building-mate on a different floor. The agent escapes
    infection only by escaping every contact at every tier, so with
    per-contact probabilities ``p_suite``, ``p_floor``, ``p_building`` and
    contact counts ``k_suite``, ``k_floor``, ``k_building``:

        P(infected today) = 1 - (1-p_suite)**k_suite
                               * (1-p_floor)**k_floor
                               * (1-p_building)**k_building

    All susceptible agents within the same suite face the same probability
    (the three counts are suite/floor/building aggregates, not
    per-individual), so it is computed once per suite.

    A newly infected agent is reported as ``cross_suite`` if their OWN
    suite had zero infectious members (``k_suite == 0``) -- the infection
    can then only have come from a floor- or building-tier contact, never
    a suite-mate. Otherwise it is reported as ``within_suite``: its suite
    did have an infectious member, even though a floor/building contact
    may also have contributed to the same compounded probability (the
    tiers are not disentangled at the level of one infection event).
    """
    infectious_by_suite: dict[str, int] = {
        suite_id: sum(1 for a in agents if a.state in INFECTIOUS_STATES)
        for suite_id, agents in agents_by_suite.items()
    }

    infectious_by_floor: Counter[str] = Counter()
    infectious_by_building: Counter[str] = Counter()
    for suite_id, count in infectious_by_suite.items():
        if count:
            infectious_by_floor[floor_of_suite[suite_id]] += count
            infectious_by_building[building_of_suite[suite_id]] += count

    p_suite = config.suite_transmission_probability
    p_floor = config.floor_transmission_probability
    p_building = config.building_transmission_probability

    within_suite: list[Agent] = []
    cross_suite: list[Agent] = []
    for suite_id, agents in agents_by_suite.items():
        floor_id = floor_of_suite[suite_id]
        building_id = building_of_suite[suite_id]

        k_suite = infectious_by_suite[suite_id]
        k_floor = infectious_by_floor[floor_id] - k_suite
        k_building = infectious_by_building[building_id] - infectious_by_floor[floor_id]

        if k_suite == 0 and k_floor == 0 and k_building == 0:
            continue

        escape = (
            (1.0 - p_suite) ** k_suite
            * (1.0 - p_floor) ** k_floor
            * (1.0 - p_building) ** k_building
        )
        prob_infected = 1.0 - escape
        bucket = within_suite if k_suite > 0 else cross_suite

        bucket.extend(
            agent
            for agent in agents
            if agent.state is InfectionState.SUSCEPTIBLE
            and rng.random() < prob_infected
        )
    return within_suite, cross_suite
