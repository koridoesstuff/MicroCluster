"""Report generation: the one place simulated agents turn into anonymous
``microcluster.models.Report`` objects."""

from __future__ import annotations

import random
import unittest

from microcluster.models import CHECKLIST, Category

from simulation.agent import Agent
from simulation.config import SimulationConfig
from simulation.infection import InfectionState
from simulation.reporting import generate_daily_reports


def _symptomatic_agent(**overrides) -> Agent:
    kwargs = dict(
        id="A1",
        suite_id="S1",
        reporting_probability=1.0,
        state=InfectionState.SYMPTOMATIC,
        state_changed_day=0,
        incubation_days=2,
        symptomatic_days=5,
    )
    kwargs.update(overrides)
    return Agent(**kwargs)


class OutbreakReportTest(unittest.TestCase):
    def test_symptomatic_agent_reports_in_the_suite_and_outbreak_category(self) -> None:
        config = SimulationConfig()
        agent = _symptomatic_agent(reporting_probability=1.0)
        reports = generate_daily_reports([agent], 0, random.Random(0), config)

        self.assertEqual(len(reports), 1)
        report = reports[0]
        self.assertEqual(report.location_id, agent.suite_id)
        self.assertEqual(report.category, config.outbreak_category)
        self.assertIn(report.symptom, CHECKLIST[config.outbreak_category])
        self.assertTrue(agent.has_reported)

    def test_zero_reporting_probability_never_reports(self) -> None:
        config = SimulationConfig()
        agent = _symptomatic_agent(reporting_probability=0.0)
        reports = generate_daily_reports([agent], 0, random.Random(0), config)

        self.assertEqual(reports, [])
        self.assertFalse(agent.has_reported)

    def test_agent_reports_at_most_once_per_episode(self) -> None:
        config = SimulationConfig()
        agent = _symptomatic_agent(reporting_probability=1.0, state_changed_day=0)
        rng = random.Random(0)

        all_reports = []
        for day in range(4):  # still SYMPTOMATIC every one of these days
            all_reports += generate_daily_reports([agent], day, rng, config)

        self.assertEqual(len(all_reports), 1)

    def test_onset_bucket_reflects_days_symptomatic(self) -> None:
        config = SimulationConfig()
        agent = _symptomatic_agent(reporting_probability=1.0, state_changed_day=5)
        # Report generated on day 12 -> 7 days symptomatic -> "3-7 days".
        reports = generate_daily_reports([agent], 12, random.Random(0), config)
        self.assertEqual(reports[0].onset.value, "3-7 days")


class BackgroundNoiseTest(unittest.TestCase):
    def test_noise_report_uses_a_non_outbreak_category(self) -> None:
        config = SimulationConfig(background_noise_daily_rate=1.0)
        for state in (
            InfectionState.SUSCEPTIBLE,
            InfectionState.INCUBATING,
            InfectionState.RECOVERED,
        ):
            with self.subTest(state=state):
                agent = Agent(
                    id="A2", suite_id="S1", reporting_probability=0.5, state=state
                )
                reports = generate_daily_reports([agent], 3, random.Random(1), config)
                self.assertEqual(len(reports), 1)
                self.assertNotEqual(reports[0].category, config.outbreak_category)
                self.assertIn(reports[0].symptom, CHECKLIST[reports[0].category])
                self.assertEqual(reports[0].location_id, agent.suite_id)

    def test_zero_rate_never_generates_noise(self) -> None:
        config = SimulationConfig(background_noise_daily_rate=0.0)
        agent = Agent(id="A3", suite_id="S1", reporting_probability=0.5)
        reports = generate_daily_reports([agent], 0, random.Random(2), config)
        self.assertEqual(reports, [])

    def test_symptomatic_agent_does_not_also_generate_noise(self) -> None:
        # A symptomatic agent's chance is entirely the outbreak-report
        # roll; it must not separately roll for background noise too.
        config = SimulationConfig(background_noise_daily_rate=1.0)
        agent = _symptomatic_agent(reporting_probability=0.0)  # never files
        reports = generate_daily_reports([agent], 0, random.Random(3), config)
        self.assertEqual(reports, [])


if __name__ == "__main__":
    unittest.main()
