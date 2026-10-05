"use strict";

// MicroCluster outbreak animation. Plain DOM, no framework, no build step.
// Detection and disclosure happen server-side; this file only draws what
// /api/run and /api/run/{id}/day/{n} return.

// render free tier edge returns intermittent 404/502 (x-render-routing:
// no-server) before the request reaches the app. retry those a few times
async function apiFetch(url, opts, tries = 4) {
  let lastErr;
  for (let attempt = 0; attempt < tries; attempt++) {
    if (attempt > 0) await new Promise((r) => setTimeout(r, 300 * 2 ** (attempt - 1)));
    try {
      // a stalled connection should surface as a plain "timed out" error,
      // not hang the UI (and the "Running..." label) forever
      const res = await fetch(url, { ...opts, signal: AbortSignal.timeout(20000) });
      if (res.ok) return res;
      if (![404, 502, 503, 504].includes(res.status) || attempt === tries - 1) return res;
      lastErr = new Error(res.status + " " + (await res.clone().text()).slice(0, 120));
    } catch (err) {
      lastErr = err;
    }
  }
  throw lastErr;
}

const els = {
  seed: document.getElementById("seed"),
  days: document.getElementById("days"),
  run: document.getElementById("run"),
  runGuided: document.getElementById("run-guided"),
  refusal: document.getElementById("refusal"),
  planPop: document.getElementById("plan-pop"),
  summaryList: document.getElementById("summary-list"),
  play: document.getElementById("play"),
  pause: document.getElementById("pause"),
  step: document.getElementById("step"),
  reset: document.getElementById("reset"),
  speed: document.getElementById("speed"),
  scrub: document.getElementById("scrub"),
  dayLabel: document.getElementById("day-label"),
  dayMax: document.getElementById("day-max"),
  status: document.getElementById("status"),
  counts: document.getElementById("counts"),
  plan: document.getElementById("plan"),
  emptyNote: document.getElementById("empty-note"),
  disclaimer: document.getElementById("disclaimer"),
  resSlider: document.getElementById("res-slider"),
  resReadout: document.getElementById("res-readout"),
  resEndCoarse: document.getElementById("res-end-coarse"),
  resEndFine: document.getElementById("res-end-fine"),
  runSummary: document.getElementById("run-summary"),
  sumDetected: document.getElementById("sum-detected"),
  sumDetectedDay: document.getElementById("sum-detected-day"),
  sumDisclosure: document.getElementById("sum-disclosure"),
  sumRefused: document.getElementById("sum-refused"),
  sumRefusedDay: document.getElementById("sum-refused-day"),
  gateDay: document.getElementById("gate-day"),
  gateBody: document.getElementById("gate-body"),
  pPopulation: document.getElementById("p-population"),
  pTransmission: document.getElementById("p-transmission"),
  pReporting: document.getElementById("p-reporting"),
  pWindow: document.getElementById("p-window"),
  pPopulationHint: document.getElementById("p-population-hint"),
  pTransmissionHint: document.getElementById("p-transmission-hint"),
  pReportingHint: document.getElementById("p-reporting-hint"),
  paramsDirty: document.getElementById("params-dirty"),
};

// captured once at load, before either button's label can be swapped to
// "Running..." while a fetch is in flight
const RUN_LABEL = els.run.textContent;
const GUIDED_LABEL = els.runGuided.textContent;

const state = {
  runId: null,
  totalDays: 0,
  frames: [],          // frames[n] = day payload
  currentDay: 0,
  timer: null,
  agentCells: new Map(), // key `${suite}#${i}` -> <div class="agent">
  suiteEls: new Map(),   // suite id -> <div class="suite">
  evals: [],           // current day's candidate scopes, coarsest -> finest
  wallIdx: -1,         // first index that FAILED the privacy gate, or -1
  maxResIdx: 0,        // furthest the slider may travel (the wall, inclusive)
  resIdx: 0,           // slider position
  lastDisclosedScopeId: undefined, // undefined = no paint yet; null = disclosed nothing
  summary: null,        // running end-of-run summary, built while frames load
};

// SUITE is the finest scope level; used to compare disclosures across a run
// to find the most specific one ever made (never hardcoded against a tier list)
const LEVEL_RANK = { CAMPUS: 1, BUILDING: 2, FLOOR: 3, SUITE: 4 };

// scope ids nest by "-" prefix: "C-B1-F2" covers "C-B1-F2-S1".
function scopeCoversSuite(scopeId, suiteId) {
  return scopeId === suiteId || String(suiteId).startsWith(scopeId + "-");
}

function setPlaybackEnabled(on) {
  for (const b of [els.play, els.pause, els.step, els.reset]) b.disabled = !on;
  els.scrub.disabled = !on;
}

function stopTimer() {
  if (state.timer !== null) {
    clearInterval(state.timer);
    state.timer = null;
  }
}

// ---- rendering -----------------------------------------------------------

