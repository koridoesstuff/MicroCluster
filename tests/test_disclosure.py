"""Disclosure engine tests -- independent of the detection engine.

The disclosure engine is fed aggregate per-scope counts directly, exactly
as the detection engine would hand them over (rule 10).
"""

from __future__ import annotations

import unittest

from microcluster import disclosure
from microcluster.config import DisclosureConfig
from microcluster.models import Scope, ScopeLevel, ScopeRegistry

from tests.fixtures import (
    roster_registry,
    single_scope_registry,
    small_registry_floor18,
    standard_registry,
)


class StatisticalThresholdTest(unittest.TestCase):
    def test_threshold_scales_up_with_population(self) -> None:
        expected = {12: 5, 18: 5, 40: 7, 100: 10, 500: 23, 2000: 45}
        for n, threshold in expected.items():
            self.assertEqual(disclosure.statistical_threshold(n), threshold, msg=f"n={n}")

    def test_floor_applies_to_small_populations(self) -> None:
        # ceil(sqrt(4)) == 2, but the floor is 5.
        self.assertEqual(disclosure.statistical_threshold(4), 5)

    def test_perfect_squares_are_exact(self) -> None:
        self.assertEqual(disclosure.statistical_threshold(10_000), 100)


class BothGatesAcrossPopulationsTest(unittest.TestCase):
    """n in {12, 18, 40, 100, 500, 2000}: the statistical threshold rises
    with n, while the privacy minimum rejects the two smallest scopes."""

    POPULATIONS = (12, 18, 40, 100, 500, 2000)
    STAT_THRESHOLD = {12: 5, 18: 5, 40: 7, 100: 10, 500: 23, 2000: 45}

    def test_qualifying_at_exactly_the_statistical_threshold(self) -> None:
        for n in self.POPULATIONS:
            q = self.STAT_THRESHOLD[n]
            result = disclosure.evaluate(single_scope_registry(n), {"C": q})
            ev = result.evaluations[0]
            with self.subTest(n=n):
                self.assertEqual(ev.statistical_threshold, q)
                self.assertTrue(ev.statistical_pass)
                # Privacy minimum (20) rejects n=12 and n=18.
                if n < 20:
                    self.assertFalse(ev.min_population_pass)
                    self.assertFalse(ev.privacy_pass)
                    self.assertFalse(ev.disclosure_eligible)
                    self.assertIsNone(result.disclosed_scope_id)
                    self.assertIn("below minimum privacy scope", ev.disclosure_reason)
                else:
                    self.assertTrue(ev.min_population_pass)
                    self.assertTrue(ev.report_fraction_pass)
                    self.assertTrue(ev.privacy_pass)
                    self.assertTrue(ev.disclosure_eligible)
                    self.assertEqual(result.disclosed_scope_id, "C")

    def test_report_fraction_gate_rejects_a_dense_small_scope(self) -> None:
        # n=40, 25 qualifying reports: statistical gate passes (25 >= 7),
        # but 25/40 = 0.625 > MAX_REPORT_FRACTION (0.5).
        result = disclosure.evaluate(single_scope_registry(40), {"C": 25})
        ev = result.evaluations[0]
        self.assertTrue(ev.statistical_pass)
        self.assertTrue(ev.min_population_pass)
        self.assertFalse(ev.report_fraction_pass)
        self.assertFalse(ev.privacy_pass)
        self.assertFalse(ev.disclosure_eligible)
        self.assertIsNone(result.disclosed_scope_id)
        self.assertIn("report fraction", ev.disclosure_reason)

    def test_gates_pull_in_opposite_directions(self) -> None:
        # Same qualifying count (10). Small scope fails statistics-free but
        # privacy; large scope fails statistics. Only the middle passes.
        small = disclosure.evaluate(single_scope_registry(15), {"C": 10}).evaluations[0]
        mid = disclosure.evaluate(single_scope_registry(60), {"C": 10}).evaluations[0]
        large = disclosure.evaluate(single_scope_registry(400), {"C": 10}).evaluations[0]

        self.assertFalse(small.privacy_pass)      # n=15 < 20
        self.assertTrue(small.statistical_pass)   # 10 >= 5

        self.assertTrue(mid.disclosure_eligible)  # 10 >= 8 and privacy ok

        self.assertFalse(large.statistical_pass)  # 10 < 20
        self.assertTrue(large.privacy_pass)       # n=400, fraction tiny


