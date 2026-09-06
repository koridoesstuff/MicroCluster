"""Experiment-runner tests.

Aggregation logic (summarize_setting, fizzle_rate, adjacent_duplicate_rows)
is tested against hand-built RunOutcome fixtures -- fast, exact, no
simulation needed. A couple of small, short integration runs exercise the
sweep end to end without paying for the full 500-seed default.
"""

from __future__ import annotations

import unittest

from microcluster.models import ScopeLevel

from microcluster.config import DisclosureConfig

from simulation.experiments import (
    RunOutcome,
    adjacent_duplicate_rows,
    degenerate_reason_for,
    false_alarm_rate_at_defaults,
    fizzle_rate,
    run_disclosure_sweeps,
    run_once,
    summarize_setting,
)


def _outcome(
    seed,
    *,
    established,
    total_infections=0,
    peak_infected=0,
    first_fired_day=None,
    first_disclosed_day=None,
    infections_at_first_disclosure=None,
    finest_disclosed_level=None,
) -> RunOutcome:
    return RunOutcome(
        seed=seed,
        established=established,
        total_infections=total_infections,
        peak_infected=peak_infected,
        first_fired_day=first_fired_day,
        first_disclosed_day=first_disclosed_day,
        infections_at_first_disclosure=infections_at_first_disclosure,
        finest_disclosed_level=finest_disclosed_level,
    )


class PolicyCostPropertyTest(unittest.TestCase):
    def test_defined_only_when_both_events_happened(self) -> None:
        self.assertEqual(
            _outcome(1, established=True, first_fired_day=3, first_disclosed_day=8).policy_cost,
            5,
        )
        self.assertIsNone(_outcome(2, established=True, first_fired_day=3).policy_cost)
        self.assertIsNone(_outcome(3, established=True, first_disclosed_day=8).policy_cost)
        self.assertIsNone(_outcome(4, established=False).policy_cost)


class FizzleRateTest(unittest.TestCase):
    def test_fraction_never_established(self) -> None:
        outcomes = [
            _outcome(1, established=False),
            _outcome(2, established=True, total_infections=10),
            _outcome(3, established=False),
            _outcome(4, established=True, total_infections=20),
        ]
        self.assertAlmostEqual(fizzle_rate(outcomes), 0.5)

    def test_empty_is_zero(self) -> None:
        self.assertEqual(fizzle_rate([]), 0.0)


class SummarizeSettingConditioningTest(unittest.TestCase):
    def setUp(self) -> None:
        self.outcomes = [
            # established, fired + disclosed
            _outcome(
                1, established=True, total_infections=40,
                first_fired_day=3, first_disclosed_day=7,
                infections_at_first_disclosure=20, finest_disclosed_level=ScopeLevel.SUITE,
            ),
            _outcome(
                2, established=True, total_infections=60,
                first_fired_day=5, first_disclosed_day=9,
                infections_at_first_disclosure=30, finest_disclosed_level=ScopeLevel.FLOOR,
            ),
            # established, detector never fired (a miss)
            _outcome(3, established=True, total_infections=15),
            # not established, one fired (false alarm), one silent
            _outcome(4, established=False, first_fired_day=2),
            _outcome(5, established=False),
        ]
        self.s = summarize_setting(self.outcomes, param_name="MIN_SCOPE_POPULATION", value=20)

    def test_counts(self) -> None:
        self.assertEqual(self.s.n_established, 3)
        self.assertEqual(self.s.n_non_established, 2)
        self.assertEqual(self.s.n_fired, 2)
        self.assertEqual(self.s.n_disclosed, 2)

    def test_total_infections_is_over_all_established(self) -> None:
        self.assertAlmostEqual(self.s.mean_total_infections, (40 + 60 + 15) / 3)

    def test_delays_are_over_the_disclosed_subset_only(self) -> None:
        self.assertAlmostEqual(self.s.mean_fire_delay, (3 + 5) / 2)
        self.assertAlmostEqual(self.s.mean_disclosure_delay, (7 + 9) / 2)
        self.assertAlmostEqual(self.s.mean_gap, ((7 - 3) + (9 - 5)) / 2)
        self.assertAlmostEqual(self.s.mean_infections_at_disclosure, (20 + 30) / 2)

    def test_finest_level_is_the_deepest_ever_disclosed(self) -> None:
        self.assertEqual(self.s.finest_disclosed_level, ScopeLevel.SUITE)

    def test_disclosed_fraction_is_over_established(self) -> None:
        self.assertAlmostEqual(self.s.disclosed_fraction, 2 / 3)

    def test_unbiased_infections_include_the_non_disclosing_established_run(self) -> None:
        # runs 1 and 2 disclosed (20, 30); run 3 established but never
        # disclosed -> contributes its full total (15).
        self.assertAlmostEqual(
            self.s.mean_infections_before_disclosure_unbiased, (20 + 30 + 15) / 3
        )

    def test_not_degenerate_by_default(self) -> None:
        self.assertFalse(self.s.degenerate)

    def test_false_alarm_rate_is_over_non_established_only(self) -> None:
        self.assertEqual(self.s.n_false_alarms, 1)
        self.assertAlmostEqual(self.s.false_alarm_rate, 1 / 2)