function renderSkeleton() {
  els.plan.classList.add("loading");
  els.plan.innerHTML = "";
  els.plan.setAttribute("aria-label", "Loading the floor plan.");
  for (let f = 0; f < 2; f++) {
    const floor = document.createElement("div");
    floor.className = "floor";
    const label = document.createElement("div");
    label.className = "floor-label";
    label.textContent = "loading";
    const suites = document.createElement("div");
    suites.className = "suites";
    for (let s = 0; s < 3; s++) {
      const sk = document.createElement("div");
      sk.className = "skeleton-suite";
      suites.appendChild(sk);
    }
    floor.append(label, suites);
    els.plan.appendChild(floor);
  }
}

function buildPlan(layout) {
  els.plan.classList.remove("loading");
  els.plan.innerHTML = "";
  els.plan.setAttribute("aria-label", "Floor plan. Everyone susceptible; the simulation has not run yet.");
  state.agentCells.clear();
  state.suiteEls.clear();

  for (const floor of layout.floors) {
    const floorEl = document.createElement("div");
    floorEl.className = "floor";

    const label = document.createElement("div");
    label.className = "floor-label";
    label.textContent = "Floor " + floor.label;

    const suitesEl = document.createElement("div");
    suitesEl.className = "suites";

    for (const suite of floor.suites) {
      const suiteEl = document.createElement("div");
      suiteEl.className = "suite";
      suiteEl.dataset.suite = suite.id;

      const sLabel = document.createElement("div");
      sLabel.className = "suite-label";
      sLabel.textContent = suite.label + "  n=" + suite.size;

      const agentsEl = document.createElement("div");
      agentsEl.className = "agents";
      for (let i = 0; i < suite.size; i++) {
        const cell = document.createElement("div");
        cell.className = "agent s-susceptible";
        agentsEl.appendChild(cell);
        state.agentCells.set(suite.id + "#" + i, cell);
      }

      suiteEl.append(sLabel, agentsEl);
      suitesEl.appendChild(suiteEl);
      state.suiteEls.set(suite.id, suiteEl);
    }

    floorEl.append(label, suitesEl);
    els.plan.appendChild(floorEl);
  }
}

// a one-shot ring, nothing else, on the instant a circle turns symptomatic.
// restart-safe (remove, force reflow, re-add) so a rapid re-trigger still plays.
function triggerPulse(cell) {
  cell.classList.remove("pulse");
  void cell.offsetWidth;
  cell.classList.add("pulse");
  setTimeout(() => cell.classList.remove("pulse"), 400);
}

function triggerStatusChange() {
  els.status.classList.remove("change-in");
  void els.status.offsetWidth;
  els.status.classList.add("change-in");
  setTimeout(() => els.status.classList.remove("change-in"), 250);
}

// `stepped` is true only for a genuine single forward step during real
// playback (advance(), driven by Step or the timer) -- never on initial
// load, a scrub jump, or ?auto=dayN. That is what keeps every screenshot
// (which always jumps straight to a day) free of the pulse / row-flash
// motion below: there is no previous rendered day to diff against.
function paintDay(n, opts = {}) {
  const frame = state.frames[n];
  if (!frame) return;
  const stepped = Boolean(opts.stepped) && n === state.currentDay + 1 && Boolean(state.frames[n - 1]);
  const prevFrame = stepped ? state.frames[n - 1] : null;
  state.currentDay = n;

  const prevAgentState = new Map();
  if (prevFrame) {
    for (const a of prevFrame.agents) prevAgentState.set(a.suite + "#" + a.i, a.state);
  }
  // diffed, not reset-then-set: every agent is present in every frame, so
  // only cells whose state actually changed get a new class -- a colour
  // transition on every cell every day would read as the grid flashing
  for (const a of frame.agents) {
    const key = a.suite + "#" + a.i;
    const cell = state.agentCells.get(key);
    if (!cell) continue;
    const cls = "agent s-" + a.state;
    if (cell.className !== cls) cell.className = cls;
    if (prevFrame && a.state === "symptomatic" && prevAgentState.get(key) !== "symptomatic") {
      triggerPulse(cell);
    }
  }

  renderResolution(frame);
  renderGateTable(frame, prevFrame);

  const d = frame.disclosure;
  const resScope = state.evals[state.resIdx];
  for (const [suiteId, suiteEl] of state.suiteEls) {
    suiteEl.classList.toggle(
      "disclosed", Boolean(d && scopeCoversSuite(d.scope_id, suiteId))
    );
    suiteEl.classList.toggle(
      "resolution", Boolean(resScope && scopeCoversSuite(resScope.scope_id, suiteId))
    );
  }

  const c = frame.counts;
  els.counts.textContent =
    `susceptible ${c.susceptible} · incubating ${c.incubating} · ` +
    `symptomatic ${c.symptomatic} · recovered ${c.recovered}`;
  // text alternative for the role=img plan -- the numbers, not the pixels
  els.plan.setAttribute(
    "aria-label",
    `Floor plan, day ${n}. ${c.susceptible} susceptible, ${c.incubating} incubating, ` +
    `${c.symptomatic} symptomatic, ${c.recovered} recovered` +
    (d ? `. Disclosed scope: ${d.level} ${d.label}.` : ".")
  );

  els.dayLabel.textContent = String(n);
  els.scrub.value = String(n);

  // undefined only before the very first paint -- a fresh load (including
  // every ?auto=dayN screenshot) never sees this as a "change"
  const newScopeId = d ? d.scope_id : null;
  const scopeChanged =
    state.lastDisclosedScopeId !== undefined && state.lastDisclosedScopeId !== newScopeId;
  state.lastDisclosedScopeId = newScopeId;

  if (d) {
    els.status.textContent =
      `System says: ${d.level} ${d.label} disclosed` +
      (frame.first_disclosed_day !== null ? ` (first on day ${frame.first_disclosed_day})` : "");
    els.status.classList.add("flagged");
  } else if (frame.detection.fired) {
    els.status.textContent =
      "System says: activity detected, nothing disclosed (no scope passes both gates)";
    els.status.classList.remove("flagged");
  } else {
    els.status.textContent = "System says: nothing";
    els.status.classList.remove("flagged");
  }
  if (scopeChanged) triggerStatusChange();

  renderRefusal(frame);
}

