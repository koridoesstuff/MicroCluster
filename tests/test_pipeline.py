"""End-to-end wiring tests: simulation -> reports -> the real detection
engine, unmodified.
"""

from __future__ import annotations

import unittest

from microcluster.models import ScopeLevel

from simulation.config import DEFAULT_SMOKE_SEEDS, SimulationConfig
from simulation.infection import InfectionState
from simulation.pipeline import (
    analyze_report_stream,
    run_with_detection,
    simulate_and_report,
)
from simulation.population import StructureSpec
from simulation.simulator import Simulation


class ReportsAreSuiteLevelTest(unittest.TestCase):
    def test_every_report_resolves_to_a_suite_scope(self) -> None:
        result = run_with_detection(seed=2, days=20)
        for report in result.reports:
            scope = result.simulation.registry.get(report.location_id)
            self.assertEqual(scope.level, ScopeLevel.SUITE)


class DailyRecordShapeTest(unittest.TestCase):
    def test_one_record_per_day_including_day_zero(self) -> None:
        result = run_with_detection(seed=1, days=15)
        self.assertEqual(len(result.daily_records), 16)
        self.assertEqual([r.day for r in result.daily_records], list(range(16)))

    def test_reports_accumulated_is_the_running_total(self) -> None:
        result = run_with_detection(seed=3, days=15)
        running = 0
        for record in result.daily_records:
            running += record.reports_submitted_today
            self.assertEqual(record.reports_accumulated, running)
        self.assertEqual(running, len(result.reports))

    def test_true_infected_count_matches_ground_truth_history(self) -> None:
        result = run_with_detection(seed=4, days=15)
        for record, day_state in zip(result.daily_records, result.simulation.history):
            expected = day_state.count(InfectionState.INCUBATING) + day_state.count(
                InfectionState.SYMPTOMATIC
            )
            self.assertEqual(record.true_infected_count, expected)


class TrajectoryUnperturbedTest(unittest.TestCase):
    def test_reporting_does_not_change_the_epidemic_trajectory(self) -> None:
        # Report generation uses its own RNG stream; the same seed must
        # produce the identical infection trajectory with or without it.
        plain = Simulation(seed=6, seed_infections=1).run(20)
        piped = run_with_detection(seed=6, days=20)
        self.assertEqual(
            [s.counts for s in plain],
            [s.counts for s in piped.simulation.history],
        )


class DetectionCanFireAndDiscloseTest(unittest.TestCase):
    def test_favorable_outbreak_is_detected_and_disclosed(self) -> None:
        # Deliberately easy: certain transmission, certain reporting, no
        # background noise -- if the wiring works at all, this must fire
        # and eventually name a scope.
        config = SimulationConfig(
            suite_transmission_probability=1.0,
            reporting_probability_min=1.0,
            reporting_probability_max=1.0,
            background_noise_daily_rate=0.0,
        )
        result = run_with_detection(seed=1, days=20, config=config)

        self.assertTrue(any(r.detection_fired for r in result.daily_records))
        self.assertTrue(any(r.disclosed_scope_id for r in result.daily_records))

    def test_no_reports_at_all_never_fires(self) -> None:
        config = SimulationConfig(
            reporting_probability_min=0.0,
            reporting_probability_max=0.0,
            background_noise_daily_rate=0.0,
        )
        result = run_with_detection(seed=1, days=20, config=config)

        self.assertEqual(result.reports, [])
        self.assertTrue(all(not r.detection_fired for r in result.daily_records))
        self.assertTrue(all(r.disclosed_scope_id is None for r in result.daily_records))