class SummarizeSettingEmptyBucketsTest(unittest.TestCase):
    def test_no_disclosures_leaves_disclosure_stats_none(self) -> None:
        s = summarize_setting(
            [_outcome(1, established=True, total_infections=10)],
            param_name="x", value=1,
        )
        self.assertEqual(s.n_disclosed, 0)
        self.assertIsNone(s.mean_disclosure_delay)
        self.assertIsNone(s.mean_gap)
        self.assertIsNone(s.mean_infections_at_disclosure)
        self.assertIsNone(s.finest_disclosed_level)
        self.assertIsNotNone(s.mean_total_infections)  # still established

    def test_all_established_yields_no_false_alarm_rate(self) -> None:
        s = summarize_setting(
            [_outcome(1, established=True, total_infections=10)], param_name="x", value=1
        )
        self.assertIsNone(s.false_alarm_rate)


class FalseAlarmAtDefaultsTest(unittest.TestCase):
    def test_over_non_established_runs(self) -> None:
        outcomes = [
            _outcome(1, established=True, first_fired_day=1),
            _outcome(2, established=False, first_fired_day=2),  # false alarm
            _outcome(3, established=False),  # silent
        ]
        alarms, non_est, rate = false_alarm_rate_at_defaults(outcomes)
        self.assertEqual((alarms, non_est), (1, 2))
        self.assertAlmostEqual(rate, 0.5)


class AdjacentDuplicateRowsTest(unittest.TestCase):
    def test_identical_regime_rows_are_flagged(self) -> None:
        same = [
            _outcome(
                1, established=True, total_infections=40,
                first_fired_day=3, first_disclosed_day=7,
                infections_at_first_disclosure=20, finest_disclosed_level=ScopeLevel.SUITE,
            )
        ]
        different = [
            _outcome(
                1, established=True, total_infections=40,
                first_fired_day=3, first_disclosed_day=12,
                infections_at_first_disclosure=55, finest_disclosed_level=ScopeLevel.FLOOR,
            )
        ]
        a = summarize_setting(same, param_name="p", value=0.25)
        b = summarize_setting(same, param_name="p", value=0.50)
        c = summarize_setting(different, param_name="p", value=0.75)

        self.assertEqual(adjacent_duplicate_rows([a, b, c]), [(0.25, 0.50)])
        self.assertEqual(adjacent_duplicate_rows([a, c]), [])


