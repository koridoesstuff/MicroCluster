# MicroCluster — demo video script

**Target runtime:** ~3:05. No time limit is stated in the repo or in
`BUILD_PLAN.md`; the internal sketch in `BUILD_PLAN.md` §8 runs to ~2:00,
this expands it to ~3 minutes, still inside the 2–4 minute band a hackathon
demo wants. A 30-second trim is marked at the end if a hard 2:30 cap turns
up in the submission rules.

**Recording setup:** one browser tab, `uvicorn api.app:app`, window at
~1440px wide so the sticky limitations bar sits on one or two lines. All
narration is one voice, unhurried. Every number spoken below is pulled
from `results/*.json` — do not round differently on screen.

**The single run used throughout:** seed `4`, Suite size `25`,
Transmission `0.025`, Reporting rate `0.80`, Days `30`. This produces:
detector fires day 3, first disclosure (one suite) day 4, that suite fails
the privacy gate and disclosure retreats to the floor by day 8, peak
around day 11.

---

## Beat 1 — The human moment · 0:00–0:14 (14s)

**On screen:** page freshly loaded. Floor-plan area empty, showing "Set a
seed and press Run to start an outbreak." The sticky limitations bar is
visible across the top. Nothing moving.

**Narration:**
> Last winter, on one dorm floor, eight people came down with the same
> thing in the same week. None of them knew about the others. If someone
> had known, they could have acted on it. But knowing means someone has to
> say "I'm sick, and here's where I live" — and now that's on a list
> somewhere.

---

## Beat 2 — The spreading animation · 0:14–0:50 (36s)

**On screen:**
- Set Suite size `25`, drag Transmission to `0.025`, Reporting rate to
  `0.80`. Seed stays `4`, Days `30`.
- Press **Run**. Skeleton blocks appear, then the floor plan: two floors,
  three suites each, 25 circles per suite, all pale (susceptible), one
  amber (incubating).
- Press **Play**, speed **2x**. Let it run from day 0 to about day 12.
  One amber dot becomes several; red (symptomatic) fills the first suite;
  a second suite on the same floor starts turning; the counts line under
  the legend climbs.
- Press **Pause** near day 8.

**Narration:**
> MicroCluster simulates that floor. A hundred and fifty people, one index
> case, and contact through shared rooms, shared floors, the building.
> Every person here is anonymous — the system never sees a name. What it
> sees is a stream of symptom reports: one category from a fixed
> checklist, a rough onset, and which group you're in. No free text, no
> exact time, no room number. You can't leak what you never collected.

---

## Beat 3 — The detector fires, and the gate table · 0:50–1:20 (30s)

**On screen:**
- Still paused near day 8. Use **Step** / the day scrubber to go back to
  **day 5**. The status line reads: *System says: SUITE C-B1-F2-S1
  disclosed*. On the floor plan that one suite is boxed in red.
- Scroll down to the **Gate table, day 5**. Point at the rows: CAMPUS and
  BUILDING and FLOOR all say *Rejected: statistical gate failed*; the
  SUITE row says *Disclosed*.

**Narration:**
> Two detectors run on that report stream — one asks whether a location is
> unusually busy next to its neighbours, the other whether total activity
> is above the background rate. Either can fire. This one fired on day
> three. But firing isn't speaking. Before the system names anywhere,
> every candidate scope goes through two gates. The statistical gate: the
> bigger the group you want to name, the more reports you need — nine for
> a floor of seventy-five, thirteen for the whole building. On day five
> the finest scope that had enough evidence *and* was safe to name was one
> suite. So that's exactly what it said.

---

## Beat 4 — The privacy refusal · 1:20–1:56 (36s)

**On screen:**
- Scrub forward to **day 8**. The status line now reads *FLOOR C-B1-F2
  disclosed* — the disclosure has moved up a level. On the plan, all three
  suites of that floor are boxed.
- Grab the **Resolution** slider (labelled coarsest → finest) and drag it
  toward *finest*. It travels a little, then **stops hard**. The readout
  box turns red-bordered:
  *"Resolution stops at SUITE C-B1-F2-S1. Rejected: report fraction (over
  the limit) exceeds maximum 0.50 (disclosure would name so large a share
  of the group that the statement is effectively a roster)."*
- In the gate table below, the SUITE C-B1-F2-S1 row: statistical gate
  PASS, privacy gate **FAIL**.

**Narration:**
> By day eight the outbreak has taken that first suite. Watch what happens
> when I ask for more detail. The slider goes coarse to fine — and it
> stops. That suite now has more than half of its twenty-five people
> reporting. Naming it wouldn't describe a cluster anymore, it would
> publish a roster. So the system won't. It falls back to the floor. The
> privacy gate scales the opposite way from the statistical one: the
> smaller and more completely covered a group is, the harder it is to
> name. The two gates pull against each other, on purpose.

---

## Beat 5 — The delay curve · 1:56–2:26 (30s)

**On screen:** scroll to **THE COST OF THE PRIVACY POLICY**. The
hand-drawn line chart: x-axis "mean days to first disclosure", y-axis
"mean infections before disclosure", five points labelled 5, 8, 12, 16,
25 climbing left to right.

**Narration:**
> Restraint has a cost, and we measured it. Five hundred simulated
> outbreaks, detection held fixed, the disclosure gate tightened one step
> at a time. At the shipped setting the system discloses on day fourteen,
> with about thirty-five people infected. Tighten the gate all the way and
> first disclosure slides to day nineteen and eighty-two infected — while
> the detector is still firing on day eight the entire time. The gap
> between knowing and being allowed to say where is about six days. That's
> the price of the policy, counted in people.

---

## Beat 6 — The benchmark, and attacking our own output · 2:26–2:52 (26s)

**On screen:** scroll through **RULES VS LEARNED MODEL** (two rows),
**CROSS-PARAMETER ROBUSTNESS CHECK**, and stop on **ATTACKING OUR OWN
SYSTEM** with the two big numbers, 358 and 0.

**Narration:**
> We trained a classifier on the simulator's own ground truth and ran it
> against the hand-written rules. It's about a day faster and catches a
> few more outbreak-days — but it pays for that with false positives, on a
> detector that already over-alarms sixty percent of the time. So the
> rules ship; the model stays a benchmark. Then we attacked our own
> output. An observer who sees only what this page shows tries to subtract
> yesterday's count from today's. Against exact numbers that pins one
> person's illness on three hundred and fifty-eight days. Against the
> ranges we actually display: zero.

---

## Beat 7 — Limitations · 2:52–3:05 (13s)

**On screen:** scroll to the top so the sticky limitations bar fills the
frame, or click through to the **Privacy policy** page.

**Narration:**
> Everything you just saw is synthetic. The transmission rates, the
> reporting rates, the contact model — chosen to make a legible demo, none
> of them measured. This predicts nothing about a real building, and it
> diagnoses and treats no one. What it is: a working demonstration that
> you can pull a community-level signal out of sparse anonymous data
> without the signal becoming the leak.

---

**Total: ~3:05.**

### 30-second trim (to ~2:35) if a hard cap appears
- Beat 2: drop the last sentence ("You can't leak what you never
  collected.") and stop narration at "room number." (−6s)
- Beat 3: cut "one asks whether a location is unusually busy … the other
  whether total activity is above the background rate. Either can fire."
  down to "Two detectors run on the report stream; either can fire." (−7s)
- Beat 5: drop "counted in people" and the "still firing on day eight"
  clause. (−8s)
- Beat 6: drop the cross-regime scroll; cut "on a detector that already
  over-alarms sixty percent of the time." (−9s)
