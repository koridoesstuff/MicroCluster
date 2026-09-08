"""Thin wiring between the engines.

Order is fixed (rule 10): intake caps first, then detection, then -- only
if detection fired -- disclosure. The disclosure engine receives the
detection engine's aggregate per-scope table, never the reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from datetime import datetime

from . import detection, disclosure, intake
from .config import (
    DEFAULT_DETECTION_CONFIG,
    DEFAULT_DISCLOSURE_CONFIG,
    DEFAULT_INTAKE_CONFIG,
    DetectionConfig,
    DisclosureConfig,
    IntakeConfig,
)
from .detection import DetectionResult, HysteresisState
from .disclosure import DisclosureResult
from .intake import IntakeResult, RejectedReport
from .models import Report, ScopeRegistry

__all__ = ["AnalysisResult", "analyze"]


@dataclass(frozen=True)
class AnalysisResult:
    detection: DetectionResult
    disclosure: DisclosureResult
    intake: IntakeResult | None = field(default=None)

    @property
    def disclosed_scope_id(self) -> str | None:
        return self.disclosure.disclosed_scope_id

    @property
    def intake_rejected(self) -> tuple[RejectedReport, ...]:
        return () if self.intake is None else self.intake.rejected


def analyze(
    reports: list[Report],
    registry: ScopeRegistry,
    *,
    now: datetime | None = None,
    detection_config: DetectionConfig = DEFAULT_DETECTION_CONFIG,
    disclosure_config: DisclosureConfig = DEFAULT_DISCLOSURE_CONFIG,
    intake_config: IntakeConfig | None = DEFAULT_INTAKE_CONFIG,
    hysteresis_state: HysteresisState | None = None,
    prior_disclosed_scope_id: str | None = None,
) -> AnalysisResult:
    """Run intake caps, then detection, then -- if it fired -- disclosure.

    ``intake_config`` applies the per-session submission caps (rule 11)
    before detection sees anything; only ``accepted`` reports go forward,
    and any rejections are on ``result.intake``. Reports with no
    ``session_id`` are never rate-limited, so a stream of anonymous
    simulator reports is unaffected. Pass ``intake_config=None`` to skip
    the caps entirely (``result.intake`` is then ``None``).

    ``hysteresis_state`` and ``prior_disclosed_scope_id`` thread state from
    the PREVIOUS call in a sequence (e.g. yesterday's ``AnalysisResult``);
    omit both for a one-off analysis. The next hysteresis state to pass
    into the following call is on ``result.detection.hysteresis_state``,
    and the scope to pass as next call's ``prior_disclosed_scope_id`` is
    ``result.disclosed_scope_id``.
    """
    intake_result: IntakeResult | None = None
    if intake_config is not None:
        intake_result = intake.enforce_submission_caps(reports, config=intake_config)
        reports = list(intake_result.accepted)

    det = detection.evaluate(
        reports, registry, now=now, config=detection_config, hysteresis_state=hysteresis_state
    )

    if not det.fired:
        # Nothing detected -> the disclosure engine does not run at all.
        return AnalysisResult(
            det,
            DisclosureResult(evaluations=(), disclosed_scope_id=None),
            intake_result,
        )

    dis = disclosure.evaluate(
        registry,
        det.qualifying_scope_counts,
        config=disclosure_config,
        prior_disclosed_scope_id=prior_disclosed_scope_id,
    )
    return AnalysisResult(det, dis, intake_result)
