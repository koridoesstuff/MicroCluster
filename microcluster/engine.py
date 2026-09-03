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
from .detection import DetectionResult
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
) -> AnalysisResult:
    det = detection.evaluate(reports, registry, now=now, config=detection_config)

    if not det.fired:
        # Nothing detected -> the disclosure engine does not run at all.
        return AnalysisResult(det, DisclosureResult(evaluations=(), disclosed_scope_id=None))

    dis = disclosure.evaluate(
        registry, det.qualifying_scope_counts, config=disclosure_config
    )
    return AnalysisResult(det, dis)
