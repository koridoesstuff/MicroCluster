"""Smoke test entry point.

Run the default 150-agent structure, seeded with one infection, for
DEFAULT_RUN_DAYS days, across DEFAULT_SMOKE_SEEDS random seeds. For each
seed, print the daily per-state counts, then a one-line summary: peak
infected and the day it occurred, the seeded suite's final attack rate,
and how many distinct suites and floors were ever touched.

    python -m simulation.smoke
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simulation.config import (  # noqa: E402
    DEFAULT_RUN_DAYS,
    DEFAULT_SEED_INFECTIONS,
    DEFAULT_SMOKE_SEEDS,
)
from simulation.contact import suite_ancestor_ids  # noqa: E402
from simulation.infection import STATE_ORDER, InfectionState  # noqa: E402
from simulation.simulator import DayState, Simulation  # noqa: E402


def _peak(history: list[DayState]) -> tuple[int, int]:
    """(peak simultaneously-infectious count, day it was first reached)."""
    peak_count = -1
    peak_day = 0
    for snapshot in history:
        infectious_now = snapshot.count(InfectionState.INCUBATING) + snapshot.count(
            InfectionState.SYMPTOMATIC
        )
        if infectious_now > peak_count:
            peak_count = infectious_now
            peak_day = snapshot.day
    return peak_count, peak_day


def _summary(sim: Simulation, history: list[DayState]) -> str:
    # Identify the seeded suite from day 0, BEFORE any spread -- by the
    # end of the run other suites may also have non-susceptible agents.
    seeded_suite = next(
        a.suite_id for a in history[0].agents if a.state is not InfectionState.SUSCEPTIBLE
    )
    peak_count, peak_day = _peak(history)

    final = history[-1]
    suite_population = sum(1 for s in final.agents if s.suite_id == seeded_suite)
    suite_ever_infected = sum(
        1
        for s in final.agents
        if s.suite_id == seeded_suite and s.state is not InfectionState.SUSCEPTIBLE
    )
    attack_rate = suite_ever_infected / suite_population * 100

    touched_suites: set[str] = set()
    touched_floors: set[str] = set()
    for snapshot in history:
        for agent_snapshot in snapshot.agents:
            if agent_snapshot.state is not InfectionState.SUSCEPTIBLE:
                touched_suites.add(agent_snapshot.suite_id)
    for suite_id in touched_suites:
        floor_id, _building_id = suite_ancestor_ids(sim.registry, suite_id)
        touched_floors.add(floor_id)

    return (
        f"  peak infected      : {peak_count} on day {peak_day}\n"
        f"  attack rate (seeded suite, n={suite_population}): {attack_rate:.1f}%\n"
        f"  suites ever touched: {len(touched_suites)}\n"
        f"  floors ever touched: {len(touched_floors)}"
    )


def _print_run(seed: int, days: int) -> None:
    sim = Simulation(seed=seed, seed_infections=DEFAULT_SEED_INFECTIONS)
    history = sim.run(days)

    columns = [state.name for state in STATE_ORDER]
    header = "day  " + "  ".join(f"{name:>11}" for name in columns)
    print(
        f"SEED {seed}   {len(sim.agents)} agents, "
        f"{DEFAULT_SEED_INFECTIONS} seeded, {days} days"
    )
    print(header)
    print("-" * len(header))
    for snapshot in history:
        cells = "  ".join(f"{snapshot.count(state):>11}" for state in STATE_ORDER)
        print(f"{snapshot.day:>3}  {cells}")
    print()
    print(_summary(sim, history))
    print()


def main() -> None:
    for seed in DEFAULT_SMOKE_SEEDS:
        _print_run(seed, DEFAULT_RUN_DAYS)


if __name__ == "__main__":
    main()
