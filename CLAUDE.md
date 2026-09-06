# MicroCluster

**Thesis: it detects the signal without exposing the person who created it.**

MicroCluster is a privacy-preserving health-signal system for small shared
communities (a co-op, a dorm, an office floor, a shared studio building).
People submit anonymous symptom reports from a **fixed checklist**. The
system looks for statistically unusual activity and, when it finds some,
discloses it **only at a scope that is both statistically supported and
privacy-safe** — otherwise it discloses nothing.

This is not an outbreak-prediction tool and it does not diagnose anyone.
The engineering problem is narrow and specific:

> Extract a community-level signal from sparse, anonymous data without
> letting the signal become a privacy leak.

**Idea locked September 2. No concept evaluation before October 6.**

Everything below is a **decided rule**, not a design open for revision.

---

## What is in this repository right now

Only three things:

1. **Detection engine** (`microcluster/detection.py`) — decides whether
   anything unusual is happening.
2. **Disclosure engine** (`microcluster/disclosure.py`) — decides what, if
   anything, may be said out loud and at what scope.
3. **Tests** (`tests/`) — cover the scenarios listed at the bottom.

No frontend. No API. No replay mode. `microcluster/engine.py` is a thin
wire between the two engines and `microcluster/demo.py` prints the six
reference scenarios.

Detection and disclosure are **separate, independently testable modules**.
They share only plain aggregate data structures. The disclosure engine
never receives individual records (see rule 10).

**Being added now (see the SIMULATION section):** an interactive simulator
that generates anonymous reports and feeds them to the detection engine to
measure how late the detector catches an outbreak. It does **not** modify
`config.py`, `models.py`, `detection.py`, `disclosure.py`, `engine.py` or
their tests — those are the foundation and stay exactly as they are. The
simulator only produces `Report` objects for the existing engines to
consume.

---

## Decided rules

### 1. Fixed checklist, never free text

Input is a **fixed checklist**. There is no natural-language interpretation
anywhere in the system.

- Four categories: **Respiratory, Gastrointestinal, General, Other**, each
  with 3–5 named symptoms (`microcluster/models.py::CHECKLIST`).
- Coarse onset: `today` / `1-2 days` / `3-7 days` / `1+ week`.
- A location group: one node in the scope hierarchy.

The specific symptom is recorded for the reporter's own clarity. It is
**never** used for matching.

### 2. Clustering at CATEGORY level only

Reports are only ever grouped by **category**, never by individual symptom.
This is what makes *"we don't diagnose"* structurally true rather than a
promise — the code has no finer-grained medical concept to reason about.

### 3. Two independent detectors, either can fire

- **Relative detector** — is this location unusual compared to its
  *contemporaneous peers* (sibling scopes, same detection window)?
- **Absolute detector** — is overall activity unusual compared to a
  configured background rate?

Either one firing counts as detection. They are computed separately and
reported separately.

### 4. `BACKGROUND_RATE` is a named, configurable, illustrative constant

`microcluster/config.py::BACKGROUND_RATE` is the approximate fraction of a
population expected to file a qualifying report within one detection
window under ordinary conditions.

**It is an illustrative figure, not a clinical or epidemiological
estimate.** It lives in `config.py` with a comment saying exactly that.
It is never inlined into scoring code. Tune it from real baseline data
before trusting the absolute detector.

### 5. `DETECTION_WINDOW` is a named constant, default 72 hours

`microcluster/config.py::DETECTION_WINDOW_HOURS = 72`. A report is
"current activity" if it was submitted within this many hours of the
evaluation time.

### 6. No composite score

The detection engine reports **three findings, plainly**, and never
combines them into one number:

- `relative_excess_ratio` — the driving location's per-capita rate divided
  by its peers' pooled per-capita rate.
- `count_within_window` — total qualifying reports in the detection window.
- `count_sharing_category` — how many of those share a single category.

A composite score would hide which of these actually moved, and would
invite threshold-tuning that trades privacy for sensitivity invisibly.

### 7. Every scope has a DECLARED population `n`

Each scope (campus / building / floor / suite) carries a population `n`
**declared at group creation**. It is never the number of people who
happened to report. All gate math uses the declared `n`.

### 8. Two separate gates, both must pass

A scope may be disclosed only if it passes **both** of these, evaluated
independently and reported separately:

- **Statistical gate:**
  `qualifying_reports >= max(STATISTICAL_GATE_FLOOR, ceil(sqrt(n)))`
  (`STATISTICAL_GATE_FLOOR = 5`). This scales **up** with `n`: a claim
  about a bigger population needs more evidence.

