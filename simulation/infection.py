"""Infection state machine.

    SUSCEPTIBLE -> INCUBATING -> SYMPTOMATIC -> RECOVERED

States progress in that order, one step at a time, and never move
backwards. :func:`set_state` is the single choke point that enforces it.
"""

from __future__ import annotations

import random
from enum import Enum
from typing import TYPE_CHECKING

from .config import SimulationConfig

if TYPE_CHECKING:  # avoid an import cycle; only needed for type checkers
    from .agent import Agent


class InfectionState(Enum):
    SUSCEPTIBLE = "susceptible"
    INCUBATING = "incubating"
    SYMPTOMATIC = "symptomatic"
    RECOVERED = "recovered"


# The only permitted progression. Position in this tuple defines "forward".
STATE_ORDER: tuple[InfectionState, ...] = (
    InfectionState.SUSCEPTIBLE,
    InfectionState.INCUBATING,
    InfectionState.SYMPTOMATIC,
    InfectionState.RECOVERED,
)

# States in which an agent can transmit to a susceptible suite-mate.
INFECTIOUS_STATES: frozenset[InfectionState] = frozenset(
    {InfectionState.INCUBATING, InfectionState.SYMPTOMATIC}
)


def order_index(state: InfectionState) -> int:
    """Position of ``state`` in :data:`STATE_ORDER`."""
    return STATE_ORDER.index(state)


def set_state(agent: "Agent", new_state: InfectionState, day: int) -> None:
    """Advance ``agent`` to ``new_state`` and stamp the day of the change.

    Raises ``ValueError`` unless ``new_state`` is the state immediately
    after the agent's current one in :data:`STATE_ORDER`: the machine only
    ever steps forward, and only by one.
    """
    current = order_index(agent.state)
    target = order_index(new_state)
    if target != current + 1:
        raise ValueError(
            f"agent {agent.id}: illegal transition "
            f"{agent.state.value} -> {new_state.value} "
            f"(states move one step forward only, never back or skipping)"
        )
    agent.state = new_state
    agent.state_changed_day = day


def infect(
    agent: "Agent", day: int, rng: random.Random, config: SimulationConfig
) -> None:
    """SUSCEPTIBLE -> INCUBATING. Draws this agent's incubation and
    symptomatic durations up front, from the configured ranges."""
    set_state(agent, InfectionState.INCUBATING, day)
    agent.incubation_days = rng.randint(
        config.incubation_days_min, config.incubation_days_max
    )
    agent.symptomatic_days = rng.randint(
        config.symptomatic_days_min, config.symptomatic_days_max
    )


def advance_time_based(agent: "Agent", day: int) -> bool:
    """Apply the time-driven transitions:

    * INCUBATING -> SYMPTOMATIC once ``incubation_days`` have elapsed,
    * SYMPTOMATIC -> RECOVERED once ``symptomatic_days`` have elapsed.

    At most one transition per call. Returns True if the agent changed
    state. SUSCEPTIBLE and RECOVERED agents are untouched.
    """
    if agent.state is InfectionState.INCUBATING:
        if day - agent.state_changed_day >= agent.incubation_days:
            set_state(agent, InfectionState.SYMPTOMATIC, day)
            return True
    elif agent.state is InfectionState.SYMPTOMATIC:
        if day - agent.state_changed_day >= agent.symptomatic_days:
            set_state(agent, InfectionState.RECOVERED, day)
            return True
    return False
