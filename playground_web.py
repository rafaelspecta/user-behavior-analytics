"""
Data Architecture Playground — Scenario Switcher Web UI

A FastAPI-based launcher for the Docker Compose scenarios.
Students open http://localhost:8084, pick a scenario, and click Launch.

Prerequisites:
  - Docker Desktop with docker compose
  - Python 3.10+ and pip install -r requirements-web.txt

Usage:
  python playground_web.py          # start the server
  python playground_web.py --port 9000  # custom port
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

import uvicorn
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
SCENARIOS_FILE = BASE_DIR / "scenarios.yml"
LAYERS_FILE = BASE_DIR / "layers.yml"
STATE_FILE = BASE_DIR / ".active-scenario"
DEFAULT_PORT = int(os.environ.get("PLAYGROUND_PORT", "8084"))

# ---------------------------------------------------------------------------
# Scenario model
# ---------------------------------------------------------------------------


class ExplorationStep(BaseModel):
    step: int
    title: str
    description: str

class ServiceLink(BaseModel):
    name: str
    url: str
    description: str

class ScenarioModel(BaseModel):
    id: str
    name: str
    description: str
    services_list: List[str] = []
    links: List[ServiceLink] = []
    exploration_steps: List[ExplorationStep] = []
    profiles: List[str]
    compose_files: List[str]
    env_file: str = ""
    services_expected: List[str] = []
    color: str = "#38bdf8"


# ---------------------------------------------------------------------------
# Load scenarios
# ---------------------------------------------------------------------------


def _load_scenarios():
    if not SCENARIOS_FILE.exists():
        return []
    with SCENARIOS_FILE.open() as f:
        data = yaml.safe_load(f)
    return [ScenarioModel(**s) for s in data.get("scenarios", [])]


SCENARIOS: List[ScenarioModel] = _load_scenarios()
active_scenario_id: Optional[str] = None


def _read_state() -> Optional[str]:
    """Read the persisted active scenario ID from disk."""
    if STATE_FILE.exists():
        sid = STATE_FILE.read_text().strip()
        if sid and any(s.id == sid for s in SCENARIOS):
            return sid
    return None


def _write_state(scenario_id: Optional[str]):
    """Persist or clear the active scenario ID."""
    if scenario_id:
        STATE_FILE.write_text(scenario_id)
    elif STATE_FILE.exists():
        STATE_FILE.unlink()

# ---------------------------------------------------------------------------
# Load layers (layer-based scenario explorer)
# ---------------------------------------------------------------------------


def _load_layers():
    if not LAYERS_FILE.exists():
        return {"layers": [], "reference_stacks": []}
    with LAYERS_FILE.open() as f:
        return yaml.safe_load(f)


LAYERS_DATA = _load_layers()

# ---------------------------------------------------------------------------
# Compose helpers
# ---------------------------------------------------------------------------


def _build_cmd(scenario: ScenarioModel, action: str, extra: List[str] = None) -> List[str]:
    """Build docker compose command for a scenario."""
    cmd = ["docker", "compose"]
    for cf in scenario.compose_files:
        cmd += ["-f", cf]
    if scenario.env_file and os.path.exists(scenario.env_file):
        cmd += ["--env-file", scenario.env_file]
    for profile in scenario.profiles:
        cmd += ["--profile", profile]
    cmd += [action]
    if extra:
        cmd += extra
    return cmd


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Data Architecture Playground")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "scenarios": [s.model_dump() for s in SCENARIOS],
        "active_scenario_id": active_scenario_id or "",
    })


@app.get("/layers", response_class=HTMLResponse)
async def layer_view(request: Request):
    return templates.TemplateResponse("layers.html", {
        "request": request,
        "scenarios": [s.model_dump() for s in SCENARIOS],
        "active_scenario_id": active_scenario_id or "",
        "layers": LAYERS_DATA.get("layers", []),
        "reference_stacks": LAYERS_DATA.get("reference_stacks", []),
    })


@app.get("/api/active-scenario")
async def active_scenario():
    """Detect which scenario (if any) is currently running.
    
    Priority:
    1. Persisted state file (.active-scenario) — written on web UI launch
    2. Docker detection — used as fallback. Queries all profiles at once
       and picks the scenario with the most expected services all running.
       Each scenario has a unique service composition — there can be only one best match.
    """
    # 1. Try persisted state first
    persisted = _read_state()
    if persisted:
        scenario = next((s for s in SCENARIOS if s.id == persisted), None)
        if scenario:
            expected = set(scenario.services_expected or [])
            running = _get_all_running_services([scenario])
            if expected and expected <= running:
                return {"scenario_id": persisted, "source": "state_file"}
    
    # 2. Fallback to Docker detection — scan all scenarios with all profiles
    all_running = _get_all_running_services(SCENARIOS)
    best_scenario = None
    best_match = 0
    for scenario in SCENARIOS:
        expected = set(scenario.services_expected or [])
        if expected and expected <= all_running:
            if len(expected) > best_match:
                best_match = len(expected)
                best_scenario = scenario.id
    if best_scenario:
        _write_state(best_scenario)
        return {"scenario_id": best_scenario, "source": "docker_detect"}
    
    return {"scenario_id": None, "source": "none"}


def _get_all_running_services(scenarios: List[ScenarioModel]) -> set:
    """Get all running services using all profiles from all scenarios."""
    cmd = ["docker", "compose"]
    seen_files = set()
    for s in scenarios:
        for cf in s.compose_files:
            if cf not in seen_files:
                cmd += ["-f", cf]
                seen_files.add(cf)
    seen_profiles = set()
    for s in scenarios:
        for p in s.profiles:
            if p not in seen_profiles:
                cmd += ["--profile", p]
                seen_profiles.add(p)
    cmd += ["ps", "--format", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(BASE_DIR))
    running = set()
    if result.returncode != 0 or not result.stdout.strip():
        return running
    for line in result.stdout.strip().split("\n"):
        try:
            entry = json.loads(line)
            if entry.get("State") == "running":
                running.add(entry.get("Service", ""))
        except json.JSONDecodeError:
            continue
    return running


@app.post("/api/scenarios/{scenario_id}/start")
async def start_scenario(scenario_id: str):
    global active_scenario_id
    scenario = next((s for s in SCENARIOS if s.id == scenario_id), None)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    # Stop any running scenario first
    if active_scenario_id and active_scenario_id != scenario_id:
        old = next((s for s in SCENARIOS if s.id == active_scenario_id), None)
        if old:
            subprocess.run(_build_cmd(old, "down"), capture_output=True, cwd=str(BASE_DIR))

    cmd = _build_cmd(scenario, "up", ["-d"])
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(BASE_DIR))
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail={"stderr": result.stderr, "cmd": cmd})

    active_scenario_id = scenario_id
    _write_state(scenario_id)
    return {"status": "started", "scenario_id": scenario_id, "cmd": cmd}


@app.post("/api/scenarios/{scenario_id}/stop")
async def stop_scenario(scenario_id: str):
    global active_scenario_id
    scenario = next((s for s in SCENARIOS if s.id == scenario_id), None)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    cmd = _build_cmd(scenario, "down")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(BASE_DIR))
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail={"stderr": result.stderr, "cmd": cmd})

    if active_scenario_id == scenario_id:
        active_scenario_id = None
        _write_state(None)
    return {"status": "stopped", "scenario_id": scenario_id}


@app.post("/api/stop-all")
async def stop_all():
    global active_scenario_id
    for scenario in SCENARIOS:
        subprocess.run(_build_cmd(scenario, "down"), capture_output=True, cwd=str(BASE_DIR))
    active_scenario_id = None
    _write_state(None)
    return {"status": "stopped_all"}


@app.get("/api/scenarios/{scenario_id}/status")
async def status(scenario_id: str):
    scenario = next((s for s in SCENARIOS if s.id == scenario_id), None)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    cmd = _build_cmd(scenario, "ps", ["--format", "json"])
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(BASE_DIR))

    services = {}
    if result.returncode == 0 and result.stdout.strip():
        for line in result.stdout.strip().split("\n"):
            try:
                entry = json.loads(line)
                services[entry.get("Service", "unknown")] = {
                    "state": entry.get("State", "unknown"),
                    "status": entry.get("Status", ""),
                    "health": entry.get("Health", ""),
                }
            except json.JSONDecodeError:
                continue

    expected = set(scenario.services_expected or [])
    missing = sorted(expected - set(services.keys()))
    healthy = bool(services) and not missing and all(
        s.get("state") == "running" for s in services.values()
    )

    return {
        "scenario_id": scenario_id,
        "active": active_scenario_id == scenario_id,
        "services": services,
        "services_running": len(services),
        "services_expected": len(expected),
        "missing_services": missing,
        "healthy": healthy,
    }


@app.get("/api/scenarios/{scenario_id}/logs")
async def logs(scenario_id: str, tail: int = 100):
    scenario = next((s for s in SCENARIOS if s.id == scenario_id), None)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    cmd = _build_cmd(scenario, "logs", ["--tail", str(tail)])
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(BASE_DIR))
    return {"scenario_id": scenario_id, "logs": result.stdout or result.stderr}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = DEFAULT_PORT
    if len(sys.argv) > 1 and sys.argv[1] == "--port" and len(sys.argv) > 2:
        port = int(sys.argv[2])
    uvicorn.run("playground_web:app", host="0.0.0.0", port=port, reload=False)
