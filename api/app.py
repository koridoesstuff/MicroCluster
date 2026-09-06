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

import uuid
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
from simulation.contact import suite_ancestor_ids
from simulation.pipeline import (
    DailyRecord,
    SimulatedReports,
    analyze_report_stream,
    simulate_and_report,
)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

MAX_DAYS = 120
MAX_RUNS_KEPT = 64  # in-memory only; oldest evicted past this

DISCLAIMER = (
    "Illustrative simulation. Every parameter here is a chosen figure, not "
    "measured from real data, and this model does not predict real disease "
    "transmission."
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
    RUNS[run_id] = run
    _RUN_ORDER.append(run_id)
    while len(_RUN_ORDER) > MAX_RUNS_KEPT:
        RUNS.pop(_RUN_ORDER.pop(0), None)


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


@app.post("/api/run")
def start_run(req: RunRequest) -> dict:
    config = req.to_config()
    try:
        simulated = simulate_and_report(seed=req.seed, days=req.days, config=config)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    daily_records = analyze_report_stream(simulated)

    layout, agent_slot = _build_layout_and_slots(simulated)
    params = {
        "suite_transmission_probability": config.suite_transmission_probability,
        "floor_transmission_probability": config.floor_transmission_probability,
        "building_transmission_probability": config.building_transmission_probability,
        "reporting_probability_min": config.reporting_probability_min,
        "reporting_probability_max": config.reporting_probability_max,
        "background_noise_daily_rate": config.background_noise_daily_rate,
        "seed_infections": config.seed_infections,
    }

    run_id = uuid.uuid4().hex[:12]
    _remember(
        run_id,
        StoredRun(
            seed=req.seed,
            days=req.days,
            params=params,
            simulated=simulated,
            daily_records=daily_records,
            agent_slot=agent_slot,
            layout=layout,
        ),
    )
    return {
        "run_id": run_id,
        "seed": req.seed,
        "days": req.days,
        "disclaimer": DISCLAIMER,
        "params": params,
        "layout": layout,
    }


@app.get("/api/run/{run_id}/day/{n}")
def get_day(run_id: str, n: int) -> dict:
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="unknown run id (it may have been evicted; start a new run)")
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
        "first_fired_day": record.first_fired_day,
        "first_disclosed_day": record.first_disclosed_day,
        "disclaimer": DISCLAIMER,
    }


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "runs_in_memory": len(RUNS)}


# The plain web UI. Mounted last so /api/* wins.
if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
