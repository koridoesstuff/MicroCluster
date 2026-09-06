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
};

const state = {
  runId: null,
  totalDays: 0,
  frames: [],          // frames[n] = day payload
  currentDay: 0,
  timer: null,
  agentCells: new Map(), // key `${suite}#${i}` -> <div class="agent">
  suiteEls: new Map(),   // suite id -> <div class="suite">
};

const STATES = ["susceptible", "incubating", "symptomatic", "recovered"];

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

  for (const [suiteId, suiteEl] of state.suiteEls) {
    const d = frame.disclosure;
    const hit = d && (d.scope_id === suiteId || String(suiteId).startsWith(d.scope_id + "-"));
    suiteEl.classList.toggle("disclosed", Boolean(hit));
  }

  const c = frame.counts;
  els.counts.textContent =
    `susceptible ${c.susceptible} · incubating ${c.incubating} · ` +
    `symptomatic ${c.symptomatic} · recovered ${c.recovered}`;

  els.dayLabel.textContent = String(n);
  els.scrub.value = String(n);

  const d = frame.disclosure;
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

// ---- run + playback -----------------------------------------------------

async function startRun() {
  stopTimer();
  setPlaybackEnabled(false);
  els.run.disabled = true;
  els.emptyNote && (els.emptyNote.style.display = "none");
  renderSkeleton();
  els.status.textContent = "System says: —";
  els.status.classList.remove("flagged");

  const body = {
    seed: Number(els.seed.value) || 0,
    days: Math.max(1, Math.min(120, Number(els.days.value) || 30)),
  };

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
  });
}
