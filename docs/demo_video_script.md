<!--
Reconciled with the redesigned UI (asset v=9). The page a viewer now sees:
  - sticky limitations bar across the top (unchanged)
  - title "MicroCluster", a one-line tagline, a ~50-word explainer paragraph
  - a collapsed "How it works" panel (native <details>)
  - a two-column workbench above ~1000px wide: LEFT column has the Run,
    Playback, Model parameters and Resolution panels; RIGHT column has the
    colour key, the "System says:" status line, the (initially hidden)
    red-bordered refusal box, the floor-plan caption, the floor plan
    itself (drawn on load, everyone susceptible), and the gate table
  - below the workbench, full width: "What the experiments found" (three
    headline sentences), then the cost chart, the rules-vs-model table,
    the cross-parameter robustness table, and the "Attacking our own
    system" panel with the two big numbers
  - a footer with Terms / Privacy links

HEADLINE-SUMMARY BEAT PLACEMENT: its own short beat (Beat 6), immediately
after the privacy refusal and BEFORE the cost chart / benchmark tables.
Reason: the three sentences in "What the experiments found" are the plain
-language version of exactly those panels. Showing them first makes the
chart and tables read as "here is the evidence for claims 1, 2 and 3"
rather than as new information, and a judge who stops watching right after
the money moment (the refusal) still leaves with all three findings. This
is bottom-line-up-front, not a recap.