// the money moment: a scope with enough evidence that the privacy gate
// refuses. wording comes from the engine's own reason text, not invented here
function renderRefusal(frame) {
  const evals = frame.evaluations || [];
  const refused = evals.find((e) => e.statistical_pass && !e.privacy_pass);
  const d = frame.disclosure;

  // :empty hides the box; writing into it is the change role=status announces
  function show(title, text) {
    const head = document.createElement("strong");
    head.textContent = title;
    const body = document.createElement("span");
    body.textContent = text;
    els.refusal.replaceChildren(head, body);
  }

  if (refused) {
    const named = d ? `${d.level} ${d.label}` : "no scope at all";
    // strip the engine's "Rejected: " prefix n trailing punctuation, frame it here
    const reason = refused.reason.replace(/^Rejected:\s*/, "").replace(/[.\s]+$/, "");
    show(
      "Privacy refusal",
      `The system has enough evidence to name ${refused.level} ${refused.label}, ` +
      `but will not: ${reason}. It disclosed ${named} instead.`
    );
    return;
  }

  if (frame.detection.fired && !d) {
    show(
      "Nothing disclosed",
      "Activity was detected, but no scope has both enough evidence and a safe " +
      "population to name, so the system says nothing."
    );
    return;
  }

  els.refusal.replaceChildren();
}

// ---- resolution slider -------------------------------------------------

// The slider walks the candidate scopes from coarsest to finest. It may
// travel up to and including the first scope that FAILED the privacy gate
// (state.wallIdx); dragging further snaps back to it. The engine already
// decided pass/fail -- this only reads frame.evaluations.
function renderResolution(frame) {
  const evals = frame.evaluations || [];
  state.evals = evals;

  if (evals.length === 0) {
    state.wallIdx = -1;
    state.maxResIdx = 0;
    state.resIdx = 0;
    els.resSlider.disabled = true;
    els.resSlider.min = "0";
    els.resSlider.max = "0";
    els.resSlider.value = "0";
    els.resReadout.className = "res-readout";
    els.resReadout.textContent = frame.detection.fired
      ? "Detection fired but no scope had a qualifying report this day."
      : "No candidate scopes. Detection has not fired on this day.";
    return;
  }

  // label the slider ends with the actual scope levels this day offers,
  // coarsest -> finest (the server already orders evaluations that way),
  // instead of the generic "coarsest"/"finest" placeholder shown pre-run
  els.resEndCoarse.textContent = evals[0].level.toLowerCase();
  els.resEndFine.textContent = evals[evals.length - 1].level.toLowerCase();

  state.wallIdx = evals.findIndex((e) => !e.privacy_pass);
  state.maxResIdx = state.wallIdx === -1 ? evals.length - 1 : state.wallIdx;
  const selIdx = evals.findIndex((e) => e.selected);
  state.resIdx = selIdx !== -1 ? selIdx : state.maxResIdx;

  els.resSlider.disabled = false;
  els.resSlider.min = "0";
  els.resSlider.max = String(evals.length - 1);
  els.resSlider.value = String(state.resIdx);
  renderResReadout();
}

function renderResReadout() {
  const e = state.evals[state.resIdx];
  if (!e) return;
  const atWall = state.wallIdx !== -1 && state.resIdx === state.wallIdx;
  els.resReadout.classList.toggle("wall", atWall);

  if (atWall) {
    els.resReadout.textContent =
      `Resolution stops at ${e.level} ${e.label}. ${e.reason}`;
  } else if (e.selected) {
    els.resReadout.textContent =
      `Resolution: ${e.level} ${e.label}. The scope the system disclosed.`;
  } else if (e.eligible) {
    els.resReadout.textContent =
      `Resolution: ${e.level} ${e.label}. Passes both gates; a finer scope was disclosed.`;
  } else {
    els.resReadout.textContent =
      `Resolution: ${e.level} ${e.label}. Passes the privacy gate. ${e.reason}`;
  }
}

