"""Policy constants and configuration for MicroCluster.

EVERYTHING IN THIS MODULE IS A PROJECT-DEFINED POLICY, NOT A PROVEN LAW.

Each value is:
  - named (nothing here is inlined into scoring code),
  - configurable (via ``DetectionConfig`` / ``DisclosureConfig``),
  - a deliberate choice, explained in the comment beside it and in
    ``CLAUDE.md``.

None of these is derived from an epidemiological or statistical result.
``ceil(sqrt(n))`` is a reasonable *shape* for "evidence should scale with
the size of the claim" -- not a theorem about this problem.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Detection window (rule 5)
# ---------------------------------------------------------------------------

# How recently a report must have been submitted to count as "current
# activity". Policy choice. Default 72 hours.
DETECTION_WINDOW_HOURS: int = 72


# ---------------------------------------------------------------------------
# Absolute detector (rule 3, rule 4)
# ---------------------------------------------------------------------------

# BACKGROUND_RATE: the approximate fraction of a population expected to
# submit a qualifying symptom report within ONE detection window under
# ordinary, non-outbreak conditions.
#
# THIS IS AN ILLUSTRATIVE FIGURE. IT IS NOT A CLINICAL OR EPIDEMIOLOGICAL
# ESTIMATE. It exists only to give the absolute detector a reference point
# to compare against. Before trusting the absolute detector for a real
# community, replace this with a rate measured from that community's own
# quiet-period baseline.
BACKGROUND_RATE: float = 0.02

# The absolute detector fires when the observed within-window report count
# reaches this multiple of the background expectation
# (BACKGROUND_RATE * declared campus population). Policy choice.
ABSOLUTE_EXCESS_RATIO: float = 1.5


# ---------------------------------------------------------------------------
# Relative detector (rule 3)
# ---------------------------------------------------------------------------

# The relative detector fires when a location's per-capita within-window
# report rate reaches this multiple of its contemporaneous peers' pooled
# per-capita rate. Policy choice.
RELATIVE_EXCESS_RATIO: float = 2.0

# Additive (Laplace) smoothing applied to BOTH sides of the relative
# excess ratio:
#
#   (reports_here + k) / (n_here + k)   divided by
#   (reports_control + k) / (n_control + k)
#
# Without it, a small quiet peer group drives the control rate to nearly
# zero and the ratio explodes to hundreds or infinity -- a number that
# looks precise but is dominated by division noise. k pulls both rates
# toward a neutral prior; the ratio stays finite and interpretable.
# Policy choice. Default 1 (one pseudo-report per pseudo-person).
RELATIVE_SMOOTHING: float = 1.0

# ...and only if that location has at least this many within-window
# reports. Without a floor, one report in a tiny group produces an
# enormous ratio and constant false positives. Policy choice.
MIN_RELATIVE_CLUSTER_REPORTS: int = 3


# ---------------------------------------------------------------------------
# Disclosure -- statistical gate (rule 8)
# ---------------------------------------------------------------------------

# statistical threshold = max(STATISTICAL_GATE_FLOOR, ceil(sqrt(n)))
#
# Scales UP with declared population n: a claim about a larger population
# must be backed by more reports. The floor keeps very small scopes from
# clearing the statistical gate on just one or two reports.
STATISTICAL_GATE_FLOOR: int = 5


# ---------------------------------------------------------------------------
# Disclosure -- privacy gate (rule 8)
# ---------------------------------------------------------------------------

# A scope may only be disclosed if its DECLARED population is at least this
# large. Small scopes are where a disclosure can re-identify the person who
# reported. This bound scales DOWN with population -- it only bites on the
# small scopes -- which is the opposite direction to the statistical gate,
# on purpose. Policy choice. Default 20.
MIN_SCOPE_POPULATION: int = 20

# ...and the qualifying report count must not exceed this fraction of the
# declared population. If half of a declared group is "reporting", naming
# the group tells you a lot about specific people in it. Policy choice.
MAX_REPORT_FRACTION: float = 0.5


# ---------------------------------------------------------------------------
# Abuse mitigation (rule 11)
# ---------------------------------------------------------------------------

# Reports are anonymous. We therefore accept that abuse is possible and
# apply only light, anonymous mitigation -- never identity-based controls,
# because identity is exactly what the system exists to protect.
#
# These caps are enforced at INTAKE, which is not part of this repository
# yet. They are named here so the policy lives in one place.
SESSION_SUBMISSION_CAP: int = 3
DAILY_SUBMISSION_CAP: int = 10


# ---------------------------------------------------------------------------
# Configuration objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DetectionConfig:
    """Tunable inputs to the detection engine. Defaults come from the
    module-level policy constants above."""

    detection_window_hours: int = DETECTION_WINDOW_HOURS
    background_rate: float = BACKGROUND_RATE
    absolute_excess_ratio: float = ABSOLUTE_EXCESS_RATIO
    relative_excess_ratio: float = RELATIVE_EXCESS_RATIO
    relative_smoothing: float = RELATIVE_SMOOTHING
    min_relative_cluster_reports: int = MIN_RELATIVE_CLUSTER_REPORTS


@dataclass(frozen=True)
class DisclosureConfig:
    """Tunable inputs to the disclosure engine. Defaults come from the
    module-level policy constants above."""

    statistical_gate_floor: int = STATISTICAL_GATE_FLOOR
    min_scope_population: int = MIN_SCOPE_POPULATION
    max_report_fraction: float = MAX_REPORT_FRACTION


DEFAULT_DETECTION_CONFIG = DetectionConfig()
DEFAULT_DISCLOSURE_CONFIG = DisclosureConfig()
