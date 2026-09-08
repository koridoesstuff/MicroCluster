"""Intake submission-cap tests (rule 11).

Boundary coverage: exactly at the cap, one over, the reset conditions
(a fresh session_id, and the per-day counter rolling at midnight), the
session_id=None exemption, and that a rejection is surfaced (report kept
plus a reason) rather than silently dropped.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from microcluster.config import IntakeConfig
from microcluster.engine import analyze
from microcluster.intake import enforce_submission_caps
from microcluster.models import (
    Category,
    Onset,
    Report,
    Scope,
    ScopeLevel,
    ScopeRegistry,
)

_DAY0 = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
_CFG = IntakeConfig(session_submission_cap=3, daily_submission_cap=10)


def _report(session_id: str | None, *, when: datetime = _DAY0, loc: str = "S1") -> Report:
    return Report(
        category=Category.GENERAL,
        symptom="fever",
        onset=Onset.TODAY,
        location_id=loc,
        submitted_at=when,
        session_id=session_id,
    )


class SessionCapTest(unittest.TestCase):
    def test_reports_up_to_the_cap_are_all_accepted(self) -> None:
        reports = [_report("s") for _ in range(_CFG.session_submission_cap)]
        result = enforce_submission_caps(reports, config=_CFG)
        self.assertEqual(len(result.accepted), 3)
        self.assertEqual(result.rejected, ())

    def test_one_over_the_cap_is_rejected_not_dropped(self) -> None:
        reports = [_report("s") for _ in range(_CFG.session_submission_cap + 1)]
        result = enforce_submission_caps(reports, config=_CFG)
        self.assertEqual(len(result.accepted), 3)
        self.assertEqual(result.n_rejected, 1)
        rej = result.rejected[0]
        self.assertIs(rej.report, reports[-1])          # the report is kept
        self.assertIn("session submission cap", rej.reason)  # with a reason

    def test_the_earliest_reports_win_when_a_session_is_over_cap(self) -> None:
        early = [_report("s", when=_DAY0 + timedelta(minutes=i)) for i in range(3)]
        late = _report("s", when=_DAY0 + timedelta(hours=5))
        result = enforce_submission_caps([*early, late], config=_CFG)
        self.assertEqual(list(result.accepted), early)
        self.assertEqual(result.rejected[0].report, late)

    def test_a_fresh_session_id_resets_the_allowance(self) -> None:
        reports = [_report("s1") for _ in range(4)] + [_report("s2") for _ in range(3)]
        result = enforce_submission_caps(reports, config=_CFG)
        # s1: 3 in, 1 out.  s2: a different key, all 3 in.
        self.assertEqual(len(result.accepted), 6)
        self.assertEqual(result.n_rejected, 1)

    def test_none_session_id_is_never_rate_limited(self) -> None:
        reports = [_report(None) for _ in range(50)]
        result = enforce_submission_caps(reports, config=_CFG)
        self.assertEqual(len(result.accepted), 50)
        self.assertEqual(result.rejected, ())

    def test_accepted_order_is_preserved(self) -> None:
        reports = [
            _report(None, loc="A"),
            _report("s", loc="B"),
            _report(None, loc="C"),
            _report("s", loc="D"),
        ]
        accepted = enforce_submission_caps(reports, config=_CFG).accepted
        self.assertEqual([r.location_id for r in accepted], ["A", "B", "C", "D"])


class DailyCapResetTest(unittest.TestCase):
    def test_daily_cap_bites_within_one_day(self) -> None:
        cfg = IntakeConfig(session_submission_cap=100, daily_submission_cap=4)
        reports = [_report("s", when=_DAY0 + timedelta(minutes=i)) for i in range(6)]
        result = enforce_submission_caps(reports, config=cfg)
        self.assertEqual(len(result.accepted), 4)
        self.assertEqual(result.n_rejected, 2)
        self.assertIn("daily submission cap", result.rejected[0].reason)

    def test_daily_counter_resets_on_the_next_calendar_day(self) -> None:
        cfg = IntakeConfig(session_submission_cap=100, daily_submission_cap=4)
        day1 = [_report("s", when=_DAY0 + timedelta(minutes=i)) for i in range(6)]
        day2 = [_report("s", when=_DAY0 + timedelta(days=1, minutes=i)) for i in range(3)]
        result = enforce_submission_caps([*day1, *day2], config=cfg)
        # day 1: 4 of 6.  day 2: fresh allowance, all 3.
        self.assertEqual(len(result.accepted), 7)
        self.assertEqual(result.n_rejected, 2)


class EngineWiringTest(unittest.TestCase):
    """The cap is a normal engine outcome, not a frontend concern."""

    def _registry(self) -> ScopeRegistry:
        return ScopeRegistry({
            "C": Scope("C", "Campus", ScopeLevel.CAMPUS, 40),
            "C-S": Scope("C-S", "Suite", ScopeLevel.SUITE, 40, parent_id="C"),
        })

    def test_analyze_reports_intake_rejections(self) -> None:
        reg = self._registry()
        reports = [_report("flood", loc="C-S") for _ in range(9)]
        result = analyze(reports, reg, now=_DAY0, intake_config=_CFG)
        self.assertIsNotNone(result.intake)
        self.assertEqual(len(result.intake.accepted), 3)
        self.assertEqual(len(result.intake_rejected), 6)

    def test_intake_config_none_skips_the_caps(self) -> None:
        reg = self._registry()
        reports = [_report("flood", loc="C-S") for _ in range(9)]
        result = analyze(reports, reg, now=_DAY0, intake_config=None)
        self.assertIsNone(result.intake)

    def test_anonymous_simulator_style_stream_is_untouched(self) -> None:
        # every simulator Report has session_id=None -> nothing is capped
        reg = self._registry()
        reports = [_report(None, loc="C-S") for _ in range(30)]
        with_caps = analyze(reports, reg, now=_DAY0)
        without = analyze(reports, reg, now=_DAY0, intake_config=None)
        self.assertEqual(with_caps.intake_rejected, ())
        self.assertEqual(
            with_caps.detection.qualifying_scope_counts,
            without.detection.qualifying_scope_counts,
        )


if __name__ == "__main__":
    unittest.main()
