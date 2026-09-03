"""End-to-end tests: detection wired to disclosure (rule 10 ordering)."""

from __future__ import annotations

import unittest

from microcluster.engine import analyze
from microcluster.models import Category

from tests.fixtures import (
    NOW,
    reports,
    roster_registry,
    small_registry_floor18,
    standard_registry,
)


class LocalizedClusterEndToEndTest(unittest.TestCase):
    def setUp(self) -> None:
        reg = standard_registry()
        data = (
            reports("S1", 9, category=Category.RESPIRATORY)
            + reports("B2", 2, category=Category.GENERAL)
            + reports("B3", 1, category=Category.GASTROINTESTINAL)
            + reports("B4", 1, category=Category.OTHER)
            + reports("B5", 1, category=Category.GENERAL)
        )
        self.result = analyze(data, reg, now=NOW)

    def test_discloses_the_suite(self) -> None:
        self.assertEqual(self.result.disclosed_scope_id, "S1")
        disclosed = self.result.disclosure.disclosed()
        self.assertEqual(disclosed.scope_id, "S1")
        self.assertTrue(disclosed.disclosure_eligible)
        self.assertEqual(disclosed.qualifying_reports, 9)

    def test_table_includes_the_rejected_coarser_scopes(self) -> None:
        ids = {ev.scope_id for ev in self.result.disclosure.evaluations}
        self.assertEqual(ids, {"S1", "F1", "B1", "C"})
        rejected = [ev for ev in self.result.disclosure.evaluations if not ev.selected]
        self.assertTrue(all(not ev.disclosure_eligible for ev in rejected))


class CampusWideEndToEndTest(unittest.TestCase):
    def test_discloses_the_campus(self) -> None:
        reg = standard_registry()
        data = []
        for b in ("B1", "B2", "B3", "B4", "B5"):
            data += reports(b, 14, category=Category.RESPIRATORY)
        result = analyze(data, reg, now=NOW)

        self.assertTrue(result.detection.absolute_detector_fired)
        self.assertFalse(result.detection.relative_detector_fired)
        self.assertEqual(result.disclosed_scope_id, "C")


class ScatteredNoiseEndToEndTest(unittest.TestCase):
    def test_detects_nothing_and_discloses_nothing(self) -> None:
        reg = standard_registry()
        data = (
            reports("B1", 2, category=Category.GENERAL)
            + reports("B2", 2, category=Category.RESPIRATORY)
            + reports("B3", 2, category=Category.GASTROINTESTINAL)
            + reports("B4", 2, category=Category.OTHER)
            + reports("B5", 1, category=Category.GENERAL)
            + reports("F2", 2, category=Category.RESPIRATORY)
            + reports("F3", 2, category=Category.GENERAL)
            + reports("S2", 2, category=Category.OTHER)
        )
        result = analyze(data, reg, now=NOW)

        self.assertFalse(result.detection.fired)
        # Disclosure engine does not run when nothing is detected (rule 10).
        self.assertEqual(result.disclosure.evaluations, ())
        self.assertIsNone(result.disclosed_scope_id)


class OverclaimRefusalEndToEndTest(unittest.TestCase):
    def test_seven_reports_cannot_name_a_scope_of_two_thousand(self) -> None:
        reg = standard_registry()
        data = reports("B1", 7, category=Category.RESPIRATORY)
        result = analyze(data, reg, now=NOW)

        # Something looks unusual in B1 relative to its peers...
        self.assertTrue(result.detection.fired)
        # ...but no scope has enough evidence to be named.
        self.assertIsNone(result.disclosed_scope_id)

        campus = next(ev for ev in result.disclosure.evaluations if ev.scope_id == "C")
        self.assertEqual(campus.statistical_threshold, 45)
        self.assertFalse(campus.statistical_pass)
        building = next(ev for ev in result.disclosure.evaluations if ev.scope_id == "B1")
        self.assertFalse(building.statistical_pass)  # 7 < ceil(sqrt(400)) == 20


class RosterRefusalEndToEndTest(unittest.TestCase):
    def test_dense_small_group_is_detected_but_never_named(self) -> None:
        reg = roster_registry()
        data = reports("G", 15, category=Category.RESPIRATORY)
        result = analyze(data, reg, now=NOW)

        self.assertTrue(result.detection.fired)  # the signal is real

        group = next(ev for ev in result.disclosure.evaluations if ev.scope_id == "G")
        self.assertTrue(group.statistical_pass)
        self.assertTrue(group.min_population_pass)
        self.assertFalse(group.report_fraction_pass)
        self.assertIn("roster", group.disclosure_reason)

        self.assertIsNone(result.disclosed_scope_id)  # ...but nothing is disclosed


class ZeroReportsEndToEndTest(unittest.TestCase):
    def test_no_reports_detects_nothing_and_discloses_nothing(self) -> None:
        result = analyze([], standard_registry(), now=NOW)
        self.assertFalse(result.detection.fired)
        self.assertEqual(result.disclosure.evaluations, ())
        self.assertIsNone(result.disclosed_scope_id)


class PrivacyRefusalEndToEndTest(unittest.TestCase):
    def test_five_reports_on_an_eighteen_person_floor_disclose_the_building(self) -> None:
        reg = small_registry_floor18()
        data = reports("F", 5, category=Category.RESPIRATORY)
        result = analyze(data, reg, now=NOW)

        self.assertTrue(result.detection.fired)

        floor = next(ev for ev in result.disclosure.evaluations if ev.scope_id == "F")
        self.assertTrue(floor.statistical_pass)   # 5 >= 5
        self.assertFalse(floor.privacy_pass)      # 18 < 20
        self.assertFalse(floor.selected)

        self.assertEqual(result.disclosed_scope_id, "B")


if __name__ == "__main__":
    unittest.main()
