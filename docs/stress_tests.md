# Stress tests: scale and reporting realism

Two limitations were open: the system had only been exercised at 150 people
and only against a clean reporting model. Both are now tested. Regenerate
with `python -m scripts.stress_tests` (about four minutes; writes
`results/scale.json` and `results/reporting_realism.json`). No detection or
disclosure code was changed; the committed shipped results are byte-identical.

All parameters remain chosen, not measured. These tests say whether the
machinery holds up, not what real buildings do.

## 1. Scale (500 seeds per size, 30 days)

Structures: 150 (1 building), 500 (2 x 2 x 5 x 25), 1,000 (2 x 4 x 5 x 25),
2,000 (4 x 4 x 5 x 25). Four distinct scope populations at 500 and above
(campus / building / floor / suite); the 150 baseline has three (its building
equals its campus). Suite size stays 25.

| | 150 | 500 | 1,000 | 2,000 |
|---|---|---|---|---|
| runs that establish | 69% | 88% | 96% | 95% |
| attack rate, building(s) touched | 70% | 92% | 98% | 98% |
| buildings touched | 1 | 1 | 1 | 1 |
| evidence-gate evaluations checked | 63,703 | 102,155 | 179,535 | 197,600 |
| formula or pass-flag violations | 0 | 0 | 0 | 0 |
| campus / building / floor thresholds | 13 / 13 / 9 | 23 / 16 / 12 | 32 / 23 / 12 | 45 / 23 / 12 |
| roster refusals (scope-days) | 2 | 282 | 5,244 | 5,217 |
| first fire, day | 8.1 | 8.0 | 7.2 | 7.3 |
| first disclosure, day | 14.1 | 10.2 | 8.7 | 9.0 |
| fire-to-disclosure gap, days | 6.0 | 2.2 | 1.5 | 1.7 |
| infected before disclosure (people) | 35 | 53 | 107 | 118 |
| ... as % of all agents | 23% | 11% | 11% | 6% |
| false-alarm rate | 60% | 66% | 86% | 84% |
| errors / crashes | 0 | 0 | 0 | 0 |
| seconds per run | 0.01 | 0.03 | 0.06 | 0.10 |

**Nothing fails.** The evidence gate equals `max(5, ceil(sqrt(n)))` on every
one of about 543,000 evaluations, and no scope is ever named without passing
both gates. The privacy gate still fires, far more often than at 150. Runtime
is linear (about 0.5 s per run at 10,000 agents).

**What degrades or shifts, stated precisely:**

- **Outbreak plausibility is conditional, and is a modelling ceiling, not an
  engine fault.** In every multi-building structure the outbreak stays in one
  building (there is no campus-level contact) and then saturates it
  (92 to 98% attack rate), because the per-contact building probability does
  not dilute as buildings grow. The 150-person structure peaks at 70%. So the
  scale results are "one large building on fire", not "a campus". Fixing this
  needs a dilution or campus-contact model change, which was not attempted;
  the ceiling is reported instead.
- **The cost of the policy in days shrinks; in people it grows.** Bigger
  outbreaks accumulate reports faster, so the gates clear soon after
  detection (gap 6.0 to about 1.7 days), but the outbreak is bigger by then:
  35 people at 150, 118 at 2,000 (6% of all agents, but 24% of the affected
  building's 500).
- **The privacy gate binds far more.** At 1,000 and 2,000 agents, 95% of runs
  hit at least one roster refusal (a suite where more than half the members
  have reported), almost all at suite level, so the finest scope is repeatedly
  refused and disclosure retreats to the floor or building.
- **The false-alarm rate rises to 84 to 86%**, on small denominators (about 22
  to 25 non-established runs per size), so treat it as directional. More
  suites means more chances for one to look anomalous against its peers.
- **A campus-wide scope is never the finest disclosure at scale.** Its
  threshold (32 at 1,000, 45 at 2,000) exceeds the building's, and the
  outbreak sits in one building, so the campus scope adds nothing.

## 2. Reporting realism (500 paired runs; same outbreaks, different reporting)

Alternative model (`SimulationConfig(reporting_model="realistic")`, default
stays `clean`): per-person baselines from Beta(0.5, 0.5) (same mean 0.5,
U-shaped instead of uniform 0.3 to 0.7); correlated reporting
(`p' = 1 - (1-p)^(1 + 0.5 r)`, r = suite reports in the last 3 days, capped
at 4, applied to background reports too); stigma (`p' = 0.5 p` inside a
scope while named and for 7 days after). With every effect off it reproduces
the clean model record for record (tested).

| model | first fire | first disclosure | gap | infected before disclosure | false alarms | false disclosures | disclosure continuity |
|---|---|---|---|---|---|---|---|
| clean (shipped) | 8.1 | 14.1 | 6.0 | 35.2 | 60% | 0% | 74% |
| realistic, all three | 7.4 | 14.2 | 6.9 | 35.8 | 90% | 3% | 59% |
| heterogeneity only | 8.7 | 14.9 | 6.2 | 40.9 | 61% | 0% | 65% |
| correlation only | 6.7 | 12.4 | 5.7 | 27.1 | 91% | 4% | 80% |
| stigma only | 8.1 | 14.1 | 6.0 | 35.2 | 60% | 0% | 57% |

"False disclosures" are runs that never established but still named a scope.
"Continuity" is the share of days from first disclosure to day 30 on which a
scope was still being named.

**Is the detector robust? Partly, and the headline timing is misleading.**

- The full model barely moves disclosure timing (14.1 to 14.2 days) or
  infections before disclosure (35.2 to 35.8). That is **cancellation, not
  robustness**: heterogeneity alone pushes them worse (14.9 days, 40.9
  infected) and correlation alone pushes them better (12.4, 27.1). Across a
  4 x 4 strength grid (`reporting_realism.json`) infections before disclosure
  range 24 to 44 (minus 31% to plus 24% against 35.2) and disclosure delay
  11.9 to 15.4 days. The direction depends on which unmeasured effect
  dominates.
- **The false-alarm rate is not robust.** It is 60% clean and 78 to 100% as
  soon as any correlation is present, because reporting that feeds on itself
  amplifies the early spike of a fizzle. At correlation strength 1.0, about a
  quarter of outbreaks that never took off produce a false named disclosure
  (21 to 26%), against 0% clean.
- **Sustained disclosure erodes under stigma.** Continuity falls 74% to 57%
  (stigma alone) and 59% (all three): once a group is named and its members
  report less, the evidence under the gate decays and the system stops
  naming it. Stigma never changes *first* disclosure (suppression only starts
  after naming), so it is invisible in the timing columns.

**Verdict.** Detection timing degrades gracefully but its stability in the
full model is partly coincidence. The detector's low-false-alarm behaviour
depends on the clean, memoryless assumption, and a plausible correlated
process makes it materially worse and can produce false disclosures. The
limitation survives testing and is restated: it is exercised against two
reporting processes, both simulated with chosen constants, and never against
real reports.
