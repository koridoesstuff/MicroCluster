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

The **shapes** are principled; the **shipped values** are defaults, not
optima.

`qualifying >= max(5, ceil(sqrt(n)))` encodes "evidence should scale with
the size of the claim." `sqrt(n)` is a reasonable growth rate for that,
not a theorem, and `config.py` says so. `n >= 20` and
`qualifying / n <= 0.5` encode "do not name a group small enough or
covered enough that naming it is naming its members." The specific
constants (5, 20, 0.5) are round numbers chosen to land in sensible
regimes for a 25 / 75 / 150 structure.

Instead of claiming they are optimal, the project makes their cost
visible: the disclosure-gate sweep runs 500 outbreaks at each of several
settings and reports how much later disclosure happens and how many more
infections result. A deployer picks the point on that curve they can
defend. The sweep and the ML benchmark are separate and neither feeds back
into the constants, so the gates were not tuned against "how good the demo
looks."

**Verdict: partial.** "It is a policy, and here is its cost curve" is a
fair answer, but a judge who wants the shipped values *derived* from a
stated risk model will not get that. There is no formal privacy guarantee
(no epsilon), only a suppression rule and its measured price.

---

## 4. Everything is tested at 150 people and three scope levels. What happens at a real building — 500 residents, a 2,000-person campus with hundreds of suites?

We do not know, and nothing in the repo validates it past 150. The default
structure is one campus / one building / two floors / three suites / 25
agents, and every result runs on it.

Several things are untested at scale and could break:

- The relative detector compares a location to its **contemporaneous
  peers**. With three suites the peer pool is two. At hundreds of suites
  the pooled control rate behaves very differently, and the
  `RELATIVE_SMOOTHING` constant that keeps the ratio finite was tuned for
  the small case.
- `sqrt(n)` at campus n = 2,000 demands 45 reports before a campus-level
  claim, which may be too slow to be useful.
- Scope stability and wandering were measured over a handful of scopes.
  Over hundreds, "how many distinct groups a run names" could be much
  worse.
- The degenerate case the sweep already flags (`MIN_SCOPE_POPULATION` =
  200 against a 150-person campus makes every disclosure structurally
  impossible) is a small taste of the configuration cliffs that appear
  when the structure and the constants are not co-designed.

**Verdict: real limitation.** The approach is defined for arbitrary
hierarchies but demonstrated only at toy scale. The on-page limitations
statement now says so.

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

The detector consumes report **counts** and is agnostic to how they are
generated, but every performance number assumes the simulator's reporting
model, and that model is deliberately simple: each agent gets a fixed
personal reporting probability drawn once from [0.3, 0.7], applied
independently each symptomatic day, no memory, no feedback.

Real reporting is none of those things. It is correlated (people report
once they hear others are sick — which would help detection but also
creates a feedback loop the simulator lacks), biased (the worried-well
flood in during a scare; genuinely sick people under-report when they feel
worst), bursty and day-of-week patterned, and directly manipulable. The
background-noise term is a flat trickle where real baseline reporting has
structure.

So: the detector's **logic** (relative excess vs peers, absolute excess vs
a baseline, inside a rolling window) is not tied to the clean model, but
its measured precision, recall and delay are, and real reporting could
degrade all three — or, through reporting cascades, flatter the recall
while making false alarms worse.

**Verdict: real limitation.** The detector has never seen a realistic
reporting process. The limitations statement now says it is exercised only
against a clean, memoryless model.

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

**Verdict: mostly honest.** The thesis sentence is true for the individual
and the privacy gate genuinely bounds the group case, but "without
exposing" slightly overstates what happens to a small named group.
"Without exposing the individual, and bounding the group" would be the
fully precise claim.

---

## 10. Reports are anonymous with no identity check. What stops someone injecting a fake cluster — or manufacturing a disclosure about a group they want stigmatised?

Nothing, today. This is the deliberate and accepted cost of anonymity, and
it is currently **unmitigated in code**. The design rejects identity-based
controls (accounts, device binding, verification) on principle, because
identity is the thing the system exists to protect. The only mitigations
named — `SESSION_SUBMISSION_CAP` and `DAILY_SUBMISSION_CAP` — are weak
(rate limits an attacker spreads across sessions or days), and they are
enforced at intake, which is not built in this repo.

So a determined actor can submit a dozen "gastrointestinal" reports tagged
to a rival's suite and, if the counts clear the statistical gate, the
system announces a GI cluster at that scope. The privacy gate's roster
refusal partly limits this — it pushes a suite-level false claim up to the
floor — but a floor-level false disclosure is still harmful, and the
attacker controls the category label. There is no anomaly-of-anomalies
check, no cross-referencing against independent signals, nothing.

**Verdict: real limitation, and the sharpest one.** Manufactured-signal
and manufactured-disclosure attacks are possible now, the mitigations are
both weak and unimplemented, and the trade-off (abuse-resistance
sacrificed for anonymity) is a design choice a judge may simply disagree
with. The limitations statement now names this explicitly.

---

## Where this project is weakest

In rough order of how much they would hurt:

1. **Abuse (Q10).** A false cluster or a targeted false disclosure can be
   injected right now; the mitigation is weak in design and absent in
   code.
2. **No realistic reporting model (Q6).** Every performance number
   assumes a clean, memoryless reporting process the detector has never
   been tested without.
3. **Unvalidated at scale (Q4).** Nothing is tested past 150 people and
   three scope levels; several components have scale-sensitive
   assumptions.
4. **60% false-alarm rate (Q8).** Honestly disclosed, defensible in
   principle, still a bad number.
5. **No formal privacy guarantee (Q3).** The gates are a suppression
   policy with a measured cost curve, not a mechanism with a proof.
6. **Thesis phrasing (Q9).** "Without exposing" is precise for the
   individual and slightly loose for a small named group.

The stronger ground: the ML benchmark's circularity is handled honestly
and the model never ships (Q1); the prior art is credited rather than
obscured (Q5); the differencing-attack residual is measured and reported,
not waved away (Q7); and the unmeasured-parameter problem is stated as a
hard limit on what the project claims, not hidden (Q2).