function applyResolutionHighlight() {
  const resScope = state.evals[state.resIdx];
  for (const [suiteId, suiteEl] of state.suiteEls) {
    suiteEl.classList.toggle(
      "resolution", Boolean(resScope && scopeCoversSuite(resScope.scope_id, suiteId))
    );
  }
}

els.resSlider.addEventListener("input", () => {
  let v = Number(els.resSlider.value);
  if (v > state.maxResIdx) {
    v = state.maxResIdx;                 // hard stop at the privacy wall
    els.resSlider.value = String(v);
  }
  state.resIdx = v;
  renderResReadout();
  applyResolutionHighlight();
});

// ---- gate table ------------------------------------------------------

function td(text) {
  const el = document.createElement("td");
  el.textContent = text;
  return el;
}

function gateCell(pass, sub) {
  const el = document.createElement("td");
  el.className = "gate-cell";
  const verdict = document.createElement("span");
  verdict.className = pass ? "pass" : "fail";
  verdict.textContent = pass ? "PASS" : "FAIL";
  el.appendChild(verdict);
  if (sub) {
    const note = document.createElement("small");
    note.textContent = sub;
    el.appendChild(note);
  }
  return el;
}

function _verdictSignature(e) {
  return `${e.statistical_pass}|${e.privacy_pass}|${e.selected}`;
}

// prevFrame is only passed for a genuine single forward step (see paintDay);
// rows are always rebuilt fresh either way, so a jump/scrub/screenshot load
// never sees the flash (there is nothing to diff against, prevFrame is null)
function renderGateTable(frame, prevFrame) {
  els.gateDay.textContent = String(frame.day);
  const body = els.gateBody;
  body.innerHTML = "";
  const evals = frame.evaluations || [];

  if (evals.length === 0) {
    const tr = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 6;
    cell.className = "muted";
    cell.textContent =
      "No candidate scopes evaluated" +
      (frame.detection.fired ? "." : " (detection did not fire).");
    tr.appendChild(cell);
    body.appendChild(tr);
    return;
  }

  const prevVerdict = new Map();
  if (prevFrame) {
    for (const e of prevFrame.evaluations || []) prevVerdict.set(e.scope_id, _verdictSignature(e));
  }

  const flashRows = [];
  for (const e of evals) {
    const tr = document.createElement("tr");
    if (e.selected) tr.className = "selected";
    tr.appendChild(td(`${e.level} ${e.label}`));
    tr.appendChild(td(String(e.population)));
    tr.appendChild(td(e.qualifying_band));
    tr.appendChild(gateCell(e.statistical_pass, `needs at least ${e.statistical_threshold}`));
    tr.appendChild(gateCell(e.privacy_pass, ""));
    tr.appendChild(td(e.reason));
    body.appendChild(tr);

    if (prevFrame) {
      const before = prevVerdict.get(e.scope_id);
      if (before !== undefined && before !== _verdictSignature(e)) {
        tr.classList.add("verdict-changed");
        flashRows.push(tr);
      }
    }
  }
  // double rAF: let the browser paint the flash once, THEN remove the class,
  // so the removal (not the arrival) is what transitions -- a fade out, not a snap
  if (flashRows.length) {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        for (const tr of flashRows) tr.classList.remove("verdict-changed");
      });
    });
  }
}

// ---- end-of-run summary -------------------------------------------------

// Built while every day's frame is fetched in startRun's prefetch loop, not
// recomputed from a single day's frame -- "most specific disclosure" and
// "was a finer scope ever refused" are properties of the whole run.
function noteSummaryFrame(summary, n, frame) {
  if (frame.detection.fired && summary.firedDay === null) {
    summary.fired = true;
    summary.firedDay = n;
  }
  const d = frame.disclosure;
  if (d) {
    const rank = LEVEL_RANK[d.level] || 0;
    if (!summary.finest || rank > LEVEL_RANK[summary.finest.level]) {
      summary.finest = d;
      summary.finestDay = n;
    }
  }
  if (!summary.refused) {
    const r = (frame.evaluations || []).find((e) => e.statistical_pass && !e.privacy_pass);
    if (r) {
      summary.refused = true;
      summary.refusedDay = n;
    }
  }
}

function renderRunSummary() {
  const s = state.summary;
  if (!s) return;
  els.sumDetected.textContent = s.fired ? "Yes" : "No";
  els.sumDetectedDay.textContent = s.fired ? String(s.firedDay) : "n/a";
  els.sumDisclosure.textContent = s.finest
    ? `${s.finest.level} ${s.finest.label} (day ${s.finestDay})`
    : "Nothing disclosed";
  els.sumRefused.textContent = s.refused ? "Yes" : "No";
  els.sumRefusedDay.textContent = s.refused ? String(s.refusedDay) : "n/a";
  els.runSummary.hidden = false;
}

// ---- run + playback -----------------------------------------------------

