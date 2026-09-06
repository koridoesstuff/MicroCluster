"""The run loop.

Step one simulated day at a time. After every step the full world state
is captured as a :class:`DayState` (per-state counts plus an immutable
snapshot of every agent) and appended to ``history`` so a run can be
recorded, replayed, or rendered later.

Contact is tiered (suite / floor / building), not suite-only -- see
``simulation.contact``. Each suite's floor and building ids are resolved
once, through the ``ScopeRegistry``, and reused every step.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from microcluster.models import ScopeRegistry

from . import contact, infection
from .contact import suite_ancestor_ids
from .agent import Agent, AgentSnapshot
from .config import DEFAULT_SIMULATION_CONFIG, SimulationConfig
from .infection import STATE_ORDER, InfectionState
from .population import StructureSpec, build_population


@dataclass(frozen=True)
class DayState:
    """The whole simulated world at the end of one day."""

    day: int
    counts: dict[InfectionState, int]
    agents: tuple[AgentSnapshot, ...]

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def count(self, state: InfectionState) -> int:
        return self.counts[state]


class Simulation:
    """One outbreak run. Fully determined by ``seed`` (given the same
    ``spec`` and ``config``)."""

    def __init__(
        self,
        *,
        seed: int,
        spec: StructureSpec | None = None,
        config: SimulationConfig = DEFAULT_SIMULATION_CONFIG,
        seed_infections: int | None = None,
    ) -> None:
        self.config = config
        self.spec = spec or StructureSpec()
        self.rng = random.Random(seed)
        self.agents: list[Agent]
        self.registry: ScopeRegistry
        self.agents, self.registry = build_population(self.spec, self.rng, config)

        self._suites: dict[str, list[Agent]] = {}
        for agent in self.agents:
            self._suites.setdefault(agent.suite_id, []).append(agent)

        # Where each suite sits in the hierarchy, read once from the
        # registry (never hard-coded from id strings) and reused every step.
        self._floor_of_suite: dict[str, str] = {}
        self._building_of_suite: dict[str, str] = {}
        for suite_id in self._suites:
            floor_id, building_id = suite_ancestor_ids(self.registry, suite_id)
            self._floor_of_suite[suite_id] = floor_id
            self._building_of_suite[suite_id] = building_id

        self.day = 0
        requested = (
            config.seed_infections if seed_infections is None else seed_infections
        )
        self._seed_infections(requested)

        # Running totals, split by contact tier that caused the infection
        # (see contact.new_infections). Useful for measuring how much of an
        # outbreak stayed within its starting suite versus spread further.
        self.total_within_suite_infections = 0
        self.total_cross_suite_infections = 0

        self.history: list[DayState] = [self._snapshot()]

    # -- setup ---------------------------------------------------------

    def _seed_infections(self, n: int) -> None:
        if n < 0:
            raise ValueError("seed_infections must be >= 0")
        if n > len(self.agents):
            raise ValueError(
                f"cannot seed {n} infections in a population of {len(self.agents)}"
            )
        for agent in self.rng.sample(self.agents, n):
            infection.infect(agent, self.day, self.rng, self.config)

    # -- stepping ----------------------------------------------------

    def step(self) -> DayState:
        """Advance one day.

        Order within the step:

        1. Decide new infections from the START-OF-DAY state, so an agent
           infected today cannot also transmit or progress today.
        2. Apply time-based progression (INCUBATING -> SYMPTOMATIC ->
           RECOVERED) to everyone.
        3. Apply the new infections (SUSCEPTIBLE -> INCUBATING).

        Returns the resulting :class:`DayState`, also appended to
        ``history``.
        """
        self.day += 1
        day = self.day

        within_suite, cross_suite = contact.new_infections(
            self._suites, self._floor_of_suite, self._building_of_suite,
            self.rng, self.config,
        )
        self.total_within_suite_infections += len(within_suite)
        self.total_cross_suite_infections += len(cross_suite)
        newly_infected = within_suite + cross_suite

        for agent in self.agents:
            infection.advance_time_based(agent, day)

        for agent in newly_infected:
            infection.infect(agent, day, self.rng, self.config)

        snapshot = self._snapshot()
        self.history.append(snapshot)
        return snapshot

    def run(self, days: int) -> list[DayState]:
        """Step ``days`` times; return the full history (day 0 .. day
        ``days``)."""
        if days < 0:
            raise ValueError("days must be >= 0")
        for _ in range(days):
            self.step()
        return self.history

    # -- snapshot ----------------------------------------------------

    def _snapshot(self) -> DayState:
        counts: dict[InfectionState, int] = {state: 0 for state in STATE_ORDER}
        agent_snapshots: list[AgentSnapshot] = []
        for agent in self.agents:
            counts[agent.state] += 1
            agent_snapshots.append(
                AgentSnapshot(
                    id=agent.id,
                    suite_id=agent.suite_id,
                    state=agent.state,
                    state_changed_day=agent.state_changed_day,
                )
            )
        return DayState(day=self.day, counts=counts, agents=tuple(agent_snapshots))
