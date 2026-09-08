"""API-layer tests.

The engines and the simulator have their own suites; these only check the
HTTP surface: shapes, the day range, the parameter passthrough, and -- the
security-relevant one -- that a day payload carries no raw reports or
ground truth beyond the agent states the animation renders.
"""

from __future__ import annotations

import unittest

import re

from fastapi.testclient import TestClient

from api.app import DISCLAIMER, app

# High transmission + near-certain reporting: a suite reliably blows past
# the report-fraction cap and fails the privacy gate (the "roster" refusal).
_ROSTER_PARAMS = {
    "suite_transmission_probability": 0.03,
    "floor_transmission_probability": 0.002,
    "building_transmission_probability": 0.0005,
    "reporting_probability_min": 0.85,
    "reporting_probability_max": 1.0,
    "background_noise_daily_rate": 0.003,
}
_BAND_RE = re.compile(r"^(0|\d+-\d+|\d+\+)$")


class ApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def _run(self, **body) -> dict:
        body.setdefault("seed", 4)
        body.setdefault("days", 12)
        res = self.client.post("/api/run", json=body)
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def test_run_returns_id_layout_and_always_visible_disclaimer(self) -> None:
        data = self._run()
        self.assertIn("run_id", data)
        self.assertEqual(data["disclaimer"], DISCLAIMER)
        self.assertIn("predicts nothing about any real building", data["disclaimer"])
        self.assertIn("no one is diagnosed or treated", data["disclaimer"])
        floors = data["layout"]["floors"]
        self.assertEqual(len(floors), 2)
        self.assertEqual(sum(len(f["suites"]) for f in floors), 6)
        self.assertTrue(all(s["size"] == 25 for f in floors for s in f["suites"]))

    def test_population_and_detection_window_controls_take_effect(self) -> None:
        data = self._run(population=30, detection_window_hours=48, days=10)
        self.assertEqual(data["params"]["population_per_suite"], 30)
        self.assertEqual(data["params"]["total_population"], 180)
        self.assertEqual(data["params"]["detection_window_hours"], 48)
        day = self.client.get(f"/api/run/{data['run_id']}/day/5").json()
        self.assertEqual(len(day["agents"]), 180)

    def test_out_of_range_controls_are_422_not_500(self) -> None:
        self.assertEqual(self.client.post("/api/run", json={"seed": 1, "population": 15}).status_code, 422)
        self.assertEqual(
            self.client.post("/api/run", json={"seed": 1, "detection_window_hours": 6}).status_code,
            422,
        )

    def test_assets_are_served_no_cache(self) -> None:
        res = self.client.get("/style.css")
        self.assertEqual(res.status_code, 200)
        self.assertIn("no-cache", res.headers.get("cache-control", ""))
        api_res = self.client.get("/api/health")
        self.assertNotIn("no-cache", api_res.headers.get("cache-control", ""))

    def test_day_zero_and_last_day_are_in_range_and_beyond_is_404(self) -> None:
        data = self._run(days=10)
        rid = data["run_id"]
        self.assertEqual(self.client.get(f"/api/run/{rid}/day/0").status_code, 200)
        self.assertEqual(self.client.get(f"/api/run/{rid}/day/10").status_code, 200)
        self.assertEqual(self.client.get(f"/api/run/{rid}/day/11").status_code, 404)
        self.assertEqual(self.client.get(f"/api/run/{rid}/day/-1").status_code, 404)

    def test_unknown_run_is_404(self) -> None:
        self.assertEqual(self.client.get("/api/run/deadbeef/day/0").status_code, 404)

    def test_day_payload_shape(self) -> None:
        data = self._run(days=8)
        day = self.client.get(f"/api/run/{data['run_id']}/day/5").json()
        self.assertEqual(day["day"], 5)
        self.assertEqual(len(day["agents"]), 150)
        for agent in day["agents"]:
            self.assertEqual(set(agent), {"suite", "floor", "i", "state"})
            self.assertIn(
                agent["state"],
                {"susceptible", "incubating", "symptomatic", "recovered"},
            )
        self.assertEqual(set(day["detection"]), {"fired", "relative", "absolute"})
        self.assertEqual(
            sum(day["counts"].values()), 150, "counts must cover every agent once"
        )

    def test_day_payload_leaks_no_reports_or_extra_ground_truth(self) -> None:
        # Whitelist exactly the keys the animation consumes. Anything else
        # -- a report list, per-agent infection timing, who-infected-whom --
        # would be a firewall break.
        data = self._run(days=6)
        day = self.client.get(f"/api/run/{data['run_id']}/day/3").json()
        self.assertEqual(
            set(day),
            {
                "day",
                "counts",
                "agents",
                "detection",
                "disclosure",
                "evaluations",
                "first_fired_day",
                "first_disclosed_day",
                "disclaimer",
            },
        )
        for agent in day["agents"]:
            self.assertNotIn("id", agent)
            self.assertNotIn("state_changed_day", agent)
            self.assertNotIn("incubation_days", agent)

    def test_seed_4_establishes_and_eventually_discloses_a_scope(self) -> None:
        data = self._run(seed=4, days=30)
        rid = data["run_id"]
        last = self.client.get(f"/api/run/{rid}/day/30").json()
        self.assertGreater(last["counts"]["recovered"], 50)  # a real outbreak ran
        self.assertIsNotNone(last["first_fired_day"])
        self.assertIsNotNone(last["first_disclosed_day"])
        self.assertLessEqual(last["first_fired_day"], last["first_disclosed_day"])
        self.assertIsNotNone(last["disclosure"])
        self.assertIn(last["disclosure"]["level"], {"SUITE", "FLOOR", "BUILDING", "CAMPUS"})

    def test_parameter_passthrough_and_validation(self) -> None:
        echoed = self._run(background_noise_daily_rate=0.02)["params"]
        self.assertAlmostEqual(echoed["background_noise_daily_rate"], 0.02)
        # min > max is rejected by SimulationConfig -> 422, not a 500.
        bad = self.client.post(
            "/api/run",
            json={"seed": 1, "reporting_probability_min": 0.9, "reporting_probability_max": 0.1},
        )
        self.assertEqual(bad.status_code, 422)

    def test_evaluations_shape_and_ordering(self) -> None:
        data = self._run(seed=4, days=30)
        rid = data["run_id"]
        levels_rank = {"CAMPUS": 1, "BUILDING": 2, "FLOOR": 3, "SUITE": 4}
        saw_a_firing_day = False
        for n in range(31):
            day = self.client.get(f"/api/run/{rid}/day/{n}").json()
            evs = day["evaluations"]
            if day["detection"]["fired"] and day["disclosure"] is not None:
                saw_a_firing_day = saw_a_firing_day or len(evs) > 0
            order_key = [(levels_rank[e["level"]], -e["population"]) for e in evs]
            self.assertEqual(
                order_key, sorted(order_key),
                "evaluations must be ordered coarsest -> finest",
            )
            for e in evs:
                self.assertEqual(
                    set(e),
                    {
                        "scope_id", "label", "level", "population", "qualifying_band",
                        "statistical_threshold", "statistical_pass", "min_population_pass",
                        "report_fraction_pass", "privacy_pass", "eligible", "selected",
                        "reason",
                    },
                )
                self.assertNotIn("qualifying_reports", e)
                self.assertNotIn("report_fraction", e)
                self.assertRegex(e["qualifying_band"], _BAND_RE)
        self.assertTrue(saw_a_firing_day)

    def test_exact_qualifying_count_never_appears_in_a_reason(self) -> None:
        # Cross-check against the engine's own numbers, computed here.
        from simulation.config import SimulationConfig
        from simulation.pipeline import run_with_detection

        run = run_with_detection(seed=4, days=30, config=SimulationConfig())
        data = self._run(seed=4, days=30)
        rid = data["run_id"]
        for record in run.daily_records:
            if not record.disclosure_evaluations:
                continue
            day = self.client.get(f"/api/run/{rid}/day/{record.day}").json()
            api_reasons = " || ".join(e["reason"] for e in day["evaluations"])
            for ev in record.disclosure_evaluations:
                exact = ev.qualifying_reports
                self.assertNotIn(f"({exact} qualifying reports", api_reasons)
                self.assertNotIn(f"qualifying count ({exact})", api_reasons)

    def test_slider_wall_data_exists_when_a_suite_fails_privacy(self) -> None:
        data = self._run(seed=4, days=30, **_ROSTER_PARAMS)
        rid = data["run_id"]
        found_wall = False
        for n in range(31):
            evs = self.client.get(f"/api/run/{rid}/day/{n}").json()["evaluations"]
            passed_then_failed = any(
                evs[i]["privacy_pass"] and not evs[j]["privacy_pass"]
                for i in range(len(evs))
                for j in range(i + 1, len(evs))
            )
            suite_roster_fail = [
                e for e in evs
                if e["level"] == "SUITE"
                and not e["privacy_pass"]
                and e["min_population_pass"]
                and not e["report_fraction_pass"]
            ]
            if passed_then_failed and suite_roster_fail:
                found_wall = True
                self.assertIn("over the limit", suite_roster_fail[0]["reason"])
                break
        self.assertTrue(found_wall, "expected a day with a coarser pass then a suite privacy fail")

    def test_layout_endpoint_serves_prerun_structure(self) -> None:
        res = self.client.get("/api/layout")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        floors = data["layout"]["floors"]
        self.assertEqual(len(floors), 2)
        self.assertEqual(sum(len(f["suites"]) for f in floors), 6)
        self.assertEqual(data["params"]["total_population"], 150)
        self.assertIn("predicts nothing about any real building", data["disclaimer"])

    def test_layout_endpoint_honours_population_and_rejects_bad_values(self) -> None:
        data = self.client.get("/api/layout?population=30").json()
        self.assertEqual(data["params"]["total_population"], 180)
        self.assertEqual(self.client.get("/api/layout?population=5").status_code, 422)

    def test_web_index_is_served(self) -> None:
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("outbreak", res.text.lower())

    def test_static_pages_are_served(self) -> None:
        for page, needle in (("terms.html", "terms of service"), ("privacy.html", "privacy")):
            res = self.client.get(f"/{page}")
            self.assertEqual(res.status_code, 200, page)
            self.assertIn(needle, res.text.lower())

    def test_precomputed_results_are_served_and_shaped(self) -> None:
        sweep = self.client.get("/api/results/disclosure_sweep")
        self.assertEqual(sweep.status_code, 200)
        sweep = sweep.json()
        self.assertIn(sweep["primary_sweep"], sweep["sweeps"])
        self.assertTrue(sweep["sweeps"][sweep["primary_sweep"]]["rows"])

        bench = self.client.get("/api/results/benchmark").json()
        self.assertEqual(set(bench["in_distribution"]), {"rules", "model"})
        self.assertEqual(len(bench["cross_regime"]), 2)
        self.assertIn("cross_regime_conclusion", bench)
        blocks = [bench["in_distribution"]] + bench["cross_regime"]
        for block in blocks:
            for who in ("rules", "model"):
                self.assertLessEqual(block[who]["precision"], 1.0)
                self.assertLessEqual(block[who]["recall"], 1.0)

        adv = self.client.get("/api/results/adversarial").json()
        self.assertGreater(adv["exact_one_person_pins"], adv["band_one_person_pins"])
        self.assertEqual(adv["band_one_person_pins"], 0)

    def test_unknown_results_file_is_404(self) -> None:
        self.assertEqual(self.client.get("/api/results/secrets").status_code, 404)


if __name__ == "__main__":
    unittest.main()
