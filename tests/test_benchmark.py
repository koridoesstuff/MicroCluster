"""Benchmark tests.

The dataset builder and the scoring logic are exercised on small, short
simulated runs -- enough seeds for both label classes to appear, few
enough to stay fast. The cross-regime harness is run once at a tiny size
to prove it wires together.
"""

from __future__ import annotations

import unittest

from simulation.benchmark import (
    FEATURE_NAMES,
    DayRow,
    benchmark_cross_regime,
    build_dataset,
    score_model,
    score_rows,
    score_rules,
    split_by_run,
    train_model,
)


class DatasetShapeTest(unittest.TestCase):
    def test_one_row_per_run_day_including_day_zero(self) -> None:
        rows = build_dataset([1, 2, 3], days=10)
        self.assertEqual(len(rows), 3 * 11)
        for seed in (1, 2, 3):
            days = sorted(r.day for r in rows if r.seed == seed)
            self.assertEqual(days, list(range(11)))

    def test_features_and_label_are_well_formed(self) -> None:
        for r in build_dataset([1, 2], days=10):
            self.assertIn(r.label, (0, 1))
            self.assertIsInstance(r.rule_fired, bool)
            self.assertGreaterEqual(r.relative_excess_ratio, 0.0)
            self.assertGreaterEqual(r.count_within_window, 0)
            self.assertGreaterEqual(r.count_within_window, r.count_sharing_category)

    def test_three_named_features(self) -> None:
        self.assertEqual(
            FEATURE_NAMES,
            ("relative_excess_ratio", "count_within_window", "count_sharing_category"),
        )

    def test_deterministic(self) -> None:
        self.assertEqual(build_dataset([1, 2], days=8), build_dataset([1, 2], days=8))

    def test_day_zero_is_never_an_established_outbreak(self) -> None:
        for r in build_dataset([1, 2, 3, 4, 5], days=6):
            if r.day == 0:
                self.assertEqual(r.label, 0)


class SplitByRunTest(unittest.TestCase):
    def test_no_seed_in_both_halves(self) -> None:
        rows = build_dataset(list(range(1, 11)), days=6)
        train, test = split_by_run(rows)
        self.assertTrue(train and test)
        self.assertEqual(
            set(r.seed for r in train) & set(r.seed for r in test), set()
        )

    def test_stable_given_the_split_seed(self) -> None:
        rows = build_dataset(list(range(1, 11)), days=6)
        a = split_by_run(rows, split_seed=99)
        b = split_by_run(rows, split_seed=99)
        self.assertEqual([r.seed for r in a[1]], [r.seed for r in b[1]])


class TrainingTest(unittest.TestCase):
    def test_single_class_training_set_is_rejected(self) -> None:
        rows = [DayRow(1, d, 0.0, 0, 0, 0, False) for d in range(5)]
        with self.assertRaises(ValueError):
            train_model(rows, kind="logistic")

    def test_unknown_kind_is_rejected(self) -> None:
        rows = build_dataset([1, 2, 3, 4], days=12)
        with self.assertRaises(ValueError):
            train_model(rows, kind="forest")

    def test_both_model_kinds_fit_and_score(self) -> None:
        rows = build_dataset(list(range(1, 13)), days=15)
        train, test = split_by_run(rows)
        for kind in ("logistic", "tree"):
            model = train_model(train, kind=kind)
            score = score_model(model, test, label=kind)
            self.assertGreaterEqual(score.precision, 0.0)
            self.assertLessEqual(score.precision, 1.0)
            self.assertGreaterEqual(score.recall, 0.0)
            self.assertLessEqual(score.recall, 1.0)


class ScoreRowsTest(unittest.TestCase):
    def _rows(self) -> list[DayRow]:
        # Seed 1: outbreak days 2..4. Seed 2: no outbreak.
        return [
            DayRow(1, 0, 0.0, 0, 0, 0, False),
            DayRow(1, 1, 0.0, 0, 0, 0, False),
            DayRow(1, 2, 0.0, 0, 0, 1, False),
            DayRow(1, 3, 0.0, 0, 0, 1, False),
            DayRow(1, 4, 0.0, 0, 0, 1, False),
            DayRow(2, 0, 0.0, 0, 0, 0, False),
            DayRow(2, 1, 0.0, 0, 0, 0, False),
        ]

    def test_perfect_prediction(self) -> None:
        rows = self._rows()
        preds = [r.label for r in rows]
        s = score_rows(rows, preds, label="perfect")
        self.assertEqual((s.precision, s.recall), (1.0, 1.0))
        self.assertEqual(s.mean_detection_delay, 0.0)
        self.assertEqual((s.n_runs_with_outbreak, s.n_runs_detected), (1, 1))

    def test_late_and_missed_detection(self) -> None:
        rows = self._rows()
        # fire only on day 4 for seed 1 -> delay 2; never for seed 2 (fine).
        preds = [1 if (r.seed == 1 and r.day == 4) else 0 for r in rows]
        s = score_rows(rows, preds, label="late")
        self.assertEqual(s.mean_detection_delay, 2.0)
        self.assertEqual(s.never_detected_runs, 0)

    def test_never_detected_run_is_counted(self) -> None:
        rows = self._rows()
        s = score_rows(rows, [0] * len(rows), label="silent")
        self.assertEqual(s.never_detected_runs, 1)
        self.assertIsNone(s.mean_detection_delay)
        self.assertEqual(s.recall, 0.0)

    def test_score_rules_uses_the_rule_fired_flag(self) -> None:
        rows = [
            DayRow(1, 0, 0.0, 0, 0, 0, False),
            DayRow(1, 1, 0.0, 0, 0, 1, True),
        ]
        s = score_rules(rows)
        self.assertEqual(s.n_predicted_positive, 1)
        self.assertEqual(s.recall, 1.0)


class CrossRegimeHarnessTest(unittest.TestCase):
    def test_runs_end_to_end_at_a_tiny_size(self) -> None:
        results = benchmark_cross_regime(
            train_seeds=list(range(1, 11)),
            test_seeds=list(range(11, 17)),
            days=15,
            test_suite_transmissions=(0.012,),
        )
        self.assertEqual(len(results), 1)
        res = results[0]
        self.assertEqual(len(res.scores), 3)
        self.assertEqual(res.scores[0].label, "authored rules")
        self.assertGreater(res.n_test_rows, 0)


if __name__ == "__main__":
    unittest.main()