Every number spoken is from results/*.json (500-seed sweep, 300-seed
benchmark, 200-seed self-test). Re-verified against the guided run:
detector fires day 3, first disclosure (one suite) day 4, that suite fails
the privacy gate and disclosure retreats to the floor by day 8, then
climbs to the building by day 10; symptomatic count peaks day 12.
-->

# MicroCluster — demo video script

**Target runtime:** ~3:00. No hard limit is stated in the repo or
`BUILD_PLAN.md`; the internal sketch in `BUILD_PLAN.md` §8 runs to ~2:00,
this expands it, still inside the 2 to 4 minute band a hackathon demo
wants. A 25-second trim is marked at the end if a hard 2:30 cap turns up
in the submission rules.

**Recording setup:** one browser tab, `uvicorn api.app:app`, window at
~1440px wide so the two-column layout is in effect and the sticky
limitations bar sits on one line. One unhurried voice.

**The single run used throughout:** the **Run the guided example** button.
It sets seed `4`, suite size `25`, transmission `0.025`, reporting `0.80`,
30 days, and starts playback. Do not set these by hand.

---

## Beat 1 — The human moment · 0:00–0:15 (15s)

**On screen:** page freshly loaded. The sticky limitations bar is across
the top. Below the title, the tagline and the explainer paragraph. The
right column already shows the floor plan drawn in full: two floors, three
suites each, twenty-five pale circles per suite, every one susceptible.
Nothing is moving. The status line reads *System says: no run yet*.

**Narration:**
> Last winter, on one dorm floor, eight people came down with the same
> thing in the same week. None of them knew about the others. If someone
> had known, they could have acted on it. But knowing means someone has to
> say "I'm sick, and here's where I live", and now that's on a list
> somewhere.

---

## Beat 2 — What it is · 0:15–0:36 (21s)

**On screen:** cursor moves to the **How it works** panel and clicks it
open. The four numbered steps appear: reports flow in, the detector flags
a statistical excess in a window, two gates decide whether anything may be
said, the finest scope clearing both is disclosed or nothing is.

**Narration:**
> This is a simulator for exactly that problem. An illness spreads through
> a simulated floor. A detector that sees only anonymous symptom reports,
> never a name, never a room, tries to find the outbreak it was never told
> about. When it finds one it reports where the cluster is, at the finest
> scope that is both statistically supported and safe to name. Everything
> on this page is simulated, and it says so.

---

## Beat 3 — The spreading animation · 0:36–1:08 (32s)

**On screen:**
- Click **Run the guided example**. A one-line hint under the button
  already says what to watch for. Skeleton blocks flash, then the plan
  repopulates and playback starts on its own.
- Let it run to about day 12. In suite C-B1-F2-S1 one circle goes amber
  (incubating), then several, then red (symptomatic, drawn with a heavy
  ring); a second suite on that floor starts turning; the counts line
  under the colour key climbs.
- Click **Pause** near day 12.

**Narration:**
> One index case, a hundred and fifty people, and contact through shared
> rooms, shared floors, the building. Every person here is anonymous. What
> the detector sees is a stream of reports: one category from a fixed
> checklist, a rough onset, and which group you are in. No free text, no
> exact time, no room number. You cannot leak what you never collected.

---

## Beat 4 — The detector fires, and the gate table · 1:08–1:35 (27s)

**On screen:**
- Drag the **Day** scrubber in the Playback panel back to **day 5**. The
  status line reads *System says: SUITE C-B1-F2-S1 disclosed (first on day
  4)*. On the plan that one suite is boxed with a heavy red border.
- Look at the **Gate table, day 5** in the right column. CAMPUS, BUILDING
  and FLOOR rows read *Rejected: statistical gate failed*; the
  SUITE C-B1-F2-S1 row is highlighted and its reason begins *Disclosed*.

**Narration:**
> Two detectors run on that report stream, one comparing a location to its
> neighbours, one comparing total activity to a background rate. Either can
> fire. This one fired on day three. But firing is not speaking. Every
> candidate scope goes through two gates. The statistical gate: the bigger
> the group you want to name, the more reports you need, nine for a floor
> of seventy-five, thirteen for the whole building. On day five the finest
> scope with enough evidence that was also safe to name was one suite. So
> that is what it said.

---

## Beat 5 — The privacy refusal · 1:35–2:08 (33s)

**On screen:**
- Scrub forward to **day 8**. The status line now reads *SYSTEM SAYS:
  FLOOR C-B1-F2 disclosed*, and a red-bordered box appears directly below
  it:
  *"Privacy refusal. The system has enough evidence to name SUITE
  C-B1-F2-S1, but will not: report fraction over the limit of 0.50
  (disclosure would name so large a share of the group that the statement
  is effectively a roster). It disclosed FLOOR C-B1-F2 instead."*
- Grab the **Resolution** slider in the left column and drag toward
  *finest*. It travels a little, then stops hard. The readout box turns a
  heavy red:
  *"Resolution stops at SUITE C-B1-F2-S1. Rejected: report fraction over
  the limit of 0.50 (disclosure would name so large a share of the group
  that the statement is effectively a roster)."*
- In the gate table, the SUITE C-B1-F2-S1 row: statistical gate **PASS**,
  privacy gate **FAIL**.

**Narration:**
> By day eight the outbreak has taken that first suite. Watch what happens
> when I ask for more detail. The slider goes coarse to fine, and it
> stops. That suite now has more than half of its twenty-five people
> reporting. Naming it would not describe a cluster any more, it would
> publish a roster. So the system will not. It falls back to the floor.
> The privacy gate scales the opposite way from the statistical one: the
> smaller and more completely covered a group is, the harder it is to
> name. The two gates pull against each other, on purpose.

---

## Beat 6 — The three findings · 2:08–2:22 (14s)

**On screen:** scroll down to **WHAT THE EXPERIMENTS FOUND**, three
sentences. Let each land.

**Narration:**
> We ran this hundreds of times and measured three things. One: the
> detector fires around day eight, but the privacy rules do not allow
> disclosure until about day fourteen, and roughly thirty-five people are
> infected in that gap. Two: a learned model is about a day faster than
> the hand-written rules but less precise. Three: against the ranges this
> page shows, an observer cannot pin a single person's overnight change.

---

## Beat 7 — The evidence · 2:22–2:45 (23s)

**On screen:** keep scrolling. The **cost of the privacy policy** chart:
five points labelled 5, 8, 12, 16, 25 climbing left to right. Then the
**Rules vs learned model** table (two rows) and the **cross-parameter
robustness check** table.

**Narration:**
> That six-day gap is the chart. Detection held fixed, the disclosure gate
> tightened one step at a time over five hundred outbreaks. At the shipped
> setting, disclosure on day fourteen, about thirty-five infected. Tighten
> it all the way and first disclosure slides to day nineteen and
> eighty-two infected. The model is faster but buys it with false
> positives on a detector that already over-alarms sixty percent of the
> time, so the rules ship and the model stays a benchmark.

---

## Beat 8 — Attacking our own output, and limitations · 2:45–3:02 (17s)

**On screen:** scroll to **ATTACKING OUR OWN SYSTEM**, the two big numbers
**358** and **0**, and the line below them about the residual leak. Then
scroll back to the top so the limitations bar fills the frame.

**Narration:**
> Then we attacked our own output. An observer differencing exact counts
> pins one person's change on three hundred and fifty-eight days. Against
> the bands this page ships, zero, though the direction of the change
> still leaks on about two hundred day-pairs, and we say so. Everything
> here is synthetic, chosen to make a legible demo, measured from nothing.
> It predicts nothing about a real building and diagnoses no one. What it
> is: a working demonstration that you can pull a community signal out of
> sparse anonymous data without the signal becoming the leak.

---

**Total: ~3:02.**

### 25-second trim (to ~2:37) if a hard cap appears
- Beat 2: stop narration at "safe to name." Drop the last two sentences
  (the limitations bar is still on screen the whole time). (−7s)
- Beat 3: drop "You cannot leak what you never collected." (−4s)
- Beat 4: cut "one comparing a location to its neighbours, one comparing
  total activity to a background rate" down to "one relative, one
  absolute". (−6s)
- Beat 7: drop "on a detector that already over-alarms sixty percent of
  the time." (−8s)
