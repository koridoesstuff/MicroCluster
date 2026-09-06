"""Adversarial self-test for the privacy claim.

Models an observer who sees only what the shipped UI shows -- day by day,
the disclosed scope and its reported report-count band -- and runs two
attacks against that stream:

  * the DIFFERENCING attack (adversarial.differencing): infer the
    overnight change in a named group from consecutive disclosures. Run
    against exact counts (the pre-band behaviour) and against bands; the
    contrast is the result.
  * SCOPE WANDERING (adversarial.wandering): how many distinct groups get
    named across a run, scope stability on versus off.

The point is to make the privacy claim demonstrable. Where a defence only
reduces leakage rather than removing it, that is reported as such.
"""

from .differencing import DifferencingOutcome, attack
from .observer import DayView, observe
from .wandering import WanderingOutcome, measure_wandering

__all__ = [
    "DayView",
    "observe",
    "DifferencingOutcome",
    "attack",
    "WanderingOutcome",
    "measure_wandering",
]