class DelayRecordingTest(unittest.TestCase):
    def test_first_fired_and_first_disclosed_are_recorded_and_ordered(self) -> None:
        config = SimulationConfig(
            suite_transmission_probability=1.0,
            reporting_probability_min=1.0,
            reporting_probability_max=1.0,
            background_noise_daily_rate=0.0,
        )
        result = run_with_detection(seed=1, days=20, config=config)

        fired_day = next(r.day for r in result.daily_records if r.detection_fired)
        disclosed_day = next(
            r.day for r in result.daily_records if r.disclosed_scope_id is not None
        )
        last = result.daily_records[-1]

        # The running fields on the final record must match what actually
        # happened, and disclosure can never precede firing.
        self.assertEqual(last.first_fired_day, fired_day)
        self.assertEqual(last.first_disclosed_day, disclosed_day)
        self.assertLessEqual(fired_day, disclosed_day)

    def test_before_either_happens_both_fields_are_none(self) -> None:
        result = run_with_detection(seed=1, days=1)
        first = result.daily_records[0]
        if not first.detection_fired:
            self.assertIsNone(first.first_fired_day)
        if first.disclosed_scope_id is None:
            self.assertIsNone(first.first_disclosed_day)

    def test_no_detection_ever_leaves_both_fields_none(self) -> None:
        config = SimulationConfig(
            reporting_probability_min=0.0,
            reporting_probability_max=0.0,
            background_noise_daily_rate=0.0,
        )
        result = run_with_detection(seed=1, days=20, config=config)
        last = result.daily_records[-1]
        self.assertIsNone(last.first_fired_day)
        self.assertIsNone(last.first_disclosed_day)


class ScopeStabilityAcrossARunTest(unittest.TestCase):
    """config.SIBLING_SWITCH_MARGIN, exercised over a full simulated run
    rather than a single evaluate() call."""

    def test_distinct_disclosed_scopes_stay_small_across_the_default_seeds(self) -> None:
        # The default structure has 6 suites, 2 floors, 1 building, 1
        # campus -- 10 possible scopes. Without stability, a wandering
        # outbreak can (and, before this change, did) name most of them
        # over a 30-day run. With it, each run should settle on very few.
        for seed in DEFAULT_SMOKE_SEEDS:
            with self.subTest(seed=seed):
                result = run_with_detection(seed=seed, days=30)
                distinct = result.distinct_disclosed_scopes()
                self.assertLessEqual(
                    len(distinct), 3, f"seed {seed} disclosed too many scopes: {distinct}"
                )

    def test_a_named_scope_persists_across_consecutive_disclosing_days(self) -> None:
        # Once something is disclosed, most consecutive disclosing days
        # should repeat it rather than naming something new each time.
        found_a_run_with_multiple_disclosures = False
        for seed in DEFAULT_SMOKE_SEEDS:
            result = run_with_detection(seed=seed, days=30)
            sequence = [r.disclosed_scope_id for r in result.daily_records if r.disclosed_scope_id]
            if len(sequence) < 2:
                continue
            found_a_run_with_multiple_disclosures = True
            changes = sum(1 for a, b in zip(sequence, sequence[1:]) if a != b)
            self.assertLess(
                changes, len(sequence), f"seed {seed}: every disclosing day changed scope"
            )
        self.assertTrue(found_a_run_with_multiple_disclosures)


class TwoPhaseEquivalenceTest(unittest.TestCase):
    """run_with_detection == simulate_and_report + analyze_report_stream.
    The split exists so an experiment can simulate a seed once and replay
    the analysis under many configs; it must not change the result."""

    def test_split_matches_the_combined_call(self) -> None:
        combined = run_with_detection(seed=3, days=25)

        simulated = simulate_and_report(seed=3, days=25)
        replayed = analyze_report_stream(simulated)

        self.assertEqual(combined.daily_records, replayed)
        self.assertEqual(
            [s.counts for s in combined.simulation.history],
            [s.counts for s in simulated.simulation.history],
        )

    def test_one_simulation_replayed_under_two_configs(self) -> None:
        from microcluster.config import DisclosureConfig

        simulated = simulate_and_report(seed=4, days=25)
        loose = analyze_report_stream(
            simulated, disclosure_config=DisclosureConfig(min_scope_population=10)
        )
        strict = analyze_report_stream(
            simulated, disclosure_config=DisclosureConfig(min_scope_population=200)
        )
        # Same epidemic, different disclosure gate -> the strict one names
        # nothing, the loose one may.
        self.assertTrue(all(r.disclosed_scope_id is None for r in strict))
        self.assertEqual(len(loose), len(strict))


class SmallStructureStillPassesPrivacyGateTest(unittest.TestCase):
    def test_custom_structure_runs_end_to_end(self) -> None:
        spec = StructureSpec(
            buildings=1, floors_per_building=1, suites_per_floor=2, agents_per_suite=25
        )
        result = run_with_detection(seed=1, days=10, spec=spec)
        self.assertEqual(len(result.simulation.agents), 50)


if __name__ == "__main__":
    unittest.main()