// Both run buttons are disabled and the clicked one relabelled for the
// couple of seconds the fetch takes, so the page never just sits there
// looking inert. Always restored together, win or lose.
function setRunningFeedback(triggerButton) {
  els.run.disabled = true;
  els.runGuided.disabled = true;
  if (triggerButton) triggerButton.textContent = "Running…";
}
function clearRunningFeedback() {
  els.run.disabled = false;
  els.runGuided.disabled = false;
  els.run.textContent = RUN_LABEL;
  els.runGuided.textContent = GUIDED_LABEL;
}

// opts.triggerButton: the button clicked, so its label can say "Running...".
// opts.autoplay (default true): start playback once frames land, same as
// the page-load autoplay -- the ?auto= smoke-test path below passes false
// because it drives its own jump-to-day / play().
async function startRun(opts = {}) {
  const autoplay = opts.autoplay !== false;
  stopTimer();
  setPlaybackEnabled(false);
  setRunningFeedback(opts.triggerButton);
  els.emptyNote && (els.emptyNote.style.display = "none");
  renderSkeleton();
  els.status.textContent = "System says: starting the simulation…";
  els.status.classList.remove("flagged");
  els.refusal.replaceChildren();
  els.resSlider.disabled = true;
  els.resReadout.className = "res-readout";
  els.resReadout.textContent = "Loading";
  els.gateBody.innerHTML = "";
  els.gateDay.textContent = "0";
  els.runSummary.hidden = true;
  state.summary = { fired: false, firedDay: null, finest: null, finestDay: null, refused: false, refusedDay: null };
  // reset the scrubber immediately, not just once frames arrive -- otherwise
  // a disabled slider sits at the previous run's end position while this
  // fetch is still in flight
  els.scrub.value = "0";
  els.dayLabel.textContent = "0";
  els.dayMax.textContent = "0";

  const reporting = Number(els.pReporting.value);
  const body = {
    seed: Number(els.seed.value) || 0,
    days: Math.max(1, Math.min(120, Number(els.days.value) || 30)),
    population: Number(els.pPopulation.value) || 25,
    suite_transmission_probability: Number(els.pTransmission.value),
    reporting_probability_min: reporting,
    reporting_probability_max: reporting,
    detection_window_hours: Number(els.pWindow.value) || 72,
  };
  const qs = new URLSearchParams(location.search);
  for (const key of [
    "suite_transmission_probability", "floor_transmission_probability",
    "building_transmission_probability", "reporting_probability_min",
    "reporting_probability_max", "background_noise_daily_rate", "seed_infections",
    "population", "detection_window_hours",
  ]) {
    if (qs.has(key)) body[key] = Number(qs.get(key));
  }
  if (qs.has("seed")) { body.seed = Number(qs.get("seed")); els.seed.value = body.seed; }
  if (qs.has("days")) { body.days = Number(qs.get("days")); els.days.value = body.days; }
  if (qs.has("population")) els.pPopulation.value = body.population;
  if (qs.has("suite_transmission_probability")) els.pTransmission.value = body.suite_transmission_probability;
  if (qs.has("reporting_probability_min")) els.pReporting.value = body.reporting_probability_min;
  if (qs.has("detection_window_hours")) els.pWindow.value = body.detection_window_hours;
  refreshParamHints();
  els.paramsDirty.hidden = true;
  els.status.textContent = `System says: simulating ${body.days} days…`;

  let meta;
  try {
    const res = await apiFetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error("run failed: " + res.status + " " + (await res.text()));
    meta = await res.json();
  } catch (err) {
    els.plan.classList.remove("loading");
    els.plan.innerHTML = "";
    els.status.textContent = "System says: the simulation could not be started (" + err.message + "). Try again.";
    clearRunningFeedback();
    return;
  }

  state.runId = meta.run_id;
  state.totalDays = meta.days;
  state.frames = new Array(meta.days + 1).fill(null);
  if (meta.disclaimer) els.disclaimer.textContent = meta.disclaimer;
  els.dayMax.textContent = String(meta.days);
  els.scrub.max = String(meta.days);

  buildPlan(meta.layout);

  // Prefetch every day up front so playback is smooth.
  for (let n = 0; n <= meta.days; n++) {
    let res;
    try {
      res = await apiFetch(`/api/run/${state.runId}/day/${n}`);
    } catch (err) {
      els.status.textContent = "System says: the simulation stopped partway through (day " + n + ": " + err.message + "). Try again.";
      clearRunningFeedback();
      return;
    }
    if (!res.ok) {
      els.status.textContent = "System says: the simulation stopped partway through (day " + n + ": HTTP " + res.status + "). Try again.";
      clearRunningFeedback();
      return;
    }
    state.frames[n] = await res.json();
    noteSummaryFrame(state.summary, n, state.frames[n]);
    if (n === 0) paintDay(0);
  }

  setPlaybackEnabled(true);
  clearRunningFeedback();
  paintDay(0);
  renderRunSummary();
  if (autoplay) play();
}

