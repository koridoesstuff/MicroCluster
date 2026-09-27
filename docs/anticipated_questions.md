# Anticipated questions — a hostile read of MicroCluster

Ten questions a skeptical, technically competent judge could ask, and the
honest answers. Where the answer is "that is a real limitation," it says
so. A ranking of the weakest points is at the bottom.

---

## 1. The ML benchmark is circular. A classifier trained on data from your own assumptions will do well on data from the same assumptions. What does it actually tell anyone?

You are right that it says nothing about epidemiology. Its scope is
narrower: given this simulator's ground truth, does a fitted model recover
the outbreak signal better than the hand-written threshold rules? Three
things keep it honest.

1. The train/test split is by simulation **run**, never by day. Adjacent
   days from one outbreak are correlated; letting them straddle the split
   would leak the test set into training and flatter the model.
2. There is a cross-regime test. The model trains at one
   `SUITE_TRANSMISSION_PROBABILITY` (0.008) and is scored on runs
   generated at 0.005 and 0.012. Its small edge (roughly +0.03 to +0.08
   recall, about 1 day faster) survives that shift — weak evidence it
   learned something transferable rather than pure memorisation. It is still a model of this
   simulator, and the write-up says so in those words.
3. The model never ships. It exists only as this comparison. In
   distribution it is marginally faster and pays for it with lower
   precision on a detector that already over-alarms, so there is no case
   for shipping it.

**Verdict: adequately handled.** The circularity is real, named, and the
design refuses to let the model's flattering in-distribution numbers
become a product decision.

---

## 2. None of the parameters are measured. Why believe any number that comes out the other end?

You should not believe the magnitudes. `simulation/config.py` says this at
the top, in the same words as the on-page banner: every transmission
probability, reporting rate, contact rate and state duration was set by
hand, checked by running the model, and kept at the value that produced a
believable partial outbreak on 150 people in 30 days.

What the project asks you to believe is not "disclosure happens on day
14," but the **shape** of two relationships that are structural, not
parametric:

- Tightening the disclosure gate monotonically pushes first disclosure
  later and lets more people be infected first (the delay curve).
- Banding the output removes the one-person differencing pin while leaving
  a measurable direction-of-change residual.

Those hold because of how the gates and the banding are defined, not
because 0.008 is the right transmission rate. Change every parameter and
the curve moves; its slope stays positive.

**Verdict: the honest answer is "you can't believe the numbers, only the
direction of the trade-offs."** That is a genuine limit on what the
project demonstrates, and it is stated prominently rather than buried.

---

## 3. Are the privacy gates principled, or tuned until the demo looked good?

The **shapes** are principled and now have an exact name; the **shipped
values** are defaults, not optima. The full mapping is in
`docs/privacy_guarantee.md` and on the privacy page.

What the two gates jointly guarantee, on every named group, by construction:
at least 20 people (a **k-anonymity-style group-size floor**, k >= 20), at
least `max(5, ceil(sqrt(n)))` supporting reports (a **minimum-support
threshold rule**), and at most half the group among the reporters (a
**prevalence cap** that bounds the homogeneity attack, in the spirit of
l-diversity and the dominance rule but not literally either). That invariant
held on about 543,000 independently re-checked evaluations up to 2,000 agents.

What they are **not**: differential privacy. They add no noise and use hard
thresholds on exact counts, so one report can flip "nothing" to "names S"
and the output change from one person is unbounded (epsilon is infinite);
there is no privacy budget, so daily releases over overlapping data do not
compose accountably; and there is no protection against an adversary who
knows almost all the reports (the threshold boundary itself leaks a bit).

The constants (5, 20, 0.5, `sqrt(n)`) are round policies for a 25 / 75 / 150
structure; the sweep shows their cost rather than deriving them. Neither the
sweep nor the benchmark feeds back into them.

**Verdict: partial, and now precisely bounded.** The property is real,
deterministic and named, and the write-up says exactly what it does not
promise. A judge who wants the constants derived from a risk model, or a
formal epsilon, still will not get either.

---

