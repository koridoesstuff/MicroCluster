"""Intake submission caps (rule 11).

The system is anonymous by design, so it cannot authenticate a reporter.
The only handle it has on a submission is an opaque, ephemeral
``session_id`` the client sends with each report. This module caps how
many reports one session_id may file. That is the whole mitigation:

  * RATE LIMITING, NOT AUTHENTICATION. A report with ``session_id is
    None`` has no key to rate-limit and is always accepted. The simulator
    generates such reports (it is not modelling an intake client), so the
    normal pipeline is unaffected by this module.
  * A per-session cap is trivially defeated by using more sessions. An
    attacker who wants K fabricated reports past the cap needs
    ``ceil(K / session_submission_cap)`` sessions -- the same K reports,
    from more sources. ``adversarial.injection`` measures this directly.

Enforcement is a pure function over a batch of reports plus an
``IntakeConfig``. It is wired into ``engine.analyze`` as the first step,
so a rejection is a normal engine outcome (``AnalysisResult.intake``),
never a silent drop.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import DEFAULT_INTAKE_CONFIG, IntakeConfig
from .models import Report

__all__ = ["RejectedReport", "IntakeResult", "enforce_submission_caps"]


@dataclass(frozen=True)
class RejectedReport:
    """A report intake refused, with the reason. The report is kept so a
    caller can surface or log it -- it just never reaches detection."""

    report: Report
    reason: str


@dataclass(frozen=True)
class IntakeResult:
    accepted: tuple[Report, ...]
    rejected: tuple[RejectedReport, ...] = field(default=())

    @property
    def n_rejected(self) -> int:
        return len(self.rejected)


def enforce_submission_caps(
    reports: list[Report],
    *,
    config: IntakeConfig = DEFAULT_INTAKE_CONFIG,
) -> IntakeResult:
    """Apply the per-session and per-session-per-day submission caps.

    Reports are considered in ``submitted_at`` order (stable for ties), so
    which reports of an over-cap session get through is deterministic: the
    earliest ones, up to the cap. A report is accepted only if, counting
    it, that session_id is still within BOTH:

      * ``session_submission_cap`` reports total (the session's lifetime,
        as far as this batch shows), and
      * ``daily_submission_cap`` reports on that report's calendar date.

    ``session_id is None`` -> always accepted (nothing to key on).
    """
    ordered = sorted(
        enumerate(reports), key=lambda pair: (pair[1].submitted_at, pair[0])
    )

    session_total: dict[str, int] = {}
    session_day: dict[tuple[str, object], int] = {}
    verdicts: dict[int, RejectedReport | None] = {}

    for original_index, report in ordered:
        sid = report.session_id
        if sid is None:
            verdicts[original_index] = None
            continue

        day_key = (sid, report.submitted_at.date())
        would_be_total = session_total.get(sid, 0) + 1
        would_be_day = session_day.get(day_key, 0) + 1

        if would_be_total > config.session_submission_cap:
            verdicts[original_index] = RejectedReport(
                report,
                f"session submission cap reached "
                f"({config.session_submission_cap} per session)",
            )
        elif would_be_day > config.daily_submission_cap:
            verdicts[original_index] = RejectedReport(
                report,
                f"daily submission cap reached "
                f"({config.daily_submission_cap} per session per day)",
            )
        else:
            session_total[sid] = would_be_total
            session_day[day_key] = would_be_day
            verdicts[original_index] = None

    accepted: list[Report] = []
    rejected: list[RejectedReport] = []
    for i, report in enumerate(reports):  # original order preserved
        v = verdicts[i]
        if v is None:
            accepted.append(report)
        else:
            rejected.append(v)

    return IntakeResult(accepted=tuple(accepted), rejected=tuple(rejected))
