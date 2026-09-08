"""HTTP API: start a run, then read one day at a time.

Endpoints
---------
POST /api/run
    Body (all fields optional except nothing -- every field has a default):
        seed, days, seed_infections,
        suite_transmission_probability, floor_transmission_probability,
        building_transmission_probability,
        reporting_probability_min, reporting_probability_max,
        background_noise_daily_rate
    Returns: { run_id, seed, days, disclaimer, params, layout }

GET /api/run/{run_id}/day/{n}
    Returns the world at day n: every agent's suite, index within that
    suite, and infection state; the day's counts; and the
    detection/disclosure verdict. Nothing else.

The simulation's ground-truth firewall still holds: detection and
disclosure see only anonymous Reports and the ScopeRegistry (built inside
``simulation.pipeline``), never agent state. This module then exposes the
agent states for *rendering* -- the same states the animation paints --
and the engine verdicts, and stops there.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from simulation.config import (
    DEFAULT_RUN_DAYS,
    DEFAULT_SIMULATION_CONFIG,
    SimulationConfig,
)

from microcluster.config import DEFAULT_DETECTION_CONFIG, DetectionConfig

from .bands import band, sanitize_reason
from simulation.contact import suite_ancestor_ids
from simulation.pipeline import (
    DailyRecord,
    SimulatedReports,
    analyze_report_stream,
    simulate_and_report,
)
from simulation.population import StructureSpec

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
RESULT_FILES = ("disclosure_sweep", "benchmark", "adversarial")

MAX_DAYS = 120
MAX_RUNS_KEPT = 64  # in-memory only; oldest evicted past this

MIN_SUITE_SIZE = 21   # StructureSpec rejects agents_per_suite <= MIN_SCOPE_POPULATION (20)
MAX_SUITE_SIZE = 40
MIN_WINDOW_HOURS = 24
MAX_WINDOW_HOURS = 168

DISCLAIMER = (
    "Illustrative simulation. Transmission, reporting, contact and incubation values "
    "are chosen for demonstration, not measured from any real population. This predicts "
    "nothing about any real building, and no one is diagnosed or treated by this tool."
)


# ---------------------------------------------------------------------------
# In-memory run store
# ---------------------------------------------------------------------------


@dataclass
class StoredRun:
    seed: int
    days: int
    params: dict
    simulated: SimulatedReports
    daily_records: list[DailyRecord]
    # agent id -> (suite_id, floor_id, index within suite), computed once.
    agent_slot: dict[str, tuple[str, str, int]]
    layout: dict


RUNS: "dict[str, StoredRun]" = {}
_RUN_ORDER: list[str] = []


def _remember(run_id: str, run: StoredRun) -> None:
    if run_id in RUNS:
        RUNS[run_id] = run
        return
    RUNS[run_id] = run
    _RUN_ORDER.append(run_id)
    while len(_RUN_ORDER) > MAX_RUNS_KEPT:
        RUNS.pop(_RUN_ORDER.pop(0), None)


# run id carries its own params so any process can rebuild the run
# deterministically after a restart or free-tier spin-down. RUNS stays a
# pure cache
def _encode_run_id(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_run_id(run_id: str) -> "dict | None":
    try:
        pad = "=" * (-len(run_id) % 4)
        data = json.loads(base64.urlsafe_b64decode(run_id + pad))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


# results json read once at import, not per request
_RESULTS_CACHE: "dict[str, dict]" = {}
for _name in RESULT_FILES:
    _p = RESULTS_DIR / f"{_name}.json"
    if _p.is_file():
        try:
            _RESULTS_CACHE[_name] = json.loads(_p.read_text())
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


_OVERRIDABLE = (
    "suite_transmission_probability",
    "floor_transmission_probability",
    "building_transmission_probability",
    "reporting_probability_min",
    "reporting_probability_max",
    "background_noise_daily_rate",
)


class RunRequest(BaseModel):
    seed: int = 1
    days: int = Field(default=DEFAULT_RUN_DAYS, ge=1, le=MAX_DAYS)
    seed_infections: int = Field(default=1, ge=0)

    population: int | None = Field(default=None, ge=MIN_SUITE_SIZE, le=MAX_SUITE_SIZE)
    detection_window_hours: int | None = Field(
        default=None, ge=MIN_WINDOW_HOURS, le=MAX_WINDOW_HOURS
    )

    suite_transmission_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    floor_transmission_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    building_transmission_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    reporting_probability_min: float | None = Field(default=None, ge=0.0, le=1.0)
    reporting_probability_max: float | None = Field(default=None, ge=0.0, le=1.0)
    background_noise_daily_rate: float | None = Field(default=None, ge=0.0, le=1.0)

    def to_config(self) -> SimulationConfig:
        base = DEFAULT_SIMULATION_CONFIG
        values = {name: getattr(base, name) for name in _OVERRIDABLE}
        for name in _OVERRIDABLE:
            supplied = getattr(self, name)
            if supplied is not None:
                values[name] = supplied
        values["seed_infections"] = self.seed_infections
        try:
            return SimulationConfig(**values)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def to_spec(self) -> StructureSpec | None:
        if self.population is None:
            return None
        return StructureSpec(agents_per_suite=self.population)

    def to_detection_config(self) -> DetectionConfig:
        if self.detection_window_hours is None:
            return DEFAULT_DETECTION_CONFIG
        return DetectionConfig(detection_window_hours=self.detection_window_hours)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="MicroCluster simulator", version="0.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _no_stale_assets(request, call_next):
    # single-process demo, no CDN: make the browser revalidate every asset
    # so an edited web/ file is never served from a stale cache
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


def _build_layout_and_slots(
    simulated: SimulatedReports,
) -> tuple[dict, dict[str, tuple[str, str, int]]]:
    registry = simulated.simulation.registry

    # Group agents by suite in their stable creation order.
    suite_members: dict[str, list[str]] = {}
    for agent in simulated.simulation.agents:
        suite_members.setdefault(agent.suite_id, []).append(agent.id)

    agent_slot: dict[str, tuple[str, str, int]] = {}
    suite_floor: dict[str, str] = {}
    for suite_id, members in suite_members.items():
        floor_id, _building_id = suite_ancestor_ids(registry, suite_id)
        suite_floor[suite_id] = floor_id
        for index, agent_id in enumerate(members):
            agent_slot[agent_id] = (suite_id, floor_id, index)

    floors: dict[str, list[str]] = {}
    for suite_id, floor_id in suite_floor.items():
        floors.setdefault(floor_id, []).append(suite_id)

    layout = {
        "floors": [
            {
                "id": floor_id,
                "label": registry.get(floor_id).label if floor_id in registry.scopes else floor_id,
                "suites": [
                    {
                        "id": suite_id,
                        "label": registry.get(suite_id).label,
                        "size": len(suite_members[suite_id]),
                    }
                    for suite_id in sorted(suite_ids)
                ],
            }
            for floor_id, suite_ids in sorted(floors.items())
        ]
    }
    return layout, agent_slot


def _materialize(req: RunRequest) -> StoredRun:
    config = req.to_config()
    detection_config = req.to_detection_config()
    try:
        simulated = simulate_and_report(
            seed=req.seed, days=req.days, spec=req.to_spec(), config=config
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    daily_records = analyze_report_stream(simulated, detection_config=detection_config)

    layout, agent_slot = _build_layout_and_slots(simulated)
    params = {
        "population_per_suite": simulated.simulation.spec.agents_per_suite,
        "total_population": len(simulated.simulation.agents),
        "detection_window_hours": detection_config.detection_window_hours,
        "suite_transmission_probability": config.suite_transmission_probability,
        "floor_transmission_probability": config.floor_transmission_probability,
        "building_transmission_probability": config.building_transmission_probability,
        "reporting_probability_min": config.reporting_probability_min,
        "reporting_probability_max": config.reporting_probability_max,
        "background_noise_daily_rate": config.background_noise_daily_rate,
        "seed_infections": config.seed_infections,
    }
    return StoredRun(
        seed=req.seed,
        days=req.days,
        params=params,
        simulated=simulated,
        daily_records=daily_records,
        agent_slot=agent_slot,
        layout=layout,
    )


@app.post("/api/run")
def start_run(req: RunRequest) -> dict:
    run_id = _encode_run_id(req.model_dump(exclude_none=True))
    run = RUNS.get(run_id) or _materialize(req)
    _remember(run_id, run)
    return {
        "run_id": run_id,
        "seed": req.seed,
        "days": req.days,
        "disclaimer": DISCLAIMER,
        "params": run.params,
        "layout": run.layout,
    }


@app.get("/api/layout")
def get_layout(population: int | None = None) -> dict:
    # pre-run empty state: the building structure before anything happens.
    # 1-day sim just to build the population n registry, no run stored
    fields: dict = {"days": 1}
    if population is not None:
        fields["population"] = population
    try:
        req = RunRequest(**fields)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    run = _materialize(req)
    return {"layout": run.layout, "params": run.params, "disclaimer": DISCLAIMER}


@app.get("/api/run/{run_id}/day/{n}")
def get_day(run_id: str, n: int) -> dict:
    run = RUNS.get(run_id)
    if run is None:
        # cache miss: rebuild from the params baked into the id
        payload = _decode_run_id(run_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="unknown run id (start a new run)")
        try:
            run = _materialize(RunRequest(**payload))
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=404, detail="unknown run id (start a new run)")
        _remember(run_id, run)
    if n < 0 or n > run.days:
        raise HTTPException(status_code=404, detail=f"day {n} out of range 0..{run.days}")

    snapshot = run.simulated.simulation.history[n]
    record = run.daily_records[n]
    registry = run.simulated.simulation.registry

    agents = []
    for agent_snapshot in snapshot.agents:
        suite_id, floor_id, index = run.agent_slot[agent_snapshot.id]
        agents.append(
            {
                "suite": suite_id,
                "floor": floor_id,
                "i": index,
                "state": agent_snapshot.state.value,
            }
        )

    disclosure = None
    if record.disclosed_scope_id is not None:
        scope = registry.get(record.disclosed_scope_id)
        disclosure = {
            "scope_id": scope.id,
            "label": scope.label,
            "level": scope.level.name,
        }

    # The gate table (rule 12), ordered coarsest -> finest so the
    # resolution slider can walk it directly. Exact qualifying counts and
    # the exact report fraction are dropped here and never sent; only the
    # band leaves the server (see api/bands.py).
    evaluations = [
        {
            "scope_id": ev.scope_id,
            "label": ev.scope_label,
            "level": ev.scope_level.name,
            "population": ev.population,
            "qualifying_band": band(ev.qualifying_reports),
            "statistical_threshold": ev.statistical_threshold,
            "statistical_pass": ev.statistical_pass,
            "min_population_pass": ev.min_population_pass,
            "report_fraction_pass": ev.report_fraction_pass,
            "privacy_pass": ev.privacy_pass,
            "eligible": ev.disclosure_eligible,
            "selected": ev.selected,
            "reason": sanitize_reason(ev.disclosure_reason),
        }
        for ev in sorted(
            record.disclosure_evaluations,
            key=lambda e: (int(e.scope_level), -e.population, e.scope_id),
        )
    ]

    return {
        "day": n,
        "counts": {state.value: snapshot.counts[state] for state in snapshot.counts},
        "agents": agents,
        "detection": {
            "fired": record.detection_fired,
            "relative": record.relative_fired,
            "absolute": record.absolute_fired,
        },
        "disclosure": disclosure,
        "evaluations": evaluations,
        "first_fired_day": record.first_fired_day,
        "first_disclosed_day": record.first_disclosed_day,
        "disclaimer": DISCLAIMER,
    }


@app.get("/api/results/{name}")
def get_results(name: str) -> dict:
    if name not in RESULT_FILES:
        raise HTTPException(status_code=404, detail=f"unknown results file: {name!r}")
    if name in _RESULTS_CACHE:
        return _RESULTS_CACHE[name]
    path = RESULTS_DIR / f"{name}.json"
    if not path.is_file():
        raise HTTPException(
            status_code=503,
            detail="results not precomputed; run python -m scripts.precompute_results",
        )
    _RESULTS_CACHE[name] = json.loads(path.read_text())
    return _RESULTS_CACHE[name]


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "runs_in_memory": len(RUNS)}


# The plain web UI. Mounted last so /api/* wins.
if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
