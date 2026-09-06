"""Headless outbreak simulator.

Simulates an illness spreading suite-by-suite through a small shared
building, generates anonymous symptom reports from it, and feeds them to
``microcluster``'s existing, unmodified detection engine. No rendering, no
API, no frontend.

It only ever *reads* from ``microcluster`` (``models``, ``config``,
``engine``) and never modifies it. See ``simulation.pipeline`` for the
end-to-end wiring, and CLAUDE.md's "ground-truth firewall" for what is and
is not allowed to cross from this package into the production engines.
"""

from . import agent, config, contact, infection, pipeline, population, reporting, simulator
from .agent import Agent, AgentSnapshot
from .config import DEFAULT_SIMULATION_CONFIG, SimulationConfig
from .infection import INFECTIOUS_STATES, STATE_ORDER, InfectionState, order_index
from .pipeline import (
    DailyRecord,
    SimulatedReports,
    SimulationRun,
    analyze_report_stream,
    run_with_detection,
    simulate_and_report,
)
from .population import StructureSpec, build_population
from .simulator import DayState, Simulation

__all__ = [
    "agent",
    "config",
    "contact",
    "infection",
    "pipeline",
    "population",
    "reporting",
    "simulator",
    "Agent",
    "AgentSnapshot",
    "SimulationConfig",
    "DEFAULT_SIMULATION_CONFIG",
    "InfectionState",
    "STATE_ORDER",
    "INFECTIOUS_STATES",
    "order_index",
    "StructureSpec",
    "build_population",
    "Simulation",
    "DayState",
    "DailyRecord",
    "SimulationRun",
    "SimulatedReports",
    "simulate_and_report",
    "analyze_report_stream",
    "run_with_detection",
]