function advance() {
  if (state.currentDay >= state.totalDays) {
    stopTimer();
    return;
  }
  paintDay(state.currentDay + 1, { stepped: true });
}

function play() {
  if (state.timer !== null) return;
  if (state.currentDay >= state.totalDays) paintDay(0);
  const interval = Number(els.speed.value) || 500;
  state.timer = setInterval(advance, interval);
}

// guided example: the exact scenario from docs/demo_video_script.md.
// Shared by the button and the autoplay-on-load below.
function runGuidedScenario() {
  els.seed.value = "4";
  els.days.value = "30";
  els.pPopulation.value = "25";
  els.pTransmission.value = "0.025";
  els.pReporting.value = "0.8";
  els.pWindow.value = "72";
  refreshParamHints();
  return startRun({ triggerButton: els.runGuided });
}

// once the user has touched Run, the guided button, or any Playback
// control, the scheduled autoplay (below) must not start a run on top of
// whatever they are doing
let userActed = false;
function noteUserAction() { userActed = true; }
for (const el of [els.run, els.runGuided, els.play, els.pause, els.step, els.reset]) {
  el.addEventListener("click", noteUserAction);
}
els.scrub.addEventListener("input", noteUserAction);

els.run.addEventListener("click", () => startRun({ triggerButton: els.run }));
els.runGuided.addEventListener("click", () => runGuidedScenario());
els.play.addEventListener("click", play);
els.pause.addEventListener("click", stopTimer);
els.step.addEventListener("click", () => { stopTimer(); advance(); });
els.reset.addEventListener("click", () => { stopTimer(); paintDay(0); });
els.scrub.addEventListener("input", () => { stopTimer(); paintDay(Number(els.scrub.value)); });
els.speed.addEventListener("change", () => {
  if (state.timer !== null) { stopTimer(); play(); }
});

// ---- model parameter controls ---------------------------------------

function refreshParamHints() {
  const perSuite = Number(els.pPopulation.value) || 25;
  els.pPopulationHint.textContent = `6 suites, ${perSuite * 6} people`;
  els.pTransmissionHint.textContent = Number(els.pTransmission.value).toFixed(3);
  els.pReportingHint.textContent = Number(els.pReporting.value).toFixed(2);
}

for (const el of [
  els.pPopulation, els.pTransmission, els.pReporting, els.pWindow, els.seed, els.days,
]) {
  el.addEventListener("input", () => {
    refreshParamHints();
    if (state.runId) els.paramsDirty.hidden = false;
  });
}
refreshParamHints();

// ts keeps the pre-run building drawing in sync w suite size
let preloadTimer = null;
els.pPopulation.addEventListener("input", () => {
  if (state.runId) return;
  clearTimeout(preloadTimer);
  preloadTimer = setTimeout(preloadLayout, 250);
});

// ---- pre-run empty state: draw the building before anything happens ----

function layoutQuery() {
  const qs = new URLSearchParams(location.search);
  const pop = qs.get("population") || els.pPopulation.value;
  return pop ? `?population=${encodeURIComponent(pop)}` : "";
}

async function preloadLayout() {
  if (state.runId) return false;
  try {
    const res = await apiFetch("/api/layout" + layoutQuery());
    if (!res.ok) return false;
    const data = await res.json();
    if (state.runId) return false;            // a real run started meanwhile
    buildPlan(data.layout);
    if (data.params && data.params.total_population) {
      els.planPop.textContent = String(data.params.total_population);
    }
    if (data.disclaimer) els.disclaimer.textContent = data.disclaimer;
    return true;
  } catch (_) {
    const note = document.getElementById("empty-note");
    if (note) note.textContent = "Press Run to draw the building and start an outbreak.";
    return false;
  }
}

// ---- precomputed results panel ---------------------------------------

const SVG_NS = "http://www.w3.org/2000/svg";

function svg(name, attrs, text) {
  const el = document.createElementNS(SVG_NS, name);
  for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, String(v));
  if (text != null) el.textContent = text;
  return el;
}

