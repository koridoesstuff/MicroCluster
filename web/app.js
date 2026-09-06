"use strict";

// MicroCluster outbreak animation. Plain DOM, no framework, no build step.
// Detection and disclosure happen server-side; this file only draws what
// /api/run and /api/run/{id}/day/{n} return.

const els = {
  seed: document.getElementById("seed"),
  days: document.getElementById("days"),
  run: document.getElementById("run"),
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
  gateDay: document.getElementById("gate-day"),
  gateBody: document.getElementById("gate-body"),
};

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
};

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

function paintDay(n) {
  const frame = state.frames[n];
  if (!frame) return;
  state.currentDay = n;

  for (const cell of state.agentCells.values()) {
    cell.className = "agent s-susceptible";
  }
  for (const a of frame.agents) {
    const cell = state.agentCells.get(a.suite + "#" + a.i);
    if (cell) cell.className = "agent s-" + a.state;
  }

  renderResolution(frame);
  renderGateTable(frame);

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

  els.dayLabel.textContent = String(n);
  els.scrub.value = String(n);

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
      : "No candidate scopes — detection has not fired on this day.";
    return;
  }

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
      `Resolution: ${e.level} ${e.label} — the scope the system disclosed.`;
  } else if (e.eligible) {
    els.resReadout.textContent =
      `Resolution: ${e.level} ${e.label} — passes both gates; a finer scope was disclosed.`;
  } else {
    els.resReadout.textContent =
      `Resolution: ${e.level} ${e.label} — passes the privacy gate. ${e.reason}`;
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
  const note = document.createElement("small");
  note.textContent = sub;
  el.append(verdict, note);
  return el;
}

function renderGateTable(frame) {
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

  for (const e of evals) {
    const tr = document.createElement("tr");
    if (e.selected) tr.className = "selected";
    tr.appendChild(td(`${e.level} ${e.label}`));
    tr.appendChild(td(String(e.population)));
    tr.appendChild(td(e.qualifying_band));
    tr.appendChild(gateCell(e.statistical_pass, `need ≥ ${e.statistical_threshold}`));
    const privSub = e.privacy_pass
      ? "within minimum size and share"
      : (!e.min_population_pass ? "population below minimum" : "share of group too large");
    tr.appendChild(gateCell(e.privacy_pass, privSub));
    tr.appendChild(td(e.reason));
    body.appendChild(tr);
  }
}

// ---- run + playback -----------------------------------------------------

async function startRun() {
  stopTimer();
  setPlaybackEnabled(false);
  els.run.disabled = true;
  els.emptyNote && (els.emptyNote.style.display = "none");
  renderSkeleton();
  els.status.textContent = "System says: —";
  els.status.classList.remove("flagged");
  els.resSlider.disabled = true;
  els.resReadout.className = "res-readout";
  els.resReadout.textContent = "Loading…";
  els.gateBody.innerHTML = "";
  els.gateDay.textContent = "–";

  const body = {
    seed: Number(els.seed.value) || 0,
    days: Math.max(1, Math.min(120, Number(els.days.value) || 30)),
  };
  // Optional illustrative overrides via URL, e.g.
  // ?suite_transmission_probability=0.03&reporting_probability_min=0.85
  const qs = new URLSearchParams(location.search);
  for (const key of [
    "suite_transmission_probability", "floor_transmission_probability",
    "building_transmission_probability", "reporting_probability_min",
    "reporting_probability_max", "background_noise_daily_rate", "seed_infections",
  ]) {
    if (qs.has(key)) body[key] = Number(qs.get(key));
  }
  if (qs.has("seed")) { body.seed = Number(qs.get("seed")); els.seed.value = body.seed; }
  if (qs.has("days")) { body.days = Number(qs.get("days")); els.days.value = body.days; }

  let meta;
  try {
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error("run failed: " + res.status + " " + (await res.text()));
    meta = await res.json();
  } catch (err) {
    els.plan.classList.remove("loading");
    els.plan.innerHTML = "";
    els.status.textContent = "Error: " + err.message;
    els.run.disabled = false;
    return;
  }

  state.runId = meta.run_id;
  state.totalDays = meta.days;
  state.frames = new Array(meta.days + 1).fill(null);
  els.disclaimer.textContent = meta.disclaimer;
  els.dayMax.textContent = String(meta.days);
  els.scrub.max = String(meta.days);

  buildPlan(meta.layout);

  // Prefetch every day up front so playback is smooth.
  for (let n = 0; n <= meta.days; n++) {
    const res = await fetch(`/api/run/${state.runId}/day/${n}`);
    if (!res.ok) {
      els.status.textContent = "Error loading day " + n + ": " + res.status;
      els.run.disabled = false;
      return;
    }
    state.frames[n] = await res.json();
    if (n === 0) paintDay(0);
  }

  setPlaybackEnabled(true);
  els.run.disabled = false;
  paintDay(0);
}

function advance() {
  if (state.currentDay >= state.totalDays) {
    stopTimer();
    return;
  }
  paintDay(state.currentDay + 1);
}

function play() {
  if (state.timer !== null) return;
  if (state.currentDay >= state.totalDays) paintDay(0);
  const interval = Number(els.speed.value) || 500;
  state.timer = setInterval(advance, interval);
}

els.run.addEventListener("click", startRun);
els.play.addEventListener("click", play);
els.pause.addEventListener("click", stopTimer);
els.step.addEventListener("click", () => { stopTimer(); advance(); });
els.reset.addEventListener("click", () => { stopTimer(); paintDay(0); });
els.scrub.addEventListener("input", () => { stopTimer(); paintDay(Number(els.scrub.value)); });
els.speed.addEventListener("change", () => {
  if (state.timer !== null) { stopTimer(); play(); }
});

// Optional: ?auto runs a seed on load (used for smoke screenshots).
// ?auto=day30 also jumps to the final day. Harmless otherwise.
const auto = new URLSearchParams(location.search).get("auto");
if (auto !== null) {
  startRun().then(() => {
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
