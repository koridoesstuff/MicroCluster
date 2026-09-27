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
simulator generates the reports and measures the policy.

**The mechanism: two gates, pulling opposite ways.** A scope is named only
if it clears both gates, evaluated separately, never merged into one
score:

- **Evidence gate:** the bigger the group, the more reports it takes to
  name it, and never fewer than 5 (reports >= max(5, ceil(sqrt(n))) for a
  group of n people).
- **Privacy gate:** never name a group under 20 people, or one where more
  than half the members have reported, because that is a list of who is ill
  (n >= 20 and reports / n <= 0.5): a k-anonymity-style floor plus a
  reporting-share cap, not differential privacy.

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
stays a benchmark. Differencing the banded output pins a one-person overnight
change on 0 days (358 for exact counts); its direction still leaks on 204 of
1,171 same-scope day-pairs.

---

**Limitations — read this.** Every transmission, reporting, contact and
incubation value is chosen for demonstration, not measured; there is no
real dataset. Tested at 150 to 2,000 simulated people (the gates held, but
outbreaks saturate one building) and against a harsher correlated reporting
model, where timing barely moves but false alarms rise from 60% to about
90%. It predicts nothing about a real building and treats no one; the claim
is understanding, not intervention. It rate-limits submissions per session
but does not authenticate reporters, so a determined attacker using multiple
sessions can still inject signal.

Epidemic simulation and small-cell suppression are mature prior art; the
contribution is wiring suppression onto a live detector and measuring the
trade-off it forces.

The ten hardest questions a skeptical judge could ask, with honest
answers, are in [`anticipated_questions.md`](anticipated_questions.md); the
exact privacy property is in [`privacy_guarantee.md`](privacy_guarantee.md).

**Tech.** Python, FastAPI + Uvicorn; detection and disclosure run
server-side only. Plain HTML/CSS/JS, no framework or build step. scikit-learn is used only
for the offline benchmark. 237 tests, all green.

**Links.** Repository <https://github.com/koridoesstuff/MicroCluster> ·
Live demo <https://microcluster.onrender.com> · Video `<VIDEO URL>`
