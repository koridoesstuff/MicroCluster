"""api.bands: count banding and reason sanitisation.

The differencing-attack defence (CLAUDE.md rule 3 for the UI): an exact
qualifying-report count must never leave the API, in a field or embedded
in a reason string.
"""

from __future__ import annotations

import unittest

from api.bands import BAND_LOWER_BOUNDS, band, band_interval, sanitize_reason


class BandTest(unittest.TestCase):
    def test_zero_and_small_bands(self) -> None:
        self.assertEqual(band(0), "0")
        self.assertEqual(band(1), "1-4")
        self.assertEqual(band(4), "1-4")
        self.assertEqual(band(5), "5-9")
        self.assertEqual(band(9), "5-9")
        self.assertEqual(band(10), "10-19")
        self.assertEqual(band(19), "10-19")

    def test_open_top_band(self) -> None:
        top = BAND_LOWER_BOUNDS[-1]
        self.assertEqual(band(top), f"{top}+")
        self.assertEqual(band(top + 1000), f"{top}+")

    def test_every_count_maps_somewhere_and_hides_plus_or_minus_one(self) -> None:
        # No two counts one apart are ever distinguishable unless they
        # straddle a band edge -- and even then only "which side", never
        # the value. Concretely: many consecutive counts share a label.
        for lo in BAND_LOWER_BOUNDS[:-1]:
            self.assertEqual(band(lo), band(lo + 1))

    def test_negative_is_zero(self) -> None:
        self.assertEqual(band(-3), "0")

    def test_band_interval_inverts_band(self) -> None:
        self.assertEqual(band_interval("0"), (0, 0))
        self.assertEqual(band_interval("1-4"), (1, 4))
        self.assertEqual(band_interval("10-19"), (10, 19))
        top = BAND_LOWER_BOUNDS[-1]
        self.assertEqual(band_interval(f"{top}+"), (top, None))
        for c in (1, 4, 5, 12, 40, 99):
            lo, hi = band_interval(band(c))
            self.assertLessEqual(lo, c)
            self.assertGreaterEqual(hi, c)


class SanitizeReasonTest(unittest.TestCase):
    def test_statistical_failure_count_becomes_a_band(self) -> None:
        out = sanitize_reason(
            "Rejected: statistical gate failed (7 qualifying reports < required 45 for n=2000)"
        )
        self.assertNotIn("(7 qualifying", out)
        self.assertIn("(5-9 qualifying reports", out)
        self.assertIn("required 45", out)  # threshold untouched
        self.assertIn("n=2000", out)       # declared population untouched

    def test_report_fraction_is_blurred(self) -> None:
        out = sanitize_reason(
            "Rejected: report fraction 0.60 exceeds maximum 0.50 (roster)"
        )
        self.assertNotIn("0.60", out)          # the exact fraction is gone
        self.assertIn("over the limit of 0.50", out)  # the policy max stays
        self.assertNotIn("exceeds maximum", out)      # no redundant phrasing

    def test_stability_note_counts_become_bands(self) -> None:
        out = sanitize_reason(
            "Disclosed: qualifying count (14) exceeded the previously disclosed "
            "scope's (8) by more than the switch margin (5); disclosure moved here."
        )
        self.assertIn("qualifying count (10-19)", out)
        self.assertIn("scope's (5-9)", out)
        self.assertIn("switch margin (5)", out)  # public policy number, kept

    def test_reason_without_a_count_is_unchanged(self) -> None:
        original = "Rejected: population n=18 below minimum privacy scope (20)"
        self.assertEqual(sanitize_reason(original), original)


if __name__ == "__main__":
    unittest.main()