function renderCostChart(data) {
  const host = document.getElementById("cost-chart");
  host.innerHTML = "";
  const rows = (data.sweeps[data.primary_sweep].rows || []).filter(
    (r) => !r.degenerate && r.disc_delay != null && r.inf_before_disclosure_unbiased != null
  );
  if (rows.length < 2) {
    host.textContent = "not enough sweep points to plot.";
    return;
  }
  rows.sort((a, b) => a.disc_delay - b.disc_delay);

  const W = 760, H = 430, L = 66, Rm = 46, T = 22, Bm = 52;
  const xs = rows.map((r) => r.disc_delay);
  const ys = rows.map((r) => r.inf_before_disclosure_unbiased);
  const xMin = Math.floor(Math.min(...xs)) - 0.5;
  const xMax = Math.ceil(Math.max(...xs)) + 0.5;
  const yMax = Math.max(15, Math.ceil(Math.max(...ys) / 15) * 15);
  const px = (x) => L + ((x - xMin) / (xMax - xMin)) * (W - L - Rm);
  const py = (y) => H - Bm - (y / yMax) * (H - T - Bm);

  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "xMidYMid meet",
    role: "img", "aria-label": "cost of the privacy policy" });

  root.appendChild(svg("line", { class: "axis", x1: L, y1: H - Bm, x2: W - Rm, y2: H - Bm }));
  root.appendChild(svg("line", { class: "axis", x1: L, y1: T, x2: L, y2: H - Bm }));

  for (let x = Math.ceil(xMin); x <= Math.floor(xMax); x += 2) {
    root.appendChild(svg("line", { class: "axis", x1: px(x), y1: H - Bm, x2: px(x), y2: H - Bm + 5 }));
    root.appendChild(svg("text", { class: "tick", x: px(x), y: H - Bm + 18, "text-anchor": "middle" }, String(x)));
  }
  for (let i = 0; i <= 3; i++) {
    const y = (yMax / 3) * i;
    root.appendChild(svg("line", { class: "axis", x1: L - 5, y1: py(y), x2: L, y2: py(y) }));
    root.appendChild(svg("text", { class: "tick", x: L - 9, y: py(y) + 4, "text-anchor": "end" }, String(Math.round(y))));
  }

  const d = rows.map((r, i) => `${i ? "L" : "M"}${px(r.disc_delay).toFixed(1)},${py(r.inf_before_disclosure_unbiased).toFixed(1)}`).join(" ");
  root.appendChild(svg("path", { class: "series", d }));

  rows.forEach((r, i) => {
    const cx = px(r.disc_delay), cy = py(r.inf_before_disclosure_unbiased);
    root.appendChild(svg("circle", { class: "point", cx, cy, r: 4 }));
    const first = i === 0;
    root.appendChild(svg("text", {
      class: "point-label",
      x: cx + (first ? 8 : -8),
      y: cy - 8,
      "text-anchor": first ? "start" : "end",
    }, String(r.value)));
  });

  root.appendChild(svg("text", { x: (L + W - Rm) / 2, y: H - 10, "text-anchor": "middle" },
    "mean days to first disclosure"));
  root.appendChild(svg("text", {
    x: 16, y: (T + H - Bm) / 2, "text-anchor": "middle",
    transform: `rotate(-90 16 ${(T + H - Bm) / 2})`,
  }, "mean infections before disclosure"));

  host.appendChild(root);
  const caption = document.createElement("p");
  caption.className = "results-note";
  caption.textContent =
    `point labels are the ${data.primary_sweep} value; the shipped default is ${rows[0].value}. Independent reporting.`;
  host.appendChild(caption);
}

function _cell(text, cls) {
  const td = document.createElement("td");
  td.textContent = text;
  if (cls) td.className = cls;
  return td;
}

function _fmtScore(v) {
  return v == null ? "n/a" : v.toFixed(2);
}

// precision/recall are fractions of 1 -- also show the percentage so the
// number reads without translating it in your head
function _fmtFraction(v) {
  return v == null ? "n/a" : `${v.toFixed(2)} (${Math.round(v * 100)}%)`;
}

function _detectorRows(scores, cols) {
  // scores: {rules, model}; cols: extra leading cell text per row or null
  const rules = document.createElement("tr");
  const model = document.createElement("tr");
  model.className = "model";
  if (cols) {
    const lead = _cell(cols);
    lead.rowSpan = 2;
    rules.appendChild(lead);
  }
  rules.append(
    _cell("authored rules"),
    _cell(_fmtFraction(scores.rules.precision)),
    _cell(_fmtFraction(scores.rules.recall)),
    _cell(_fmtScore(scores.rules.delay))
  );
  model.append(
    _cell("learned model"),
    _cell(_fmtFraction(scores.model.precision)),
    _cell(_fmtFraction(scores.model.recall)),
    _cell(_fmtScore(scores.model.delay))
  );
  return [rules, model];
}

function renderBenchmark(data) {
  const body = document.getElementById("benchmark-body");
  body.innerHTML = "";
  body.append(..._detectorRows(data.in_distribution, null));
  document.getElementById("benchmark-conclusion").textContent = data.conclusion;
}

function renderRobustness(data) {
  const body = document.getElementById("robustness-body");
  body.innerHTML = "";
  for (const regime of data.cross_regime) {
    body.append(..._detectorRows(regime, regime.label));
  }
  document.getElementById("robustness-conclusion").textContent = data.cross_regime_conclusion;
}

function renderAdversarial(data) {
  document.getElementById("adv-exact").textContent = String(data.exact_one_person_pins);
  document.getElementById("adv-band").textContent = String(data.band_one_person_pins);
  document.getElementById("adv-residual").textContent =
    `Bands remove the one-person pin, not every inference. What the observer still gets: ` +
    `${data.residual}. The direction of the overnight change is still forced on ` +
    `${data.band_direction_known} of ${data.same_scope_pairs.toLocaleString()} day-pairs, ` +
    `and with scope stability off a run names about ${data.wandering_off_mean} distinct ` +
    `groups instead of ${data.wandering_on_mean}.`;
}