- **Privacy gate:**
  `n >= MIN_SCOPE_POPULATION` (default 20)
  **and** `qualifying_reports / n <= MAX_REPORT_FRACTION` (configurable).
  This scales **down** with `n`: small scopes are the dangerous ones.

The two gates **pull in opposite directions by design**. They are never
merged into a single number. Merging them would make the most identifying
statement (a tiny, precise scope) the *cheapest* to make — which is
backwards. Keeping them separate means a small scope must clear a bar that
a large scope does not, and a large scope must clear a bar that a small
scope does not.

### 9. Disclose the finest scope passing both gates

Evaluate every candidate scope with the single rule in rule 8. Disclose
the **finest** scope (deepest level, then smallest `n`) that passes both
gates. If none passes, **disclose nothing**. There is no hardcoded tier
list — `campus → building → floor → suite` falls out of applying one rule
to a set of candidates.

### 10. Privacy evaluation runs AFTER detection, before presentation

Order is fixed: detection → disclosure → presentation. The disclosure
engine is handed **aggregate per-scope counts and declared populations**,
never individual records. The presentation layer (not built yet) will be
handed only the evaluation table from rule 12 and must render it as-is.

### 11. Anonymity over identity-based abuse prevention

Reports are anonymous. That means abuse — someone spamming reports to
manufacture a signal — is **possible, and we accept it** as the cost of
anonymity.

Light mitigation only: a per-session submission cap
(`SESSION_SUBMISSION_CAP`) and a per-day cap (`DAILY_SUBMISSION_CAP`),
both named constants in `config.py`, enforced at intake (intake is not
part of this repo yet). We deliberately choose these weak, anonymous
mitigations over any identity-based control (accounts, device binding,
verification), because identity is precisely what the system exists to
protect.

### 12. Every candidate scope gets a complete evaluation record

`disclosure.evaluate(...)` returns a `ScopeEvaluation` for **every**
candidate scope, including the rejected ones — not just the winner. Each
record contains:

- scope id, label, level
- declared population `n`
- qualifying report count
- statistical threshold and PASS/FAIL
- privacy threshold(s) and PASS/FAIL (minimum population, report fraction)
- final `disclosure_eligible` (both gates) and `selected`
- a `disclosure_reason` string explaining the outcome, e.g.
  *"Rejected: population n=18 below minimum privacy scope (20)"*

The winning disclosure is **selected from this table**, never computed on
its own path. A future UI renders these records directly and must never
recompute a gate result itself.

---

## Every threshold is a policy, not a law

`ceil(sqrt(n))`, `STATISTICAL_GATE_FLOOR`, `MIN_SCOPE_POPULATION`,
`MAX_REPORT_FRACTION`, `BACKGROUND_RATE`, `ABSOLUTE_EXCESS_RATIO`,
`RELATIVE_EXCESS_RATIO`, `DETECTION_WINDOW_HOURS` — these are
**project-defined policies**. They are:

- **named** — all in `microcluster/config.py`,
- **configurable** — via `DetectionConfig` / `DisclosureConfig`,
- **documented as choices** — here and in `config.py` comments.

None of them is derived from a proven result. `sqrt(n)` is a reasonable
shape for "evidence should scale with the size of the claim", not a
theorem about this problem.

---

## Detection hysteresis and disclosure scope stability

`detection.evaluate` and `disclosure.evaluate` are each still, in
isolation, a pure single-instant computation. Called in a SEQUENCE (once a
day over a live event), both accept optional state threaded from the
previous call, and both use that state the same way: prefer continuity
over reacting to a single noisy instant.

- **Detection hysteresis.** Once fired, `fired` is held `True` for at
  least `HYSTERESIS_MIN_FIRED_DAYS` consecutive evaluations even if that
  day's raw relative/absolute check alone says no — an ordinary wobble in
  which reports fall inside a rolling 72h window should not flip
  detection off and back on inside one ongoing event. It releases early
  regardless of the minimum if the window's qualifying count drops to
  `HYSTERESIS_RELEASE_THRESHOLD` or below: a drop that low means the event
  is genuinely over. State is `HysteresisState`, threaded explicitly
  (never global); a call with no state behaves exactly as if hysteresis
  did not exist.