class OverclaimRefusalTest(unittest.TestCase):
    """7 qualifying reports, campus n=2000: the statistical gate fails
    (7 < 45) at every scope, so nothing is disclosed."""

    def test_campus_scope_fails_statistical_gate(self) -> None:
        reg = standard_registry()
        result = disclosure.evaluate(reg, {"B1": 7, "C": 7})

        campus = next(ev for ev in result.evaluations if ev.scope_id == "C")
        self.assertEqual(campus.statistical_threshold, 45)
        self.assertEqual(campus.qualifying_reports, 7)
        self.assertFalse(campus.statistical_pass)
        self.assertFalse(campus.disclosure_eligible)
        self.assertIn("statistical gate failed", campus.disclosure_reason)

        self.assertIsNone(result.disclosed_scope_id)


class PrivacyRefusalTest(unittest.TestCase):
    """5 qualifying reports, floor n=18: statistical gate passes (5 >= 5)
    but the privacy gate fails (18 < 20). A coarser scope is disclosed."""

    def setUp(self) -> None:
        self.reg = small_registry_floor18()
        self.result = disclosure.evaluate(self.reg, {"F": 5, "B": 5, "C": 5})

    def test_floor_passes_statistics_but_fails_privacy(self) -> None:
        floor = next(ev for ev in self.result.evaluations if ev.scope_id == "F")
        self.assertEqual(floor.statistical_threshold, 5)
        self.assertTrue(floor.statistical_pass)
        self.assertFalse(floor.min_population_pass)
        self.assertFalse(floor.privacy_pass)
        self.assertFalse(floor.disclosure_eligible)
        self.assertFalse(floor.selected)
        self.assertIn("below minimum privacy scope", floor.disclosure_reason)

    def test_coarser_scope_is_disclosed_instead(self) -> None:
        self.assertEqual(self.result.disclosed_scope_id, "B")
        building = self.result.disclosed()
        self.assertIsNotNone(building)
        self.assertEqual(building.scope_id, "B")
        self.assertTrue(building.selected)
        self.assertTrue(building.disclosure_eligible)

    def test_campus_scope_now_fails_statistics(self) -> None:
        campus = next(ev for ev in self.result.evaluations if ev.scope_id == "C")
        self.assertFalse(campus.statistical_pass)  # ceil(sqrt(300)) == 18 > 5


class RosterRefusalTest(unittest.TestCase):
    """~15 qualifying reports in a declared group of n=25: clears the
    statistical gate and the population minimum, but 15/25 = 0.60 exceeds
    MAX_REPORT_FRACTION -- naming the group would be naming its members."""

    def setUp(self) -> None:
        self.reg = roster_registry()
        self.result = disclosure.evaluate(self.reg, {"G": 15, "C": 15})
        self.group = next(ev for ev in self.result.evaluations if ev.scope_id == "G")

    def test_passes_statistical_gate(self) -> None:
        self.assertEqual(self.group.statistical_threshold, 5)
        self.assertTrue(self.group.statistical_pass)

    def test_passes_population_minimum(self) -> None:
        self.assertTrue(self.group.min_population_pass)  # 25 >= 20

    def test_refused_on_report_fraction(self) -> None:
        self.assertAlmostEqual(self.group.report_fraction, 0.60)
        self.assertFalse(self.group.report_fraction_pass)
        self.assertFalse(self.group.privacy_pass)
        self.assertFalse(self.group.disclosure_eligible)

    def test_disclosure_reason_names_the_fraction_ceiling_specifically(self) -> None:
        reason = self.group.disclosure_reason
        self.assertIn("report fraction 0.60 exceeds maximum 0.50", reason)
        self.assertIn("roster", reason)

    def test_nothing_is_disclosed(self) -> None:
        self.assertIsNone(self.result.disclosed_scope_id)