// headline numbers, straight from results/*.json, nothing hardcoded
function renderSummary(sweep, bench, adv) {
  const rows = (sweep.sweeps[sweep.primary_sweep].rows || []).filter(
    (r) => !r.degenerate && r.disc_delay != null && r.fire_delay != null
  );
  const shipped = rows[0];
  const items = [];

  if (shipped) {
    const gap = shipped.disc_delay - shipped.fire_delay;
    items.push(
      `Averaged over ${sweep.seeds.toLocaleString()} simulated outbreaks at the default ` +
      `transmission rate, with independent reporting, the detector fires around day ` +
      `${shipped.fire_delay.toFixed(0)} ` +
      `but the privacy rules hold disclosure until about day ${shipped.disc_delay.toFixed(0)}. ` +
      `That gap of roughly ${gap.toFixed(0)} days, during which about ` +
      `${Math.round(shipped.inf_before_disclosure_unbiased)} people are infected, ` +
      `is the measurable cost of the policy.`
    );
  }

  const r = bench.in_distribution.rules, m = bench.in_distribution.model;
  items.push(
    `On held-out runs in the training regime, with independent reporting, the authored ` +
    `rules score precision ` +
    `${r.precision.toFixed(2)}, recall ${r.recall.toFixed(2)}. A learned model is about ` +
    `${(r.delay - m.delay).toFixed(1)} day faster but less precise (${m.precision.toFixed(2)}), ` +
    `so the rules ship and the model stays a benchmark.`
  );

  items.push(
    `In simulated runs with independent reporting, banding the report counts stops an ` +
    `observer pinning an exact one-person overnight ` +
    `change: ${adv.exact_one_person_pins} days against exact counts, ` +
    `${adv.band_one_person_pins} against the bands. On about ` +
    `${adv.band_direction_known} of ${adv.same_scope_pairs.toLocaleString()} same-scope ` +
    `day-pairs the bands still reveal which way the count moved, though not by how much.`
  );

  els.summaryList.innerHTML = "";
  for (const text of items) {
    const li = document.createElement("li");
    li.textContent = text;
    els.summaryList.appendChild(li);
  }
}

async function loadResults() {
  try {
    const [sweep, bench, adv] = await Promise.all([
      apiFetch("/api/results/disclosure_sweep").then((r) => r.json()),
      apiFetch("/api/results/benchmark").then((r) => r.json()),
      apiFetch("/api/results/adversarial").then((r) => r.json()),
    ]);
    renderSummary(sweep, bench, adv);
    renderCostChart(sweep);
    renderBenchmark(bench);
    renderRobustness(bench);
    renderAdversarial(adv);
    return true;
  } catch (err) {
    document.getElementById("cost-chart").textContent =
      "precomputed results unavailable: run python -m scripts.precompute_results";
    els.summaryList.innerHTML = "<li class=\"muted\">Findings unavailable.</li>";
    return false;
  }
}

// Autoplay the guided example once the layout and the precomputed results
// have both loaded, so a visitor sees motion with no click. Does nothing if:
//   - ?auto=... is present (that query param already drives its own
//     playback below -- used for every gallery/verification screenshot),
//   - ?autoplay=0 is present (escape hatch to capture the plain pre-run
//     state deliberately),
//   - loading is slow (over AUTOPLAY_TIMEOUT_MS) or either fetch failed --
//     falls back to the static pre-run state rather than a broken run,
//   - the visitor has already clicked Run, the guided button, or anything
//     in the Playback panel first.
const AUTOPLAY_TIMEOUT_MS = 5000;
async function autoplayOnLoad(layoutReady, resultsReady) {
  const qs = new URLSearchParams(location.search);
  if (qs.get("auto") !== null || qs.get("autoplay") === "0") return;
  let ok = false;
  try {
    ok = await Promise.race([
      Promise.all([layoutReady, resultsReady]).then((results) => results.every(Boolean)),
      new Promise((resolve) => setTimeout(() => resolve(false), AUTOPLAY_TIMEOUT_MS)),
    ]);
  } catch (_) {
    ok = false;
  }
  if (!ok || userActed || state.runId) return;
  runGuidedScenario();
}

const layoutReady = preloadLayout();
const resultsReady = loadResults();
autoplayOnLoad(layoutReady, resultsReady);

// Optional: ?auto runs a seed on load (used for smoke screenshots).
// ?auto=day30 also jumps to the final day. Harmless otherwise.
const auto = new URLSearchParams(location.search).get("auto");
if (auto !== null) {
  startRun({ autoplay: false }).then(() => {
    const m = /^day(\d+)$/.exec(auto);
    if (auto === "end") paintDay(state.totalDays);
    else if (m) paintDay(Math.min(state.totalDays, Number(m[1])));
    else play();
    // ?res=wall drives the slider to its hard stop (for screenshots).
    if (new URLSearchParams(location.search).get("res") === "wall") {
      els.resSlider.value = String(state.maxResIdx);
      els.resSlider.dispatchEvent(new Event("input"));
    }
  });
}
