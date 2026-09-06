"""Detection engine tests -- independent of the disclosure engine."""

from __future__ import annotations

import math
import unittest

from microcluster import detection
from microcluster.config import DetectionConfig
from microcluster.detection import HysteresisState
from microcluster.models import Category

from tests.fixtures import NOW, report, reports, single_scope_registry, standard_registry


class LocalizedClusterTest(unittest.TestCase):
    """A burst in one suite: the relative detector fires, the absolute
    detector does not."""

    def setUp(self) -> None:
        self.reg = standard_registry()
        # All reports at suite level (see the mixed-level assumption in
        # detection.evaluate): the cluster in S1, scattered peers in the
        # sibling suites.
        self.reports = (
            reports("S1", 9, category=Category.RESPIRATORY)
            + reports("S2", 2, category=Category.GENERAL)
            + reports("S3", 1, category=Category.GASTROINTESTINAL)
            + reports("S4", 1, category=Category.OTHER)
            + reports("S5", 1, category=Category.GENERAL)
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
        # Uniform building level; three reports per building, no category
        # concentrated anywhere.
        self.reports = (
            reports("B1", 3, category=Category.GENERAL)
            + reports("B2", 3, category=Category.RESPIRATORY)
            + reports("B3", 3, category=Category.GASTROINTESTINAL)
            + reports("B4", 3, category=Category.OTHER)
            + reports("B5", 3, category=Category.GENERAL)
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


class AbsoluteDetectorCategoryScopingTest(unittest.TestCase):
    """The absolute detector counts only dominant-category reports, so a
    spike made of several unrelated illnesses does not fire it."""

    def test_mixed_category_volume_spike_does_not_fire_absolute(self) -> None:
        reg = standard_registry()
        # 70 within-window reports campus-wide -- above the raw-volume
        # threshold of 1.5 * (0.02 * 2000) = 60 -- but split evenly
        # between two unrelated categories, so the dominant-category
        # count is only 35.
        data = []
        for b in ("B1", "B2", "B3", "B4", "B5"):
            data += reports(b, 7, category=Category.RESPIRATORY)
            data += reports(b, 7, category=Category.GASTROINTESTINAL)
        result = detection.evaluate(data, reg, now=NOW)

        self.assertEqual(result.findings.count_within_window, 70)
        self.assertFalse(result.absolute_detector_fired)
        self.assertFalse(result.relative_detector_fired)
        self.assertFalse(result.fired)

    def test_single_category_spike_of_the_same_size_does_fire_absolute(self) -> None:
        reg = standard_registry()
        data = []
        for b in ("B1", "B2", "B3", "B4", "B5"):
            data += reports(b, 14, category=Category.RESPIRATORY)
        result = detection.evaluate(data, reg, now=NOW)

        self.assertEqual(result.findings.count_within_window, 70)
        self.assertTrue(result.absolute_detector_fired)


class RelativeDetectorClusterMinimumIsCategoryScopedTest(unittest.TestCase):
    """The minimum-cluster-size gate counts only the hotspot's
    dominant-category reports."""

    def test_location_with_three_different_categories_fails_the_minimum(self) -> None:
        reg = standard_registry()
        # One suite, three reports, three categories. Volume ratio is
        # high, but no single category reaches
        # MIN_RELATIVE_CLUSTER_REPORTS (3).
        data = (
            reports("S1", 1, category=Category.RESPIRATORY)
            + reports("S1", 1, category=Category.GASTROINTESTINAL)
            + reports("S1", 1, category=Category.GENERAL)
        )
        result = detection.evaluate(data, reg, now=NOW)

        self.assertEqual(result.findings.count_within_window, 3)
        self.assertGreater(result.findings.relative_excess_ratio, 2.0)
        self.assertFalse(result.relative_detector_fired)
        self.assertFalse(result.fired)

    def test_same_location_one_category_meets_the_minimum(self) -> None:
        reg = standard_registry()
        data = reports("S1", 3, category=Category.RESPIRATORY)
        result = detection.evaluate(data, reg, now=NOW)

        self.assertGreater(result.findings.relative_excess_ratio, 2.0)
        self.assertTrue(result.relative_detector_fired)


class MixedLevelReportsAssumptionTest(unittest.TestCase):
    """evaluate() enforces that all reports resolve to one ScopeLevel."""

    def test_mixed_level_reports_are_rejected(self) -> None:
        reg = standard_registry()
        data = (
            reports("S1", 3, category=Category.RESPIRATORY)  # SUITE
            + reports("B2", 3, category=Category.RESPIRATORY)  # BUILDING
        )
        with self.assertRaises(ValueError) as ctx:
            detection.evaluate(data, reg, now=NOW)
        self.assertIn("same scope level", str(ctx.exception))

    def test_uniform_level_reports_are_accepted(self) -> None:
        reg = standard_registry()
        data = reports("S1", 3, category=Category.RESPIRATORY) + reports(
            "S2", 3, category=Category.RESPIRATORY
        )
        detection.evaluate(data, reg, now=NOW)  # does not raise

    def test_level_check_sees_reports_outside_the_window_too(self) -> None:
        # The old report is outside the 72h window and would be ignored by
        # both detectors, but it still counts for the level check.
        reg = standard_registry()
        data = reports("S1", 3, category=Category.RESPIRATORY) + reports(
            "B2", 1, category=Category.RESPIRATORY, hours_ago=500
        )
        with self.assertRaises(ValueError):
            detection.evaluate(data, reg, now=NOW)


class HysteresisTest(unittest.TestCase):
    """Detection hysteresis (config.HYSTERESIS_MIN_FIRED_DAYS /
    HYSTERESIS_RELEASE_THRESHOLD), threaded via HysteresisState across a
    sequence of evaluate() calls.

    A campus-only registry isolates these to the absolute detector alone:
    with a single scope, the relative detector has no peers and can never
    fire (see DetectorEdgeCaseTest), so ``raw_fired`` here is exactly
    ``absolute_detector_fired``, driven entirely by how many reports we
    put in the window.
    """

    def setUp(self) -> None:
        self.reg = single_scope_registry(2000)  # expected = 0.02*2000 = 40
        self.config = DetectionConfig(
            background_rate=0.02,
            absolute_excess_ratio=1.5,  # fires at >= 60
            hysteresis_min_fired_days=3,
            hysteresis_release_threshold=3,
        )

    def _evaluate(self, count: int, state: HysteresisState | None):
        data = reports("C", count, category=Category.RESPIRATORY, hours_ago=0, now=NOW)
        return detection.evaluate(
            data, self.reg, now=NOW, config=self.config, hysteresis_state=state
        )

    def test_single_call_with_no_state_is_unaffected_by_hysteresis(self) -> None:
        # 70 >= 60 -> raw fires; no prior state -> fired == raw_fired.
        fired_result = self._evaluate(70, None)
        self.assertTrue(fired_result.raw_fired)
        self.assertEqual(fired_result.fired, fired_result.raw_fired)

        # 10 < 60 -> raw does not fire; still no prior state -> False.
        quiet_result = self._evaluate(10, None)
        self.assertFalse(quiet_result.raw_fired)
        self.assertEqual(quiet_result.fired, quiet_result.raw_fired)

    def test_quiet_stretch_with_no_prior_activation_never_fires(self) -> None:
        state = None
        for _ in range(4):
            result = self._evaluate(5, state)
            self.assertFalse(result.fired)
            self.assertFalse(result.hysteresis_state.active)
            state = result.hysteresis_state

    def test_hold_continues_while_raw_still_fires(self) -> None:
        state = None
        result = self._evaluate(70, state)  # raw fires
        self.assertTrue(result.fired)
        self.assertEqual(result.hysteresis_state, HysteresisState(active=True, consecutive_days=1))

        state = result.hysteresis_state
        result = self._evaluate(65, state)  # still raw-fires
        self.assertTrue(result.fired)
        self.assertEqual(result.hysteresis_state, HysteresisState(active=True, consecutive_days=2))

    def test_hold_survives_a_raw_dip_until_the_minimum_is_served(self) -> None:
        # Day 0: raw fires (70 >= 60).
        state = None
        result = self._evaluate(70, state)
        self.assertTrue(result.fired)
        state = result.hysteresis_state

        # Day 1: raw fires again (65 >= 60); streak now 2.
        result = self._evaluate(65, state)
        self.assertTrue(result.fired)
        self.assertEqual(result.hysteresis_state.consecutive_days, 2)
        state = result.hysteresis_state

        # Day 2: raw does NOT fire (50 < 60), but the window is nowhere
        # near the release threshold (3) and the minimum hold (3 days)
        # has not yet been served (streak is only 2) -> HELD fired=True.
        result = self._evaluate(50, state)
        self.assertFalse(result.raw_fired)
        self.assertTrue(result.fired, "hysteresis should have held fired=True")
        self.assertEqual(result.hysteresis_state, HysteresisState(active=True, consecutive_days=3))
        state = result.hysteresis_state

        # Day 3: raw still does not fire (45 < 60); the minimum (3) has
        # now been served -> releases on schedule.
        result = self._evaluate(45, state)
        self.assertFalse(result.raw_fired)
        self.assertFalse(result.fired, "hysteresis should have released on schedule")
        self.assertEqual(result.hysteresis_state, HysteresisState(active=False, consecutive_days=0))

    def test_release_threshold_overrides_the_minimum_hold(self) -> None:
        # Day 0: raw fires (70 >= 60); streak = 1, well under the minimum.
        state = None
        result = self._evaluate(70, state)
        self.assertTrue(result.fired)
        state = result.hysteresis_state

        # Day 1: the window has nearly emptied out (2 <= release threshold
        # of 3) -- releases IMMEDIATELY, even though the minimum hold (3)
        # was never served.
        result = self._evaluate(2, state)
        self.assertFalse(result.raw_fired)
        self.assertFalse(result.fired, "a near-empty window should release early")
        self.assertEqual(result.hysteresis_state, HysteresisState(active=False, consecutive_days=0))

    def test_a_fresh_raw_fire_restarts_the_streak_at_one(self) -> None:
        state = HysteresisState(active=False, consecutive_days=0)
        result = self._evaluate(70, state)
        self.assertEqual(result.hysteresis_state, HysteresisState(active=True, consecutive_days=1))


if __name__ == "__main__":
    unittest.main()
