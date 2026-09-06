"""Population and scope-registry builder.

Given a structure spec, produce the agents together with a matching
``microcluster.models.ScopeRegistry`` whose every declared population is
the *actual* number of agents beneath that scope (rule 7 in CLAUDE.md:
declared populations are set at group creation, not counted from reports --
here "group creation" is this function, and it counts agents, not
reports).

Binding constraint (CLAUDE.md SIMULATION section): agents live in suites.
Any Report generated later uses the agent's SUITE id as ``location_id``.
The coarser scopes (FLOOR, BUILDING, CAMPUS) exist here only so that
``registry.chain_to_root`` can reach them.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass

from microcluster.config import MIN_SCOPE_POPULATION
from microcluster.models import Scope, ScopeLevel, ScopeRegistry

from . import config as simconfig
from .agent import Agent
from .config import DEFAULT_SIMULATION_CONFIG, SimulationConfig


@dataclass(frozen=True)
class StructureSpec:
    """How many of each scope, and how many agents per suite. The defaults
    give the 150-agent smoke-test structure."""

    buildings: int = simconfig.DEFAULT_BUILDINGS
    floors_per_building: int = simconfig.DEFAULT_FLOORS_PER_BUILDING
    suites_per_floor: int = simconfig.DEFAULT_SUITES_PER_FLOOR
    agents_per_suite: int = simconfig.DEFAULT_AGENTS_PER_SUITE


def _validate_spec(spec: StructureSpec) -> None:
    for name, value in vars(spec).items():
        if value <= 0:
            raise ValueError(f"StructureSpec.{name} must be positive, got {value!r}")
    if spec.agents_per_suite <= MIN_SCOPE_POPULATION:
        raise ValueError(
            f"agents_per_suite ({spec.agents_per_suite}) must exceed "
            f"MIN_SCOPE_POPULATION ({MIN_SCOPE_POPULATION}); at or below it the "
            f"privacy gate can never pass at suite level, so a suite-level "
            f"disclosure would be structurally impossible."
        )


def build_population(
    spec: StructureSpec | None = None,
    rng: random.Random | None = None,
    config: SimulationConfig = DEFAULT_SIMULATION_CONFIG,
) -> tuple[list[Agent], ScopeRegistry]:
    """Build the agent list and the matching ``ScopeRegistry``.

    ``rng`` seeds the per-agent reporting-probability draws; pass an
    explicit ``random.Random`` for reproducibility.
    """
    spec = spec or StructureSpec()
    _validate_spec(spec)
    rng = rng or random.Random()

    campus_id = config.campus_scope_id
    parent_of: dict[str, str] = {}
    building_ids: list[str] = []
    floor_ids: list[str] = []
    suite_ids: list[str] = []
    agents: list[Agent] = []

    for b in range(1, spec.buildings + 1):
        building_id = f"{campus_id}-B{b}"
        building_ids.append(building_id)
        parent_of[building_id] = campus_id
        for f in range(1, spec.floors_per_building + 1):
            floor_id = f"{building_id}-F{f}"
            floor_ids.append(floor_id)
            parent_of[floor_id] = building_id
            for s in range(1, spec.suites_per_floor + 1):
                suite_id = f"{floor_id}-S{s}"
                suite_ids.append(suite_id)
                parent_of[suite_id] = floor_id
                for a in range(1, spec.agents_per_suite + 1):
                    agents.append(
                        Agent(
                            id=f"{suite_id}-A{a}",
                            suite_id=suite_id,
                            reporting_probability=rng.uniform(
                                config.reporting_probability_min,
                                config.reporting_probability_max,
                            ),
                        )
                    )

    # Declared population of a scope == number of agents beneath it. Walk
    # each agent's suite up to the campus root, counting as we go.
    population: Counter[str] = Counter()
    for agent in agents:
        node = agent.suite_id
        while True:
            population[node] += 1
            if node == campus_id:
                break
            node = parent_of[node]

    scopes: dict[str, Scope] = {
        campus_id: Scope(
            id=campus_id,
            label=config.campus_label,
            level=ScopeLevel.CAMPUS,
            population=population[campus_id],
        )
    }
    for building_id in building_ids:
        scopes[building_id] = Scope(
            id=building_id,
            label=building_id,
            level=ScopeLevel.BUILDING,
            population=population[building_id],
            parent_id=parent_of[building_id],
        )
    for floor_id in floor_ids:
        scopes[floor_id] = Scope(
            id=floor_id,
            label=floor_id,
            level=ScopeLevel.FLOOR,
            population=population[floor_id],
            parent_id=parent_of[floor_id],
        )
    for suite_id in suite_ids:
        scopes[suite_id] = Scope(
            id=suite_id,
            label=suite_id,
            level=ScopeLevel.SUITE,
            population=population[suite_id],
            parent_id=parent_of[suite_id],
        )

    registry = ScopeRegistry(scopes)  # runs ScopeRegistry's own validation
    return agents, registry
