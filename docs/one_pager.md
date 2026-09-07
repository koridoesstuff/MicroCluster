# MicroCluster

**A privacy-preserving health-signal system for small shared communities —
with a simulator that measures what the privacy costs.**

> It detects the signal without exposing the person who created it.

---

**The problem.** A small cluster of the same illness on a dorm or office
floor is worth catching early — but surfacing it means someone reports
being sick and says where they are, and a system that collects that can
leak it. The useful signal and the privacy risk are the same data.

**What it does.** People submit anonymous reports from a fixed checklist:
one of four symptom categories, a coarse onset bucket, one location group.
No name, no free text, no exact time, no room. Two detectors watch the
stream — one comparing a location to its neighbours, one comparing total
activity to a background rate. When one fires, a disclosure engine decides
what may be said, and at what scope.

**The mechanism — two gates, pulling opposite ways.** A scope is named
only if it clears both, evaluated separately, never merged into one score:

- **Statistical gate:** `qualifying ≥ max(5, ceil(√n))` for declared
  population `n`. Scales *up* with `n` — a bigger claim needs more
  evidence (9 reports for a 75-person floor, 13 for a 150-person
  building).
- **Privacy gate:** `n ≥ 20` and `qualifying / n ≤ 0.5`. Scales *down*
  with `n` — a small, near-fully-covered group is the identifying one, and
  naming it publishes a roster.

The system discloses the **finest scope that clears both**; if none does,
it says nothing. Accounts or precise location would make clusters easier
to pin down and rebuild exactly the dataset the system exists to avoid, so
it chooses data minimisation over control. Report counts render as bands
("5–9", "10–19"), never exact integers, which closes a day-to-day
differencing attack.

---

### Results — 500-seed sweep, 300-seed benchmark, 200-seed self-test

**The delay the policy buys** (detection fixed, disclosure gate tightened):

| Gate setting | First disclosure | Infected by then | Finest scope |
|---|---|---|---|
| shipped | day 14.1 | ~35 | one suite |
| tightest tested | day 18.6 | ~82 | floor only |

The detector fires on day ~8 either way. The gap between knowing and being
allowed to say where is **about 6 days** — the price of the policy, in
people. (It also false-alarms on 60% of outbreaks that never establish — a
real weakness, stated in the UI.)

**Authored rules vs a learned model** (held out by simulation run):

| Detector | Precision | Recall | Mean delay |
|---|---|---|---|
| authored threshold rules | 0.95 | 0.78 | 3.7 days |
| logistic-regression model | 0.93 | 0.82 | 2.8 days |

The model is ~1 day faster for ~3 points of precision; the small edge
survives a change in transmission probability. **The rules ship; the model
is kept only as this benchmark.**

**Attacking our own output.** Over 1,171 consecutive same-scope
disclosures, an observer differencing the numbers pins an exact
one-person overnight change on **358 days against exact counts, and 0
against the bands the UI ships** (direction of change still leaks on 204
pairs — reported, not hidden).

---

**Limitations.** Every transmission rate, reporting rate, contact rate and
incubation time is chosen for demonstration, not measured; there is no
real dataset behind the simulator. It predicts nothing about any real
building and diagnoses or treats no one — the claim is understanding, not
intervention. Agent-based epidemic modelling and small-cell suppression
are both mature prior art; the contribution is wiring the suppression
policy onto a live detector and measuring the trade-off.

**Tech.** Python, FastAPI + Uvicorn; engines and simulator run server-side
only. Plain HTML/CSS/vanilla JS with a hand-drawn SVG chart — no
framework, no build step, no CDN. scikit-learn is used only for the
offline benchmark. 209 tests, all green.

**Links.** Repository <https://github.com/koridoesstuff/MicroCluster> ·
Live demo <https://microcluster.onrender.com> · Video `<VIDEO URL>`