## 4. Everything is tested at 150 people and three scope levels. What happens at a real building — 500 residents, a 2,000-person campus with hundreds of suites?

It is now tested at 500, 1,000 and 2,000 agents with four distinct scope
populations (campus / building / floor / suite), 500 seeds each
(`docs/stress_tests.md`, `results/scale.json`). No detection or disclosure
code changed. **Nothing fails**: zero crashes, zero violations of the evidence
formula on about 543,000 evaluations, no scope named without passing both
gates, runtime linear (0.1 s per run at 2,000; about 0.5 s at 10,000).

What that showed, including the parts that do not look good:

- **The outbreak model hits a ceiling, not the engine.** Every multi-building
  run stays inside one building (no campus-level contact exists) and then
  saturates it (92 to 98% attack rate), because the per-contact building
  probability does not dilute as buildings grow. The scale results describe
  "one large building on fire", not a campus.
- **Policy cost shrinks in days and grows in people.** The fire-to-disclosure
  gap falls from 6.0 to about 1.7 days, but infections before disclosure rise
  from 35 (150 agents) to 118 (2,000).
- **The privacy gate binds much more**: 95% of runs at 1,000 and 2,000 hit a
  roster refusal, almost all at suite level, so disclosure repeatedly retreats
  a level.
- **False alarms rise to 84 to 86%** (small denominators, about 22 to 25 runs).
- **A campus-wide disclosure never wins at scale**: its threshold (32 to 45)
  exceeds the building's and the outbreak sits in one building.
- Still untested: hundreds of suites per floor, suites of other sizes, more
  than one seeded outbreak, and any real contact structure.

**Verdict: restated, no longer "unknown".** The machinery scales to at least
2,000 agents; what does not scale credibly is the simulated epidemic, and the
false-alarm rate gets worse. Nothing past a single synthetic building
structure is validated.

---

## 5. Strip the framing and this is small-cell suppression with extra steps. What is actually new?

Correct that the disclosure engine **is** small-cell suppression — the
README's prior-art section says exactly that and cites the family (cell
suppression, minimum-cell-size rules, k-anonymity, differential privacy as
the modern formal treatment). Two things are combined rather than
invented:

1. The suppression policy is wired directly onto the output of an anomaly
   detector as one server-side pipeline, with a fixed order (detection ->
   disclosure -> presentation) — not a statistician manually suppressing
   cells in a published table after the fact.
2. The project measures the cost of the suppression in the units that
   matter: extra infections per day of privacy-mandated delay, and what an
   observer can reconstruct from the banded stream over time. Small-cell
   suppression literature is about static tabular releases; this is a
   live, sequential disclosure where the **sequence** leaks more than any
   single release, and the residual is quantified.

**Verdict: honest.** "An integration plus a measurement" is a fair
description and it is the one the project already gives. A judge who only
rewards novel mechanisms will not be moved; one who values honest
engineering and a real trade-off measurement will be.

---

## 6. Your detector consumes a `reporting_probability`. Real people do not report like that. Would it work at all on real reporting behavior?

Now stress-tested against a deliberately harsher process
(`SimulationConfig(reporting_model="realistic")`, default unchanged):
heterogeneous baselines (Beta(0.5, 0.5), same mean, U-shaped), correlated
reporting (probability rises after suite-mates report, worried-well filers
included) and stigma (probability halves in a named group). Same outbreaks,
paired, 500 runs (`docs/stress_tests.md`).

| | clean | realistic |
|---|---|---|
| first disclosure (day) | 14.1 | 14.2 |
| infected before disclosure | 35.2 | 35.8 |
| false-alarm rate | 60% | 90% |
| false disclosures (fizzles that still named a scope) | 0% | 3% |
| disclosure continuity | 74% | 59% |

The timing looks robust. **It is not; it is cancellation.** Heterogeneity
alone makes disclosure later (14.9 days, 40.9 infected) and correlation alone
earlier (12.4, 27.1). Across a 4 x 4 strength grid infections before
disclosure range 24 to 44 (minus 31% to plus 24%). The direction depends on
which unmeasured effect dominates.

