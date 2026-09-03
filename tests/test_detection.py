"""Detection engine tests -- independent of the disclosure engine."""

from __future__ import annotations

import math
import unittest

from microcluster import detection
from microcluster.config import DetectionConfig
from microcluster.models import Category

from tests.fixtures import NOW, report, reports, standard_registry


class LocalizedClusterTest(unittest.TestCase):
    """A burst in one suite: the relative detector fires, the absolute
    detector does not."""

    def setUp(self) -> None:
        self.reg = standard_registry()
        self.reports = (
            reports("S1", 9, category=Category.RESPIRATORY)
            + reports("B2", 2, category=Category.GENERAL)
            + reports("B3", 1, category=Category.GASTROINTESTINAL)
            + reports("B4", 1, category=Category.OTHER)
            + reports("B5", 1, category=Category.GENERAL)
            # Old reports in the same suite: outside the 72h window, ignored.
            + reports("S1", 6, category=Category.RESPIRATORY, hours_ago=500)
        )
        self.result = detection.evaluate(self.reports, self.reg, now=NOW)

    def test_relative_fires_absolute_does_not(self) -> None:
        self.assertTrue(self.result.relative_detector_fired)
        self.assertFalse(self.result.absolute_detector_fired)
        self.assertTrue(self.result.fired)

    def test_three_findings_reported_plainly(self) -> None:
        f = self.result.findings
        self.assertEqual(f.count_within_window, 14)
        self.assertEqual(f.count_sharing_category, 9)
        self.assertGreater(f.relative_excess_ratio, 2.0)

    def test_hotspot_and_dominant_category(self) -> None:
        self.assertEqual(self.result.hotspot_location_id, "S1")
        self.assertEqual(self.result.dominant_category, Category.RESPIRATORY)

    def test_absolute_expectation_is_from_background_rate(self) -> None:
        # 0.02 * 2000 declared campus population.
        self.assertAlmostEqual(self.result.absolute_expected, 40.0)

    def test_aggregate_for_disclosure_is_per_scope_counts_only(self) -> None:
        self.assertEqual(
            self.result.qualifying_scope_counts,
            {"S1": 9, "F1": 9, "B1": 9, "C": 9},
        )


class CampusWideRiseTest(unittest.TestCase):
    """An even rise across every building: the absolute detector fires,
    the relative detector does not (no location stands out)."""

    def setUp(self) -> None:
        self.reg = standard_registry()
        self.reports = []
        for b in ("B1", "B2", "B3", "B4", "B5"):
            self.reports += reports(b, 14, category=Category.RESPIRATORY)
        self.result = detection.evaluate(self.reports, self.reg, now=NOW)

    def test_absolute_fires_relative_does_not(self) -> None:
        self.assertTrue(self.result.absolute_detector_fired)
        self.assertFalse(self.result.relative_detector_fired)
        self.assertTrue(self.result.fired)

    def test_relative_excess_ratio_is_about_one(self) -> None:
        # Every building reports at the same per-capita rate, so no
        # location stands out: the smoothed ratio sits close to 1.
        ratio = self.result.findings.relative_excess_ratio
        self.assertGreater(ratio, 0.9)
        self.assertLess(ratio, 1.15)

    def test_counts(self) -> None:
        self.assertEqual(self.result.findings.count_within_window, 70)
        self.assertEqual(self.result.findings.count_sharing_category, 70)
        self.assertEqual(self.result.qualifying_scope_counts["C"], 70)
        for b in ("B1", "B2", "B3", "B4", "B5"):
            self.assertEqual(self.result.qualifying_scope_counts[b], 14)


class ScatteredNoiseTest(unittest.TestCase):
    """Low volume, spread across locations and categories: neither
    detector fires."""

    def setUp(self) -> None:
        self.reg = standard_registry()
        self.reports = (
            reports("B1", 2, category=Category.GENERAL)
            + reports("B2", 2, category=Category.RESPIRATORY)
            + reports("B3", 2, category=Category.GASTROINTESTINAL)
            + reports("B4", 2, category=Category.OTHER)
            + reports("B5", 1, category=Category.GENERAL)
            + reports("F2", 2, category=Category.RESPIRATORY)
            + reports("F3", 2, category=Category.GENERAL)
            + reports("S2", 2, category=Category.OTHER)
        )
        self.result = detection.evaluate(self.reports, self.reg, now=NOW)

    def test_neither_detector_fires(self) -> None:
        self.assertFalse(self.result.relative_detector_fired)
        self.assertFalse(self.result.absolute_detector_fired)
        self.assertFalse(self.result.fired)


