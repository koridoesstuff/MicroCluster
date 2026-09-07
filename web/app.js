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
      const res = await fetch(url, opts);
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
  pPopulation: document.getElementById("p-population"),
  pTransmission: document.getElementById("p-transmission"),
  pReporting: document.getElementById("p-reporting"),
  pWindow: document.getElementById("p-window"),
  pPopulationHint: document.getElementById("p-population-hint"),
  pTransmissionHint: document.getElementById("p-transmission-hint"),
  pReportingHint: document.getElementById("p-reporting-hint"),
  paramsDirty: document.getElementById("params-dirty"),
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
      : "No candidate scopes. Detection has not fired on this day.";
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
    tr.appendChild(gateCell(e.privacy_pass, ""));
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
  els.status.textContent = "System says: loading";
  els.status.classList.remove("flagged");
  els.resSlider.disabled = true;
  els.resReadout.className = "res-readout";
  els.resReadout.textContent = "Loading";
  els.gateBody.innerHTML = "";
  els.gateDay.textContent = "0";

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
    els.status.textContent = "Error: " + err.message;
    els.run.disabled = false;
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
      els.status.textContent = "Error loading day " + n + ": " + err.message;
      els.run.disabled = false;
      return;
    }
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
  caption.textContent = `point labels are the ${data.primary_sweep} value; the shipped default is 5.`;
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
    _cell(_fmtScore(scores.rules.precision)),
    _cell(_fmtScore(scores.rules.recall)),
    _cell(_fmtScore(scores.rules.delay))
  );
  model.append(
    _cell("learned model"),
    _cell(_fmtScore(scores.model.precision)),
    _cell(_fmtScore(scores.model.recall)),
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
    `${data.band_direction_known} of ${data.same_scope_pairs} day-pairs, and with scope ` +
    `stability off a run names about ${data.wandering_off_mean} distinct groups instead of ` +
    `${data.wandering_on_mean}.`;
}

async function loadResults() {
  try {
    const [sweep, bench, adv] = await Promise.all([
      apiFetch("/api/results/disclosure_sweep").then((r) => r.json()),
      apiFetch("/api/results/benchmark").then((r) => r.json()),
      apiFetch("/api/results/adversarial").then((r) => r.json()),
    ]);
    renderCostChart(sweep);
    renderBenchmark(bench);
    renderRobustness(bench);
    renderAdversarial(adv);
  } catch (err) {
    document.getElementById("cost-chart").textContent =
      "precomputed results unavailable: run python -m scripts.precompute_results";
  }
}

loadResults();

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