The false-alarm rate **does** depend on the clean assumption: 60% clean, 78
to 100% once any correlation is present, and at high correlation about a
quarter of outbreaks that never took off produce a false named disclosure.
Stigma never changes first disclosure but erodes sustained disclosure (74% to
57%), which the timing columns cannot show.

**Verdict: the limitation survived testing and is restated.** Timing degrades
gracefully; low-false-alarm behaviour depends on memoryless reporting, and a
plausible correlated process makes it worse and can produce false
disclosures. Both processes are still simulated with chosen constants; the
detector has never seen a real report.

---

## 7. You still leak the direction of change on 204 of 1,171 day-pairs. Concretely, what does that let a determined attacker learn about a specific real person?

For those 204 overnight transitions, an observer watching only the page
learns that the named group's within-window qualifying count moved up or
moved down — not by how much (the band is 5 or 10 wide) and not whose
report caused it.

Stack that with everything else the page shows: the **group** is named
(say, "Floor 2"), the count is bracketed to a band, and the disclosed
scope is fairly stable (with scope stability on, a run names about 1.6
distinct groups total, versus 3.1 with it off). Now suppose the attacker
independently knows their target lives on that floor and has an
out-of-band signal — saw the target looking unwell, knows the target was
absent. A direction-known day-pair is then weak Bayesian corroboration:
"consistent with my target having filed a report that night." It is never
confirmation, never "my target and nobody else," never a room or a name —
those were never collected.

Not safe against: an attacker who already has strong side information
about a small named group and wants their prior nudged. Safe against:
reconstructing the report stream, or pinning a single person's state
change from the page alone. The exact-count version of the page would give
the last two away; the banded version does not.

**Verdict: adequately answered, but only if stated this precisely.** The
residual is real and is not nothing — it is "weak corroboration for an
attacker who already knows a lot." The one-pager and the on-page copy both
now lead with the residual rather than an unqualified zero.

---

## 8. Your detector fires on ~60% of outbreaks that never establish. A system that cries wolf on more than half the hard cases is not a useful detector.

That number is over the ~31% of runs that fizzle — a single index case
that infects a few people and dies out on its own. In the first few days a
fizzle and a real takeoff produce an **identical** early spike; you cannot
tell them apart without hindsight, and any detector tuned to catch real
outbreaks early will also fire on the fizzles that looked the same on day
3. We report it (`false_alarm_rate` in the sweep, and on the page) rather
than hide it, because tuning the detector to fire only once establishment
is certain defeats the point of **early** detection.

Two things limit the damage: a detector fire is not a disclosure (the two
gates sit between them, and most false fires never clear the statistical
gate at any nameable scope), and the hysteresis rule releases "fired" as
soon as the window's qualifying count drops to its floor, so a fizzle's
false alarm is short-lived.

**Verdict: partial.** The honest framing — "early detection of a thing
that has not happened yet is inherently near-chance on the ambiguous
cases, and the disclosure gates are the backstop" — is defensible, but 60%
is a genuinely bad headline number and a judge is right to press on it.

---

## 9. The thesis is "it detects the signal without exposing the person who created it." But a disclosure names a group, and in a 25-person suite where a dozen people reported, "someone on your suite is sick" is a lot of exposure.

"The person who created it" means the individual reporter, whose name,
room, exact time and free-text description never exist in the system —
there is nothing to expose at the individual level because it was never
collected.

Group-level exposure is real and is exactly what the privacy gate bounds.
The roster refusal in the demo is the system declining to name a 25-person
suite precisely because a dozen reports out of 25 makes "this suite" close
to "these people." When the suite fails that gate, disclosure retreats to
the floor (75 people), where the same dozen reports are a much weaker
statement about any individual. So the claim is defensible as written, but
the honest loss is that a **group** health signal is still surfaced, and a
small enough named group is still a meaningful disclosure about the people
in it — the system trades that down to the coarsest safe scope, it does
not eliminate it.

On zero users: the project is a simulator by design (a deployed reporting
tool with no users would have to explain why nobody uses it; a simulator
does not), and the impact claim is "understanding, not intervention" —
nobody is diagnosed, treated or protected, and the docs say so.

