# MicroCluster

**A privacy-preserving community health-signal system, with a simulator
that measures what the privacy costs.**

> It detects the signal without identifying the reporter, and won't name a
> group too small or too covered to name safely.

*(This file and `one_pager.html` carry the same prose; the HTML is the
print source for `one_pager.pdf`. Keep them in sync.)*

---

**The problem.** A cluster of the same illness on a dorm or office floor
is worth catching early, but surfacing it means someone reports being sick
and says where they are. The useful signal and the privacy risk are the
same data.

**What it does.** People submit anonymous reports from a fixed checklist:
one of four symptom categories, a coarse onset, one location group. No
name, no free text, no room. Two detectors watch the stream, one relative
to a location's neighbours, one against a background rate; when one fires,
a disclosure engine decides what may be said and at what scope. A headless
agent-based simulator generates the reports and measures the policy.

**The mechanism: two gates, pulling opposite ways.** A scope is named only
if it clears both gates, evaluated separately, never merged into one
score:

- **Statistical gate:** qualifying reports >= max(5, ceil(sqrt(n))) for
  declared population n. Scales *up* with n: a bigger claim needs more
  evidence.
- **Privacy gate:** n >= 20, and qualifying / n <= 0.5. Scales *down* with
  n: a small, near-fully-covered group is the identifying one, and naming
  it publishes a roster.

The system discloses the finest scope clearing both; if none does, it says
nothing. Report counts render as bands ("5-9", "10-19"), never exact
integers.

---

### Results — 500-seed sweep, 300-seed benchmark, 200-seed self-test

**The delay the policy buys** (detection fixed, disclosure gate tightened;
the detector fires around day 8 in both rows):

| Disclosure gate | First disclosure | Infected by then | Finest scope |
|---|---|---|---|
| shipped | day 14 | ~35 | one suite |
| tightest tested | day 19 | ~82 | floor only |

**Authored rules vs a learned model** (held out by run):

| Detector | Precision | Recall | Mean delay |
|---|---|---|---|
| authored threshold rules | 0.95 | 0.78 | 3.7 days |
| logistic-regression model | 0.93 | 0.82 | 2.8 days |

The detector fires around day 8; disclosure is not permitted until about
day 14, and that six-day gap, roughly 35 people infected, is the
measurable cost of the policy. The learned model is about a day faster for
about three points of precision, so the authored rules ship and the model
stays a benchmark. Differencing the banded output pins an exact one-person
overnight change on 0 days, against 358 for exact counts; the direction of
change still leaks on 204 of 1,171 same-scope day-pairs, reported not
hidden.

---

**Limitations — read this.** Every transmission, reporting, contact and
incubation value is chosen for demonstration, not measured; there is no
real dataset, and the system is validated only at one population size
(150). The detector is exercised only against a clean, memoryless
reporting model, and fires on roughly 60% of outbreaks that never
establish. It predicts nothing about a real building and treats no one;
the claim is understanding, not intervention. It rate-limits submissions
per session but does not authenticate reporters, so a determined attacker
using multiple sessions can still inject signal; anonymity is chosen over
abuse-resistance by design.

Agent-based epidemic modelling and small-cell suppression are both mature
prior art. The contribution is wiring the suppression policy directly onto
a live anomaly detector as one server-side pipeline, and measuring the
trade-off it forces.

The ten hardest questions a skeptical judge could ask, with honest
answers, are in [`anticipated_questions.md`](anticipated_questions.md).

**Tech.** Python, FastAPI + Uvicorn; detection and disclosure run
server-side only. Plain HTML/CSS/vanilla JS with a hand-drawn SVG chart,
no framework, no build step. scikit-learn is used only for the offline
benchmark. 223 tests, all green; contrast-checked, keyboard-navigable.

**Links.** Repository <https://github.com/koridoesstuff/MicroCluster> ·
Live demo <https://microcluster.onrender.com> · Video `<VIDEO URL>`
