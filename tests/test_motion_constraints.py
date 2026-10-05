"""CLAUDE.md UI CONSTRAINTS, "Motion" -- the durable version of the ad hoc
grep that used to just ban transition/animation outright.

Motion is now permitted narrowly (state-change and interaction feedback,
capped at 400ms, never looping; one decorative exception). What must still
be impossible -- gradients, shadows, glassmorphism/blur, and anything that
loops -- is checked here instead of by a blanket "no transition" grep, so
this suite has to be updated if the rule changes, not silently bypassed.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"

# still an absolute ban, with or without motion.
_BANNED_RAW = (
    r"linear-gradient",
    r"radial-gradient",
    r"conic-gradient",
    r"box-shadow",
    r"text-shadow",
    r"backdrop-filter",
    r"filter:\s*blur",
    r"\binfinite\b",          # looping animation/animation-iteration-count
)
_BANNED_FONT = r"font-family:[^;]*(Inter|Geist|Space Grotesk)"

_FOCUS_RING_RULE = (
    "a:focus-visible, button:focus-visible, input:focus-visible,\n"
    "select:focus-visible, summary:focus-visible {\n"
    "  outline: 2px solid var(--ink);\n"
    "  outline-offset: 2px;\n"
    "}"
)


class BannedPatternsTest(unittest.TestCase):
    def test_css_has_no_banned_decoration_or_looping_motion(self) -> None:
        css = (WEB / "style.css").read_text(encoding="utf-8")
        for pattern in _BANNED_RAW:
            self.assertIsNone(re.search(pattern, css, re.I), f"found banned pattern: {pattern}")
        self.assertIsNone(re.search(_BANNED_FONT, css, re.I), "banned font-family")

    def test_html_pages_have_no_banned_decoration(self) -> None:
        for name in ("index.html", "privacy.html", "terms.html"):
            html = (WEB / name).read_text(encoding="utf-8")
            for pattern in _BANNED_RAW:
                self.assertIsNone(re.search(pattern, html, re.I), f"{name}: {pattern}")

    def test_no_em_dash_in_ui_copy_or_code(self) -> None:
        for path in list(WEB.glob("*.html")) + list(WEB.glob("*.css")) + list(WEB.glob("*.js")):
            self.assertNotIn("—", path.read_text(encoding="utf-8"), path.name)


class MotionCapTest(unittest.TestCase):
    def test_every_transition_and_animation_duration_is_capped_at_400ms(self) -> None:
        css = (WEB / "style.css").read_text(encoding="utf-8")
        durations = [int(m) for m in re.findall(r"(\d{2,4})ms", css)]
        # sanity check the test itself is looking at the motion section at all
        self.assertGreaterEqual(len(durations), 5, "expected the new motion rules to be present")
        for ms in durations:
            self.assertLessEqual(ms, 400, f"{ms}ms exceeds the 400ms cap")

    def test_reduced_motion_neutralises_every_new_transition_and_animation(self) -> None:
        css = (WEB / "style.css").read_text(encoding="utf-8")
        match = re.search(
            r"@media \(prefers-reduced-motion:\s*reduce\)\s*\{(.*?)\n\}", css, re.S
        )
        self.assertIsNotNone(match, "no prefers-reduced-motion: reduce block found")
        block = match.group(1)
        self.assertIn("transition: none", block)
        self.assertIn("animation: none", block)
        # the pulse ring and the flashed gate row must be fully suppressed,
        # not just left with an un-eased snap
        self.assertIn(".agent.pulse::before", block)
        self.assertIn("tr.verdict-changed", block)


class FocusRingUntouchedTest(unittest.TestCase):
    def test_focus_visible_ring_is_byte_identical(self) -> None:
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertIn(_FOCUS_RING_RULE, css, "the focus-visible ring rule was changed")


if __name__ == "__main__":
    unittest.main()
