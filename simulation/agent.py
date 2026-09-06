"""The Agent: one simulated person."""

from __future__ import annotations

from dataclasses import dataclass

from .infection import InfectionState


@dataclass
class Agent:
    """One simulated person.

    An agent belongs to exactly one suite. Every ``Report`` it produces
    (see ``simulation.reporting``) uses ``suite_id`` as the
    ``location_id`` -- always, and only that (detection.evaluate rejects
    mixed-level input).

    ``incubation_days`` / ``symptomatic_days`` are drawn when the agent is
    infected and are ``None`` before then.
    """

    id: str
    suite_id: str
    # Personal probability of filing a report while SYMPTOMATIC. Not
    # everyone reports; assigned once at population creation.
    reporting_probability: float
    state: InfectionState = InfectionState.SUSCEPTIBLE
    # Day on which ``state`` last changed (0 = start of the run).
    state_changed_day: int = 0
    incubation_days: int | None = None
    symptomatic_days: int | None = None
    # Whether this agent has already filed its (at most one) report for
    # the current illness episode. Reports are anonymous, so this flag
    # lives only here -- it never appears on a Report.
    has_reported: bool = False

    def __post_init__(self) -> None:
        if not 0.0 <= self.reporting_probability <= 1.0:
            raise ValueError(
                f"agent {self.id}: reporting_probability "
                f"{self.reporting_probability!r} is outside [0, 1]"
            )


@dataclass(frozen=True)
class AgentSnapshot:
    """Immutable view of one agent at the end of a simulated day."""

    id: str
    suite_id: str
    state: InfectionState
    state_changed_day: int
