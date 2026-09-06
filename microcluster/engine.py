"""Thin wiring between the two engines.

Order is fixed (rule 10): detection first, then -- only if detection fired
-- disclosure. The disclosure engine receives the detection engine's
aggregate per-scope table, never the reports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from . import detection, disclosure
from .config import (
    DEFAULT_DETECTION_CONFIG,
    DEFAULT_DISCLOSURE_CONFIG,
    DetectionConfig,
    DisclosureConfig,
)
from .detection import DetectionResult, HysteresisState
from .disclosure import DisclosureResult
from .models import Report, ScopeRegistry

__all__ = ["AnalysisResult", "analyze"]


@dataclass(frozen=True)
class AnalysisResult:
    detection: DetectionResult
    disclosure: DisclosureResult

    @property
    def disclosed_scope_id(self) -> str | None:
        return self.disclosure.disclosed_scope_id


def analyze(
    reports: list[Report],
    registry: ScopeRegistry,
    *,
    now: datetime | None = None,
    detection_config: DetectionConfig = DEFAULT_DETECTION_CONFIG,
    disclosure_config: DisclosureConfig = DEFAULT_DISCLOSURE_CONFIG,
    hysteresis_state: HysteresisState | None = None,
    prior_disclosed_scope_id: str | None = None,
) -> AnalysisResult:
    """Run detection then, if it fired, disclosure.

    ``hysteresis_state`` and ``prior_disclosed_scope_id`` thread state from
    the PREVIOUS call in a sequence (e.g. yesterday's ``AnalysisResult``);
    omit both for a one-off analysis. The next hysteresis state to pass
    into the following call is on ``result.detection.hysteresis_state``,
    and the scope to pass as next call's ``prior_disclosed_scope_id`` is
    ``result.disclosed_scope_id``.
    """
    det = detection.evaluate(
        reports, registry, now=now, config=detection_config, hysteresis_state=hysteresis_state
    )

    if not det.fired:
        # Nothing detected -> the disclosure engine does not run at all.
        return AnalysisResult(det, DisclosureResult(evaluations=(), disclosed_scope_id=None))

    dis = disclosure.evaluate(
        registry,
        det.qualifying_scope_counts,
        config=disclosure_config,
        prior_disclosed_scope_id=prior_disclosed_scope_id,
    )
    return AnalysisResult(det, dis)