- **Disclosure scope stability.** Once a scope has been disclosed, passing
  its id as `prior_disclosed_scope_id` makes `evaluate` prefer to keep
  disclosing that scope, or a coarser ancestor of it if the exact scope
  stops qualifying, over hopping to a different scope. It only switches
  away from that lineage when some other scope's qualifying count exceeds
  it by more than `SIBLING_SWITCH_MARGIN`. Each disclosure still passes
  both gates on its own; the point is that the SEQUENCE of disclosures
  leaks more than any one of them does — an observer who watches it
  wander learns about every group it ever names, not just one. A call
  with no prior id is unaffected.

Both constants live in `microcluster/config.py` next to every other
threshold, for the same reason: named, configurable, and not a proven
law. `simulation/pipeline.py` is the reference caller — it threads both
kinds of state day to day and records, in `DailyRecord`, the running
`first_fired_day` and `first_disclosed_day`. The gap between them is the
measurable cost of the privacy policy: how long the system knew something
before it was permitted to say where.

---

## Test scenarios (`tests/`)

- **Localized cluster** — relative detector fires, absolute does not; a
  suite-level disclosure.
- **Campus-wide rise** — absolute detector fires, relative does not; a
  campus-level disclosure.
- **Scattered noise** — neither detector fires; nothing disclosed.
- **Overclaim refusal** — 7 reports, campus `n=2000`: statistical gate
  fails (`7 < 45`); no campus-level disclosure.
- **Privacy refusal** — 5 reports, floor `n=18`: statistical gate passes
  (`5 >= 5`) but privacy gate fails (`18 < 20`); a coarser scope is
  disclosed instead.
- **Both gates across populations** — `n ∈ {12, 18, 40, 100, 500, 2000}`:
  the statistical threshold rises with `n` while the privacy minimum
  rejects the smallest scopes.
- **Roster refusal** — ~15 qualifying reports in a declared group of
  `n=25`: passes the statistical gate (`15 >= 5`) and the population
  minimum (`25 >= 20`), but refused because `15/25 = 0.60` exceeds
  `MAX_REPORT_FRACTION` (0.5). Naming the group would name its members.
- **Edge cases** — zero reports (nothing detected, nothing disclosed); a
  `Report` carrying a symptom outside the fixed checklist is rejected at
  construction.

Run them:

```
python -m unittest discover -s tests -v
python -m microcluster.demo      # prints the scenario evaluation tables
```

---

## Relative detector: additive smoothing

The relative excess ratio is additively (Laplace) smoothed on both sides:

```
(reports_here + k) / (n_here + k)
--------------------------------------  >= RELATIVE_EXCESS_RATIO  ->  fires
(reports_control + k) / (n_control + k)
```

`k` is `config.RELATIVE_SMOOTHING` (default 1, one pseudo-report per
pseudo-person). Without it, a quiet peer group pushes the control rate to
almost zero and the ratio blows up into the hundreds or to infinity: a
number that reads as precise but is really just division-by-noise. `k`
pulls both rates toward a neutral prior, so the ratio stays finite and
comparable across scopes. It is a policy constant like every other
threshold here, not a derived value.

---

## SIMULATION

The project is expanding into an **interactive simulator**. Everything
already built stays exactly as it is — `config.py`, `models.py`,
`detection.py`, `disclosure.py`, `engine.py` and their passing tests are
the foundation and are **not** redesigned. The simulator is new code that
sits *around* them.

### What the simulator does

1. Simulates an illness spreading through a small shared environment — a
   dorm floor of **20 to 200 people**.
2. Generates **anonymous symptom reports** from the simulated people, from
   the same fixed checklist the real system uses.
3. Feeds those reports into the **existing detection engine**, unchanged.
4. Measures **how late** the detector catches the outbreak — the delay
   between the outbreak actually taking hold and the detector firing.

The thesis does not move: *it detects the signal without exposing the
person who created it.* The project still does **not** claim to predict
real outbreaks. It is an engineering problem with a measurement attached:
extract a community-level signal from sparse anonymous data without letting
the signal become a privacy leak, and quantify how well that works.

### Three outputs by submission

1. **Live animation** of the outbreak spreading through the environment,
   with the detector firing shown against it.
2. **Delay curve** — how many extra infections each additional day of
   detection delay costs.
3. **Benchmark** — a classifier trained on the simulator's ground truth,
   scored against the hand-authored threshold rules in `config.py` /
   `disclosure.py`. The point is to see how the simple, legible policy
   rules compare to a fitted model on the same data.

### The ground-truth firewall