class EvaluationTableTest(unittest.TestCase):
    def test_every_candidate_scope_gets_a_record_including_rejected(self) -> None:
        reg = standard_registry()
        result = disclosure.evaluate(reg, {"S1": 9, "F1": 9, "B1": 9, "C": 9})
        ids = [ev.scope_id for ev in result.evaluations]
        self.assertEqual(set(ids), {"S1", "F1", "B1", "C"})

    def test_records_are_ordered_finest_scope_first(self) -> None:
        reg = standard_registry()
        result = disclosure.evaluate(reg, {"S1": 9, "F1": 9, "B1": 9, "C": 9})
        levels = [ev.scope_level for ev in result.evaluations]
        self.assertEqual(
            levels,
            [ScopeLevel.SUITE, ScopeLevel.FLOOR, ScopeLevel.BUILDING, ScopeLevel.CAMPUS],
        )

    def test_finest_eligible_scope_wins_and_others_are_marked_not_selected(self) -> None:
        reg = standard_registry()
        # Enough reports for the suite AND the floor to pass both gates.
        result = disclosure.evaluate(reg, {"S1": 12, "F1": 12, "B1": 12, "C": 12})
        selected = [ev.scope_id for ev in result.evaluations if ev.selected]
        self.assertEqual(selected, ["S1"])
        floor = next(ev for ev in result.evaluations if ev.scope_id == "F1")
        self.assertTrue(floor.disclosure_eligible)
        self.assertFalse(floor.selected)
        self.assertIn("a finer scope was disclosed", floor.disclosure_reason)

    def test_winner_is_selected_from_the_table(self) -> None:
        reg = standard_registry()
        result = disclosure.evaluate(reg, {"S1": 9, "F1": 9, "B1": 9, "C": 9})
        self.assertIs(result.disclosed(), next(e for e in result.evaluations if e.selected))

    def test_empty_count_table_discloses_nothing(self) -> None:
        reg = standard_registry()
        result = disclosure.evaluate(reg, {})
        self.assertEqual(result.evaluations, ())
        self.assertIsNone(result.disclosed_scope_id)
        self.assertIsNone(result.disclosed())

    def test_nothing_disclosed_yields_no_selection_but_full_table(self) -> None:
        reg = standard_registry()
        result = disclosure.evaluate(reg, {"B1": 3, "C": 3})
        self.assertIsNone(result.disclosed_scope_id)
        self.assertIsNone(result.disclosed())
        self.assertEqual(len(result.evaluations), 2)
        self.assertTrue(all(not ev.selected for ev in result.evaluations))


class ConfigurableThresholdsTest(unittest.TestCase):
    def test_max_report_fraction_is_configurable(self) -> None:
        strict = DisclosureConfig(max_report_fraction=0.1)
        result = disclosure.evaluate(single_scope_registry(100), {"C": 15}, config=strict)
        ev = result.evaluations[0]
        self.assertTrue(ev.statistical_pass)     # 15 >= 10
        self.assertFalse(ev.report_fraction_pass)  # 0.15 > 0.10
        self.assertIsNone(result.disclosed_scope_id)

    def test_min_scope_population_is_configurable(self) -> None:
        lax = DisclosureConfig(min_scope_population=10)
        result = disclosure.evaluate(single_scope_registry(15), {"C": 6}, config=lax)
        ev = result.evaluations[0]
        self.assertTrue(ev.min_population_pass)   # 15 >= 10 now
        self.assertTrue(ev.disclosure_eligible)
        self.assertEqual(result.disclosed_scope_id, "C")


if __name__ == "__main__":
    unittest.main()
