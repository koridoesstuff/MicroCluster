"""The differencing attack.

The observer takes two consecutive days that disclose the SAME scope and
asks how many individuals' reports changed overnight. The disclosed
per-scope qualifying count is a running total over the 72h detection
window, so the overnight change is::

    delta = count(day d+1) - count(day d)

With EXACT counts the observer learns ``delta`` as a single integer; when
``abs(delta) == 1`` that is one identifiable person's report appearing or
ageing out of the window overnight -- a pinned one-person change.

With BANDS the observer knows only ``[lo, hi]`` for each day, so ``delta``
is an interval ``[lo(d+1) - hi(d), hi(d+1) - lo(d)]`` -- normally many
integers wide, and never a pinned single person.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from api.bands import band_interval

from .observer import DayView

_NEG_INF = float("-inf")
_POS_INF = float("inf")


@dataclass(frozen=True)
class _Pair:
    scope_label: str
    day_from: int
    delta_low: float
    delta_high: float

    @property
    def known_exactly(self) -> bool:
        return self.delta_low == self.delta_high

    @property
    def unbounded(self) -> bool:
        return self.delta_low == _NEG_INF or self.delta_high == _POS_INF

    @property
    def possible_values(self) -> float:
        return _POS_INF if self.unbounded else self.delta_high - self.delta_low + 1

    @property
    def one_person_pinned(self) -> bool:
        return self.known_exactly and abs(self.delta_low) == 1

    @property
    def direction_known(self) -> bool:
        return not self.unbounded and not (self.delta_low <= 0 <= self.delta_high)


@dataclass(frozen=True)
class DifferencingOutcome:
    mode: str
    same_scope_pairs: int
    pinned_exactly: int
    one_person_pinned: int
    direction_known: int
    unbounded_pairs: int
    median_possible_values: float
    residual: str


def _delta_bounds(a: DayView, b: DayView) -> tuple[float, float]:
    if a.exact_count is not None and b.exact_count is not None:
        d = float(b.exact_count - a.exact_count)
        return d, d
    lo_a, hi_a = band_interval(a.band)
    lo_b, hi_b = band_interval(b.band)
    low = _NEG_INF if hi_a is None else float(lo_b - hi_a)
    high = _POS_INF if hi_b is None else float(hi_b - lo_a)
    return low, high


def _pairs(views: list[DayView]) -> list[_Pair]:
    out: list[_Pair] = []
    for a, b in zip(views, views[1:]):
        if a.scope_id is None or a.scope_id != b.scope_id:
            continue
        low, high = _delta_bounds(a, b)
        out.append(_Pair(a.scope_label, a.day, low, high))
    return out


def _residual(mode: str, pairs: list[_Pair]) -> str:
    if not pairs:
        return "no scope was disclosed on two consecutive days"
    if mode == "exact":
        return "overnight change in the named group is known to the exact person"
    return (
        "the named group is still named; its count stays bracketed to a band; "
        "the overnight change stays a wide interval"
    )


def attack(views: list[DayView], *, mode: str) -> DifferencingOutcome:
    """Run the differencing attack over one observed run.

    ``mode`` is ``"exact"`` or ``"band"`` and only labels the result --
    which one actually applies is decided by whichever field
    :func:`adversarial.observer.observe` populated.
    """
    pairs = _pairs(views)
    finite = [p.possible_values for p in pairs if not p.unbounded]
    return DifferencingOutcome(
        mode=mode,
        same_scope_pairs=len(pairs),
        pinned_exactly=sum(1 for p in pairs if p.known_exactly),
        one_person_pinned=sum(1 for p in pairs if p.one_person_pinned),
        direction_known=sum(1 for p in pairs if p.direction_known),
        unbounded_pairs=sum(1 for p in pairs if p.unbounded),
        median_possible_values=median(finite) if finite else _POS_INF,
        residual=_residual(mode, pairs),
    )
