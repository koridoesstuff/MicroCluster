"""Scale validation and reporting-realism tests.

Scale: the largest structure that works (2,000 agents, four distinct scope
populations) must run end to end, keep the evidence gate equal to its
formula on every evaluation, and still trigger the privacy gate.

Realism: the alternative reporting model must be strictly opt-in (the
default config is unchanged and every committed result stays valid), must
reduce to the clean model when all three effects are off, and each effect
must push the reporting process in the direction it claims to.
"""

from __future__ import annotations

import math
import unittest
from dataclasses import replace

from microcluster.models import ScopeLevel
from simulation.config import (
    DEFAULT_SIMULATION_CONFIG,
    REPORTING_MODEL_CLEAN,
    REPORTING_MODEL_REALISTIC,
    SimulationConfig,
)
from simulation.pipeline import run_with_detection, simulate_and_report
from simulation.realism import RealismConfig, run_realistic
from simulation.scale import SCALE_SPECS, measure_size


def _sig(run):
    return [
        (r.disclosed_scope_id, r.reports_submitted_today, r.detection_fired)
        for r in run.daily_records
    ]


class ScaleTest(unittest.TestCase):
    def test_2000_agents_build_with_four_distinct_scope_populations(self) -> None:
        run = run_with_detection(seed=1, days=5, spec=SCALE_SPECS[2000])
        reg = run.simulation.registry
        self.assertEqual(len(run.simulation.agents), 2000)
        self.assertEqual(reg.campus_population(), 2000)
        self.assertEqual({s.population for s in reg.scopes.values()}, {2000, 500, 125, 25})
        self.assertEqual(
            {s.level for s in reg.scopes.values()},
            {ScopeLevel.CAMPUS, ScopeLevel.BUILDING, ScopeLevel.FLOOR, ScopeLevel.SUITE},
        )

    def test_evidence_gate_matches_its_formula_at_the_largest_size(self) -> None:
        r = measure_size(2000, list(range(1, 13)))
        self.assertEqual(r.errors, 0)
        self.assertGreater(r.scope_evaluations_checked, 0)
        self.assertEqual(r.threshold_formula_violations, 0)
        self.assertEqual(r.pass_flag_violations, 0)
        self.assertEqual(r.selected_without_both_gates, 0)
        # ceil(sqrt(n)) at every level of the 2,000-agent structure
        self.assertEqual(
            r.thresholds_by_level,
            {
                "CAMPUS": max(5, math.isqrt(2000) + 1),   # 45
                "BUILDING": max(5, math.isqrt(500) + 1),  # 23
                "FLOOR": max(5, math.isqrt(125) + 1),     # 12
                "SUITE": 5,
            },
        )

    def test_privacy_gate_still_triggers_at_the_largest_size(self) -> None:
        r = measure_size(2000, list(range(1, 13)))
        self.assertGreater(r.roster_refusals, 0)
        self.assertGreater(r.n_established, 0)


class RealismOptInTest(unittest.TestCase):
    def test_default_config_is_the_clean_model(self) -> None:
        self.assertEqual(DEFAULT_SIMULATION_CONFIG.reporting_model, REPORTING_MODEL_CLEAN)

    def test_unknown_reporting_model_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            SimulationConfig(reporting_model="whatever")

    def test_simulate_and_report_refuses_the_realistic_model(self) -> None:
        cfg = replace(DEFAULT_SIMULATION_CONFIG, reporting_model=REPORTING_MODEL_REALISTIC)
        with self.assertRaises(ValueError):
            simulate_and_report(seed=1, days=3, config=cfg)

    def test_run_with_detection_dispatches_on_the_config(self) -> None:
        cfg = replace(DEFAULT_SIMULATION_CONFIG, reporting_model=REPORTING_MODEL_REALISTIC)
        clean = run_with_detection(seed=4, days=30)
        realistic = run_with_detection(seed=4, days=30, config=cfg)
        self.assertNotEqual(_sig(clean), _sig(realistic))

    def test_all_effects_off_reduces_to_the_clean_model_exactly(self) -> None:
        off = RealismConfig(heterogeneity=False, correlation=False, stigma=False)
        for seed in (1, 4, 9):
            self.assertEqual(
                _sig(run_with_detection(seed=seed, days=30)),
                _sig(run_realistic(seed=seed, days=30, realism=off)),
            )

    def test_the_epidemic_is_identical_under_both_models(self) -> None:
        clean = run_with_detection(seed=7, days=30)
        realistic = run_realistic(seed=7, days=30)
        self.assertEqual(
            [tuple(s.counts.values()) for s in clean.simulation.history],
            [tuple(s.counts.values()) for s in realistic.simulation.history],
        )


class RealismEffectsTest(unittest.TestCase):
    def test_heterogeneity_keeps_the_mean_but_widens_the_spread(self) -> None:
        run = run_realistic(
            seed=3, days=0,
            realism=RealismConfig(heterogeneity=True, correlation=False, stigma=False),
        )
        p = [a.reporting_probability for a in run.simulation.agents]
        self.assertAlmostEqual(sum(p) / len(p), 0.5, delta=0.08)
        self.assertLess(min(p), 0.3)   # the clean model never goes below 0.3
        self.assertGreater(max(p), 0.7)

    def test_correlation_raises_total_reports(self) -> None:
        only_corr = RealismConfig(heterogeneity=False, correlation=True, stigma=False)
        base = corr = 0
        for seed in range(1, 21):
            base += len(run_with_detection(seed=seed, days=30).reports)
            corr += len(run_realistic(seed=seed, days=30, realism=only_corr).reports)
        self.assertGreater(corr, base)

    def test_stigma_lowers_reports_and_never_changes_the_first_disclosure(self) -> None:
        only_stigma = RealismConfig(heterogeneity=False, correlation=False, stigma=True)
        base = stig = 0
        for seed in range(1, 21):
            a = run_with_detection(seed=seed, days=30)
            b = run_realistic(seed=seed, days=30, realism=only_stigma)
            base += len(a.reports)
            stig += len(b.reports)
            # suppression only starts after a scope is named
            self.assertEqual(
                a.daily_records[-1].first_disclosed_day,
                b.daily_records[-1].first_disclosed_day,
            )
        self.assertLess(stig, base)


if __name__ == "__main__":
    unittest.main()
