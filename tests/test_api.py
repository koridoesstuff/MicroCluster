"""API-layer tests.

The engines and the simulator have their own suites; these only check the
HTTP surface: shapes, the day range, the parameter passthrough, and -- the
security-relevant one -- that a day payload carries no raw reports or
ground truth beyond the agent states the animation renders.
"""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from api.app import DISCLAIMER, app


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
        self.assertIn("does not predict real disease transmission", data["disclaimer"])
        floors = data["layout"]["floors"]
        self.assertEqual(len(floors), 2)
        self.assertEqual(sum(len(f["suites"]) for f in floors), 6)
        self.assertTrue(all(s["size"] == 25 for f in floors for s in f["suites"]))

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

    def test_web_index_is_served(self) -> None:
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("outbreak", res.text.lower())


if __name__ == "__main__":
    unittest.main()
