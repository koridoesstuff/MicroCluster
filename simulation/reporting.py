"""Turns simulated infection state into anonymous Reports.

This is the ONLY bridge between the simulator's ground truth and the
production ``microcluster`` engines. Only two facts survive the crossing:
which SUITE an agent is in, and whether they feel like filing a report
today. Everything else the simulator knows -- who is actually infected,
since when, who infected whom -- stays on this side of the line (see
CLAUDE.md, "The ground-truth firewall").

Two kinds of reports are generated each day:

  * OUTBREAK reports -- from agents SYMPTOMATIC with the real illness, at
    most once per episode, in the single configured outbreak category.
  * BACKGROUND NOISE -- from agents who are NOT currently symptomatic,
    independently each day, in a category other than the outbreak's. This
    is what makes the detection problem real: without it, every report in
    the stream would be outbreak signal.
"""

from __future__ import annotations

import random
from datetime import timedelta

from microcluster.models import CHECKLIST, Category, Onset, Report

from .agent import Agent
from .config import SimulationConfig
from .infection import InfectionState

# Every fixed-checklist category except whichever one the outbreak is
# using, for drawing a background-noise report's category.
_ALL_CATEGORIES: tuple[Category, ...] = tuple(Category)


def _non_outbreak_categories(outbreak_category: Category) -> tuple[Category, ...]:
    return tuple(c for c in _ALL_CATEGORIES if c != outbreak_category)


def _onset_for(days_symptomatic: int) -> Onset:
    """Coarse onset bucket (rule 1), computed from how many days an agent
    has been symptomatic -- what a real reporter would say if asked."""
    if days_symptomatic <= 0:
        return Onset.TODAY
    if days_symptomatic <= 2:
        return Onset.ONE_TO_TWO_DAYS
    if days_symptomatic <= 7:
        return Onset.THREE_TO_SEVEN_DAYS
    return Onset.ONE_WEEK_PLUS


def generate_daily_reports(
    agents: list[Agent],
    day: int,
    rng: random.Random,
    config: SimulationConfig,
) -> list[Report]:
    """Every report filed on simulated ``day``.

    Mutates ``agent.has_reported`` in place when an outbreak report is
    filed, so the same episode is never reported twice. ``rng`` should be
    a stream dedicated to reporting, kept separate from the simulation's
    own transmission/progression stream so that adding report generation
    never perturbs the epidemic trajectory itself.
    """
    submitted_at = config.simulation_start + timedelta(days=day)
    noise_categories = _non_outbreak_categories(config.outbreak_category)
    reports: list[Report] = []

    for agent in agents:
        if agent.state is InfectionState.SYMPTOMATIC:
            if agent.has_reported:
                continue
            if rng.random() < agent.reporting_probability:
                days_symptomatic = day - agent.state_changed_day
                symptom = rng.choice(CHECKLIST[config.outbreak_category])
                reports.append(
                    Report(
                        category=config.outbreak_category,
                        symptom=symptom,
                        onset=_onset_for(days_symptomatic),
                        location_id=agent.suite_id,
                        submitted_at=submitted_at,
                    )
                )
                agent.has_reported = True
            continue

        # Not currently symptomatic with the real illness: a chance of an
        # ordinary, unrelated report, independent of any episode.
        if rng.random() < config.background_noise_daily_rate:
            category = rng.choice(noise_categories)
            reports.append(
                Report(
                    category=category,
                    symptom=rng.choice(CHECKLIST[category]),
                    onset=rng.choice(list(Onset)),
                    location_id=agent.suite_id,
                    submitted_at=submitted_at,
                )
            )

    return reports