**Verdict: mostly honest, and the phrasing is now fixed.** The old
tagline ("without exposing the person who created it") slightly overstated
what happens to a small named group. It now reads: "it detects the signal
without identifying the reporter, and won't name a group too small or too
covered to name safely" — the affirmative claim about the individual, and
the explicit bound on the group, in one line.

---

## 10. Reports are anonymous with no identity check. What stops someone injecting a fake cluster — or manufacturing a disclosure about a group they want stigmatised?

The per-session submission cap is now enforced — `microcluster.intake`,
wired into `engine.analyze` as its first step, server side, so it holds
regardless of client. A report carries an opaque, ephemeral `session_id`;
that is the only thing the cap keys on. `adversarial.injection` measures
exactly what it buys, and the answer is: **it raises the attacker's
session count, and nothing else.**

Concretely, against the representative target — a floor, declared
population 75:

- To manufacture a floor-level false disclosure an attacker needs **9**
  fabricated reports. That number is set by the statistical gate
  (`ceil(sqrt(75)) = 9`); the cap does not change it.
- **Without the cap**, or with unlimited sessions: 9 reports from **1
  source**, and the floor is falsely disclosed.
- **With the cap, attacker limited to one session:** 6 of the 9 are
  rejected, 3 get through, the statistical gate is not cleared, and
  **nothing is disclosed**. A naive single-session flood is stopped.
- **With the cap, attacker rotates sessions:** `ceil(9 / 3) = 3`
  session_ids, 3 reports each, 0 rejected, floor falsely disclosed. The
  attack succeeds again.

A `session_id` is a client-chosen, unauthenticated string. Generating
three of them (or three hundred) costs the attacker essentially nothing,
so the cap converts "9 reports from one source" into "9 reports across
three sources" and stops there. The attacker still controls the category
label, and the privacy gate's roster refusal only pushes a suite-level
false claim up to the floor — a floor-level false disclosure is still
harmful. There is still no anomaly-of-anomalies check and no
cross-referencing against independent signals.

What would actually close this is identity or session binding (a
verified account, a device attestation, a server-issued session an
attacker cannot mint at will) — exactly the class of control the system
refuses on principle, because identity is the thing it exists to protect.

**Verdict: partially mitigated, still open — not solid.** The cap is real
now and it does stop a lazy single-session attacker, which is worth
having. It does not prevent report injection by anyone willing to rotate
sessions, and it cannot without adding identity. The privacy policy and
the one-pager both now say the system rate-limits but does not
authenticate reporters.

---

## Where this project is weakest

In rough order of how much they would hurt:

1. **Abuse (Q10).** The per-session cap is now enforced and stops a
   single-session flood, but an attacker who rotates unauthenticated
   session_ids still injects a false cluster or targeted false disclosure
   at the same report cost. Closing it needs identity binding, which the
   design refuses.
2. **Reporting realism (Q6).** Tested against a harsher simulated process:
   timing survives only by cancellation, false alarms rise from 60% to 78 to
   100% under correlation, and false disclosures appear. Never tested on real
   reports.
3. **Scale (Q4).** The machinery holds to 2,000 agents (and 10,000 for
   runtime), but the simulated epidemic saturates one building and the
   false-alarm rate reaches 84 to 86%. Nothing real is validated.
4. **60% false-alarm rate (Q8).** Honestly disclosed, defensible in
   principle, still a bad number, and worse at scale and under correlation.
5. **No formal privacy guarantee (Q3).** The property is now named exactly
   (k-anonymity-style floor, threshold rule, prevalence cap) and is
   explicitly not differential privacy: no noise, unbounded epsilon, no
   composition accounting.

Q9's loose thesis phrasing has been fixed (the tagline now states the
individual claim and the group bound separately).

The stronger ground: the ML benchmark's circularity is handled honestly
and the model never ships (Q1); the prior art is credited rather than
obscured (Q5); the differencing-attack residual is measured and reported,
not waved away (Q7); and the unmeasured-parameter problem is stated as a
hard limit on what the project claims, not hidden (Q2).
