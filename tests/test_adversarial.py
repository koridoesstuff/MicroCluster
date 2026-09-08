"""Adversarial self-test tests.

The important ones are on the ATTACK: the differencing attack must
provably pin a one-person overnight change when it is handed exact counts,
otherwise the banded-vs-exact contrast demonstrates nothing.
"""

from __future__ import annotations

import unittest

from api.bands import band
from adversarial.differencing import attack
from adversarial.observer import DayView, observe
from adversarial.selftest import run_self_test
from adversarial.wandering import measure_wandering
from simulation.pipeline import run_with_detection, simulate_and_report


def _views(scope, counts, *, exact):
    out = []
    for i, c in enumerate(counts):
        out.append(
            DayView(
                day=i,
                scope_id=scope,
                scope_label=scope,
                scope_level="SUITE",
                exact_count=c if exact else None,
                band=None if exact else band(c),
            )
        )
    return out


class DifferencingAgainstExactCountsTest(unittest.TestCase):
    def test_pins_every_one_person_overnight_change(self) -> None:
        out = attack(_views("S", [7, 8, 9, 8, 8], exact=True), mode="exact")
        self.assertEqual(out.same_scope_pairs, 4)
        self.assertEqual(out.pinned_exactly, 4)
        self.assertEqual(out.one_person_pinned, 3)
        self.assertEqual(out.direction_known, 3)
        self.assertEqual(out.unbounded_pairs, 0)

    def test_two_person_change_is_pinned_but_not_one_person(self) -> None:
        out = attack(_views("S", [10, 12], exact=True), mode="exact")
        self.assertEqual(out.pinned_exactly, 1)
        self.assertEqual(out.one_person_pinned, 0)

    def test_a_scope_change_between_days_yields_no_pair(self) -> None:
        views = [
            DayView(0, "A", "A", "SUITE", 7, None),
            DayView(1, "B", "B", "SUITE", 8, None),
        ]
        self.assertEqual(attack(views, mode="exact").same_scope_pairs, 0)


class DifferencingAgainstBandsTest(unittest.TestCase):
    def test_one_person_pin_is_impossible(self) -> None:
        out = attack(_views("S", [7, 8, 9, 8, 8], exact=False), mode="band")
        self.assertEqual(out.same_scope_pairs, 4)
        self.assertEqual(out.one_person_pinned, 0)
        self.assertEqual(out.pinned_exactly, 0)

    def test_direction_can_still_leak_across_a_band_edge(self) -> None:
        out = attack(_views("S", [9, 10], exact=False), mode="band")
        self.assertEqual(out.one_person_pinned, 0)
        self.assertEqual(out.direction_known, 1)

    def test_within_a_band_nothing_leaks(self) -> None:
        out = attack(_views("S", [5, 9], exact=False), mode="band")
        self.assertEqual(out.direction_known, 0)
        self.assertGreater(out.median_possible_values, 1)


class ObserverTest(unittest.TestCase):
    def test_exact_and_band_views_populate_exactly_one_count_field(self) -> None:
        run = run_with_detection(seed=4, days=30)
        exact = observe(run.daily_records, leak_exact_counts=True)
        banded = observe(run.daily_records, leak_exact_counts=False)
        self.assertEqual(len(exact), len(run.daily_records))
        for ev, bv, rec in zip(exact, banded, run.daily_records):
            if rec.disclosed_scope_id is None:
                self.assertIsNone(ev.scope_id)
                continue
            self.assertIsNotNone(ev.exact_count)
            self.assertIsNone(ev.band)
            self.assertIsNone(bv.exact_count)
            self.assertEqual(bv.band, band(ev.exact_count))

    def test_exact_count_matches_the_selected_scope_evaluation(self) -> None:
        run = run_with_detection(seed=4, days=30)
        for rec, view in zip(run.daily_records, observe(run.daily_records, leak_exact_counts=True)):
            if rec.disclosed_scope_id is None:
                continue
            selected = next(
                e for e in rec.disclosure_evaluations if e.scope_id == rec.disclosed_scope_id
            )
            self.assertEqual(view.exact_count, selected.qualifying_reports)


class WanderingTest(unittest.TestCase):
    def test_stability_off_names_more_groups_in_aggregate(self) -> None:
        total_on = total_off = 0
        for seed in range(1, 16):
            w = measure_wandering(simulate_and_report(seed=seed, days=30))
            total_on += w.stability_on
            total_off += w.stability_off
        self.assertLess(total_on, total_off)


class SelfTestIntegrationTest(unittest.TestCase):
    def test_attack_succeeds_on_exact_and_fails_on_bands(self) -> None:
        s = run_self_test(seeds=list(range(1, 25)))
        self.assertGreater(s.same_scope_pairs, 0)
        self.assertGreater(
            s.exact_one_person_pinned, 0, "differencing attack proved nothing against exact counts"
        )
        self.assertEqual(s.band_one_person_pinned, 0)
        self.assertGreaterEqual(s.wandering_off_mean, s.wandering_on_mean)


class InjectionAttackTest(unittest.TestCase):
    """The intake cap must raise the attacker's session count without
    claiming to close the hole -- exactly what the docs say it does."""

    def test_cap_blocks_one_session_but_not_a_session_rotating_attacker(self) -> None:
        from adversarial.injection import measure_injection

        r = measure_injection()  # target FLOOR C-B1-F2, declared population 75
        self.assertEqual(r.target_level, "FLOOR")

        # the report count is set by the statistical gate, not the cap
        self.assertEqual(r.reports_to_disclose, 9)  # ceil(sqrt(75)) = 9
        self.assertEqual(r.sessions_without_cap, 1)
        self.assertEqual(
            r.sessions_with_cap,
            -(-r.reports_to_disclose // r.session_cap),  # ceil(9 / 3) = 3
        )

        # the cap stops a single-session flood ...
        self.assertFalse(r.single_session_attack_succeeds)
        # ... and does nothing against an attacker who rotates sessions
        self.assertTrue(r.multi_session_attack_succeeds)


if __name__ == "__main__":
    unittest.main()