class DegenerateReasonTest(unittest.TestCase):
    POPS = (25, 75, 150)  # suite / floor / building=campus in the default structure

    def test_normal_config_is_not_degenerate(self) -> None:
        self.assertIsNone(degenerate_reason_for(DisclosureConfig(), self.POPS))

    def test_min_population_above_whole_campus_is_degenerate(self) -> None:
        reason = degenerate_reason_for(
            DisclosureConfig(min_scope_population=200), self.POPS
        )
        self.assertIsNotNone(reason)
        self.assertIn("200", reason)

    def test_tiny_report_fraction_is_degenerate(self) -> None:
        # floor(25*0.08)=2, floor(75*0.08)=6 < ceil(sqrt(75))=9,
        # floor(150*0.08)=12 < 13 -- no scope can clear both gates.
        self.assertIsNotNone(
            degenerate_reason_for(DisclosureConfig(max_report_fraction=0.08), self.POPS)
        )

    def test_high_statistical_floor_still_leaves_floor_disclosable(self) -> None:
        # floor n=75 admits up to floor(75*0.5)=37 reports and needs 25 -> OK.
        self.assertIsNone(
            degenerate_reason_for(DisclosureConfig(statistical_gate_floor=25), self.POPS)
        )

    def test_adjacent_duplicate_rows_skips_degenerate_rows(self) -> None:
        a = summarize_setting([], param_name="p", value=1, degenerate=True, degenerate_reason="x")
        b = summarize_setting([], param_name="p", value=2, degenerate=True, degenerate_reason="x")
        self.assertEqual(adjacent_duplicate_rows([a, b]), [])


class RunOnceIntegrationTest(unittest.TestCase):
    def test_disclosure_fields_are_consistent(self) -> None:
        outcome = run_once(2, days=20)
        if outcome.first_disclosed_day is None:
            self.assertIsNone(outcome.infections_at_first_disclosure)
            self.assertIsNone(outcome.finest_disclosed_level)
        else:
            self.assertIsNotNone(outcome.infections_at_first_disclosure)
            self.assertIsInstance(outcome.finest_disclosed_level, ScopeLevel)
            # disclosure cannot precede firing
            self.assertLessEqual(outcome.first_fired_day, outcome.first_disclosed_day)


class SweepIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.results = run_disclosure_sweeps(seeds=list(range(1, 13)), days=18)

    def test_three_sweeps_each_with_the_right_row_count(self) -> None:
        self.assertEqual(
            set(self.results.sweeps),
            {"MIN_SCOPE_POPULATION", "STATISTICAL_GATE_FLOOR", "MAX_REPORT_FRACTION"},
        )
        self.assertEqual(len(self.results.sweeps["MIN_SCOPE_POPULATION"]), 4)
        self.assertEqual(len(self.results.sweeps["STATISTICAL_GATE_FLOOR"]), 5)
        self.assertEqual(len(self.results.sweeps["MAX_REPORT_FRACTION"]), 3)

    def test_establishment_is_disclosure_independent(self) -> None:
        # Every row of every sweep must reflect the same established count
        # (establishment depends only on the simulated epidemic).
        n_established = {
            s.n_established
            for summaries in self.results.sweeps.values()
            for s in summaries
        }
        self.assertEqual(len(n_established), 1)
        only = n_established.pop()
        self.assertAlmostEqual(
            1 - only / 12, self.results.fizzle_rate
        )

    def test_false_alarm_and_fire_delay_are_detection_side_constants(self) -> None:
        self.assertEqual(self.results.n_established + self.results.non_established, 12)
        # control fire delay is defined whenever at least one established
        # run fired
        if self.results.n_fired:
            self.assertIsNotNone(self.results.control_fire_delay)

    def test_impossible_min_population_row_is_marked_degenerate(self) -> None:
        rows = self.results.sweeps["MIN_SCOPE_POPULATION"]
        self.assertTrue(rows[-1].degenerate)  # value 200, campus is 150
        self.assertFalse(rows[0].degenerate)  # value 20

    def test_tighter_gate_never_discloses_more_than_a_looser_one(self) -> None:
        # Within the MIN_SCOPE_POPULATION sweep (monotone tightening),
        # n_disclosed should be non-increasing.
        counts = [s.n_disclosed for s in self.results.sweeps["MIN_SCOPE_POPULATION"]]
        self.assertEqual(counts, sorted(counts, reverse=True))


if __name__ == "__main__":
    unittest.main()
