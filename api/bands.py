"""Report-count banding for the API's presentation boundary.

PRIVACY REQUIREMENT, not a styling choice. A ``ScopeEvaluation`` carries
the exact qualifying-report count for a scope. If that exact integer is
visible in the UI on two consecutive days that both name the same scope,
an observer subtracts the two and learns that exactly one identifiable
person became ill (or recovered) overnight -- a differencing attack that
would be live in the shipped product.

So the exact count never leaves the server. Every count the API emits is
first mapped to a BAND. The band edges below are a privacy policy, named
here the same way every threshold in ``microcluster/config.py`` is:
wider bands are safer and coarser; these are a chosen starting point, not
a proven-safe value.

The same rule reaches the human-readable ``disclosure_reason`` strings,
which sometimes embed a raw count ("7 qualifying reports < required 45"):
:func:`sanitize_reason` rewrites those to the band before the string is
sent.
"""

from __future__ import annotations

import re

# Lower bound of each band. A count of N lands in the band [lo, next_lo - 1]
# for the largest lo <= N; at or above the last edge it is "<edge>+".
# Chosen so the smallest bands ("1-4", "5-9", "10-19") are narrow enough
# to stay informative and wide enough that a one-person night-to-night
# change cannot be read off two consecutive disclosures.
BAND_LOWER_BOUNDS: tuple[int, ...] = (1, 5, 10, 20, 50, 100)


def band(count: int) -> str:
    """Map an exact count to its band label ("0", "1-4", ..., "100+")."""
    if count <= 0:
        return "0"
    edges = BAND_LOWER_BOUNDS
    if count >= edges[-1]:
        return f"{edges[-1]}+"
    for lo, hi in zip(edges, edges[1:]):
        if lo <= count < hi:
            return f"{lo}-{hi - 1}" if hi - 1 > lo else f"{lo}"
    # count in [1, edges[0]) is impossible while edges[0] == 1, but stay safe.
    return f"1-{edges[0] - 1}"


def band_interval(label: str) -> tuple[int, int | None]:
    """Inverse of :func:`band`: the inclusive ``[lo, hi]`` a label stands
    for. ``hi`` is ``None`` for the open-topped ``"<n>+"`` band."""
    if label == "0":
        return (0, 0)
    if label.endswith("+"):
        return (int(label[:-1]), None)
    lo, hi = label.split("-")
    return (int(lo), int(hi))


_QUALIFYING_PAREN = re.compile(r"\((\d+) qualifying reports")
_QUALIFYING_COUNT = re.compile(r"qualifying count \((\d+)\)")
_SCOPES_COUNT = re.compile(r"scope's \((\d+)\)")
_FRACTION = re.compile(r"report fraction \d+(?:\.\d+)? exceeds maximum (\d+(?:\.\d+)?)")


def sanitize_reason(reason: str) -> str:
    """Rewrite every raw report count inside a ``disclosure_reason`` to its
    band, and blur the exact report fraction. Population, statistical
    thresholds and the switch margin are public policy numbers and are
    left untouched.

    Targets the exact phrasings ``microcluster.disclosure`` produces; a
    reason with no embedded count passes through unchanged.
    """
    out = _QUALIFYING_PAREN.sub(
        lambda m: f"({band(int(m.group(1)))} qualifying reports", reason
    )
    out = _QUALIFYING_COUNT.sub(
        lambda m: f"qualifying count ({band(int(m.group(1)))})", out
    )
    out = _SCOPES_COUNT.sub(lambda m: f"scope's ({band(int(m.group(1)))})", out)
    out = _FRACTION.sub(
        r"report fraction over the limit of \1", out
    )
    return out