class DetectorEdgeCaseTest(unittest.TestCase):
    def test_zero_reports(self) -> None:
        reg = standard_registry()
        result = detection.evaluate([], reg, now=NOW)
        self.assertFalse(result.fired)
        self.assertFalse(result.relative_detector_fired)
        self.assertFalse(result.absolute_detector_fired)
        self.assertIsNone(result.dominant_category)
        self.assertIsNone(result.hotspot_location_id)
        self.assertEqual(result.findings.count_within_window, 0)
        self.assertEqual(result.findings.count_sharing_category, 0)
        self.assertEqual(result.findings.relative_excess_ratio, 0.0)
        self.assertEqual(result.qualifying_scope_counts, {})

    def test_reports_outside_window_are_excluded(self) -> None:
        reg = standard_registry()
        old = reports("S1", 9, category=Category.RESPIRATORY, hours_ago=200)
        result = detection.evaluate(old, reg, now=NOW)
        self.assertEqual(result.findings.count_within_window, 0)
        self.assertIsNone(result.dominant_category)
        self.assertFalse(result.fired)
        self.assertEqual(result.qualifying_scope_counts, {})

    def test_relative_detector_has_a_minimum_cluster_size(self) -> None:
        # Two reports in a tiny suite produce a huge ratio but must not
        # fire -- MIN_RELATIVE_CLUSTER_REPORTS is 3.
        reg = standard_registry()
        result = detection.evaluate(
            reports("S1", 2, category=Category.RESPIRATORY), reg, now=NOW
        )
        self.assertGreater(result.findings.relative_excess_ratio, 2.0)
        self.assertFalse(result.relative_detector_fired)

    def test_location_that_is_the_whole_campus_cannot_fire_relative(self) -> None:
        reg = standard_registry()
        result = detection.evaluate(
            reports("C", 50, category=Category.RESPIRATORY), reg, now=NOW
        )
        # No peers to compare against -> relative ratio stays 0, not inf.
        self.assertEqual(result.findings.relative_excess_ratio, 0.0)
        self.assertFalse(result.relative_detector_fired)
        # Absolute still works: 50 >= 1.5 * (0.02 * 2000) = 60 is False here.
        self.assertFalse(result.absolute_detector_fired)

    def test_unknown_location_is_rejected(self) -> None:
        reg = standard_registry()
        bad = [report("does-not-exist")]
        with self.assertRaises(KeyError):
            detection.evaluate(bad, reg, now=NOW)

    def test_relative_ratio_stays_finite_when_peers_are_silent(self) -> None:
        # Smoothing keeps the ratio finite even when the control rate
        # would otherwise be exactly zero.
        reg = standard_registry()
        result = detection.evaluate(
            reports("S1", 5, category=Category.RESPIRATORY), reg, now=NOW
        )
        ratio = result.findings.relative_excess_ratio
        self.assertTrue(math.isfinite(ratio))
        self.assertGreater(ratio, 2.0)
        self.assertTrue(result.relative_detector_fired)

    def test_smoothing_constant_damps_the_ratio(self) -> None:
        # Same data, larger smoothing constant -> ratio pulled toward 1.
        reg = standard_registry()
        data = reports("S1", 9, category=Category.RESPIRATORY)
        light = detection.evaluate(
            data, reg, now=NOW, config=DetectionConfig(relative_smoothing=1.0)
        ).findings.relative_excess_ratio
        heavy = detection.evaluate(
            data, reg, now=NOW, config=DetectionConfig(relative_smoothing=25.0)
        ).findings.relative_excess_ratio
        self.assertLess(heavy, light)


if __name__ == "__main__":
    unittest.main()