The simulator knows everything: who is infected, when, who infects whom.
That knowledge is the simulator's alone. It is **never** passed to
`detection` or `disclosure`. Those engines receive exactly what they
receive in production — anonymous `Report` objects and declared scope
populations — and nothing else. This is the same boundary as rule 10,
extended: detection sees reports, disclosure sees aggregates, and neither
ever sees the simulation's ground truth. The benchmark classifier (output
3) is the *only* consumer of ground truth, and it is scored, not wired
into the disclosure path.

### Constraints (unchanged, and binding on the simulator)

- **Fixed symptom checklist**, never free text. No natural-language
  interpretation anywhere, including in the report generator.
- **Clustering at category level only**, never individual-symptom
  matching.
- **Two detectors in parallel**: relative (versus contemporaneous peers)
  and absolute (versus the configured background rate).
- **Two disclosure gates, both must pass**: statistical (scales up with
  `n`) and privacy (scales down with `n`).
- **Every threshold is a named, configurable constant** with a comment
  explaining the choice — the simulator's own parameters included.
- **Privacy evaluation runs after detection, before presentation.** The
  animation and the delay curve render engine output; they do not
  recompute gates.
- **Every emitted report is at the same `ScopeLevel` — `SUITE`.**
  `detection.evaluate` raises `ValueError` on mixed-level input (its
  peer-population math only holds for sibling locations). Each simulated
  agent belongs to one suite; a report's `location_id` is always that
  suite. The coarser scopes (`FLOOR`, `BUILDING`, `CAMPUS`) exist only in
  the `ScopeRegistry` as the suite's ancestors, and are reached through
  the registry, never by emitting a report against them.

### Simulation parameters are chosen, not measured

Transmission probability, incubation distribution, reporting propensity,
contact structure, background symptom rate — every one of these is a
**chosen** figure, picked to produce a legible demonstration, not measured
from real data. **Anything user-facing must say so**, in the same plain
language `config.py` uses for `BACKGROUND_RATE`. The simulator's constants
live in their own config module with the same naming and commenting
discipline as `microcluster/config.py`.

### Timeline

- **Idea locked: September 2.** No concept evaluation before October 6.
- **Feature freeze: September 25.**
- **Submission: October 6.**

---

## SECURITY POSTURE

- No accounts, no passwords, no sessions, no external API keys, no
  uploads, no SQL, no free text. Most standard web vulnerabilities are
  **structurally absent, not mitigated**. There is no auth to bypass, no
  injection sink, no file handler, no session to fixate.
- Input validation is **whitelist-based** via the fixed checklist
  (`models.py`). A `Report` whose category, onset, or symptom is not an
  exact member of the closed vocabulary is rejected at construction.
- The privacy strategy is **DATA MINIMIZATION, not encryption**. The
  system never holds identity, free text, precise time, or precise
  location, so there is very little to encrypt. You cannot leak what you
  did not collect.
- **CRITICAL for the future API layer:** detection and disclosure MUST
  run server side. Raw `Report` objects must NEVER be sent to the client.
  The API returns `ScopeEvaluation` records (and the detection findings)
  only. Doing gate evaluation or scope selection in the client would make
  the privacy gate bypassable with devtools, network inspection, or a
  patched bundle.
- Anonymity was chosen over identity-based abuse prevention. Per-session
  and per-day submission caps (`SESSION_SUBMISSION_CAP`,
  `DAILY_SUBMISSION_CAP`) are the only mitigation, and this is
  deliberate: identity is the thing the system exists to protect, so we
  will not introduce it to stop abuse.

---

## UI CONSTRAINTS (binding when the frontend is built)

There is no frontend yet. When one is built, these are binding.

**Prohibited:** gradients, Lucide icons, pure white backgrounds, rainbow
coloring, drop shadows, three-feature-card rows, emoji, glassmorphism, em
dashes in copy, Inter / Geist / Space Grotesk, colored left stripes, fake
testimonials, bento grids, terminal window mockups, "it's not X, it's Y"
phrasing, checkmark bullets, three pricing tiers, soft corner radii,
purple-and-black, radial orbs, dot grids, sparkle icons, animated arrows,
hover animations, neon colors, basic pastels.

**Required:** real working product demos (not mockups); skeleton loaders
for async states; a Terms of Service page; and a privacy policy that
states the ACTUAL mechanism (what is stored, what is never collected, how
the thresholds work) rather than boilerplate.

**Visual direction:** flat, high contrast, documentary / clinical.
Off-white or light gray background. Fonts limited to the system UI stack,
IBM Plex, Source Sans, or a serif such as Charter.
