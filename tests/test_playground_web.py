"""Tests for playground_web.py — scenario switcher backend.

Run with: python -m pytest tests/test_playground_web.py -v
"""

import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playground_web import (
    app,
    SCENARIOS,
    _build_cmd,
    _read_state,
    _write_state,
    ScenarioModel,
)


import playground_web


BASE_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """FastAPI TestClient for the app."""
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.fixture(autouse=True)
def clean_state():
    """Remove .active-scenario state file before each test."""
    state_file = BASE_DIR / ".active-scenario"
    if state_file.exists():
        state_file.unlink()
    yield
    if state_file.exists():
        state_file.unlink()


# ---------------------------------------------------------------------------
# Scenario validation
# ---------------------------------------------------------------------------


def test_scenarios_yml_is_valid():
    """scenarios.yml parses and every scenario has required fields."""
    with (BASE_DIR / "scenarios.yml").open() as f:
        data = yaml.safe_load(f)

    scenarios = data.get("scenarios", [])
    assert len(scenarios) == 4, f"Expected 4 scenarios, got {len(scenarios)}"

    required = {"id", "name", "description", "profiles", "compose_files", "services_expected"}
    for s in scenarios:
        missing = required - set(s.keys())
        assert not missing, f"Scenario '{s.get('id', 'unknown')}' missing: {missing}"
        assert s["id"].startswith("scenario-"), f"Bad id: {s['id']}"
        assert s["profiles"], f"No profiles for {s['id']}"
        assert s["compose_files"], f"No compose_files for {s['id']}"
        assert s["services_expected"], f"No services_expected for {s['id']}"

        # Validate services_list matches services_expected
        if "services_list" in s:
            assert set(s["services_list"]) == set(s["services_expected"]), \
                f"services_list != services_expected for {s['id']}"

        # Validate exploration steps are sequential
        steps = s.get("exploration_steps", [])
        if steps:
            nums = [st["step"] for st in steps]
            assert nums == list(range(1, len(nums) + 1)), \
                f"Steps not sequential for {s['id']}: {nums}"


def test_no_duplicate_scenario_ids():
    """Scenario IDs must be unique."""
    ids = [s.id for s in SCENARIOS]
    assert len(ids) == len(set(ids)), f"Duplicate scenario IDs: {ids}"


def test_services_expected_no_init_containers():
    """kafka-init and ivy2-cache-init must not appear in services_expected."""
    for s in SCENARIOS:
        assert "kafka-init" not in s.services_expected
        assert "ivy2-cache-init" not in s.services_expected


def test_default_profile_is_streaming_first():
    """At least one scenario must use streaming-first profile."""
    streaming_first_scenarios = [
        s for s in SCENARIOS if "streaming-first" in s.profiles
    ]
    assert streaming_first_scenarios, "No scenarios use streaming-first profile"


def test_airflow_scenario_exists():
    """A scenario with airflow-orchestrated profile must exist."""
    airflow_scenarios = [
        s for s in SCENARIOS if "airflow-orchestrated" in s.profiles
    ]
    assert airflow_scenarios, "No scenario uses airflow-orchestrated profile"
    assert "airflow" in airflow_scenarios[0].services_expected


def test_trino_in_expected_services():
    """Scenario 3 must include trino in services_expected."""
    s = next(s for s in SCENARIOS if s.id == "scenario-3")
    assert "trino" in s.services_expected
    assert "spark-thrift" in s.services_expected


def test_hudi_env_file():
    """Scenario 4 must point to .env.scenario-3 (Hudi env)."""
    s = next(s for s in SCENARIOS if s.id == "scenario-4")
    assert s.env_file == ".env.scenario-3"


# ---------------------------------------------------------------------------
# layers.yml validation
# ---------------------------------------------------------------------------


def test_layers_yml_exists_and_valid():
    """layers.yml must exist and have layers + reference stacks."""
    layers_file = BASE_DIR / "layers.yml"
    assert layers_file.exists(), "layers.yml not found"

    with layers_file.open() as f:
        data = yaml.safe_load(f)

    layers = data.get("layers", [])
    assert len(layers) == 11, f"Expected 11 layers, got {len(layers)}"

    layer_ids = []
    for layer in layers:
        assert "id" in layer, f"Layer missing id: {layer.get('name')}"
        assert "name" in layer, f"Layer missing name: {layer.get('id')}"
        assert "tools" in layer, f"Layer missing tools: {layer.get('name')}"
        layer_ids.append(layer["id"])

        for tool in layer["tools"]:
            assert tool["status"] in ("implemented", "future"), \
                f"Bad status for {tool['name']}: {tool['status']}"

            # Future tools with scenarios listed — shouldn't happen
            if tool["status"] == "future":
                assert not tool.get("scenarios"), \
                    f"Future tool '{tool['name']}' has scenarios set"

    assert len(set(layer_ids)) == len(layer_ids), "Duplicate layer IDs"

    # Reference stacks
    stacks = data.get("reference_stacks", [])
    assert len(stacks) == 3, f"Expected 3 reference stacks, got {len(stacks)}"
    for stack in stacks:
        assert "id" in stack
        assert "name" in stack
        assert "color" in stack
        assert len(stack.get("layers", [])) == 11, \
            f"Stack '{stack['name']}' must cover all 11 layers"


# ---------------------------------------------------------------------------
# Compose command builder
# ---------------------------------------------------------------------------


def test_build_cmd_basic():
    """_build_cmd creates correct docker compose command."""
    scenario = ScenarioModel(
        id="test",
        name="Test",
        description="Test scenario",
        profiles=["streaming-first"],
        compose_files=["docker-compose.yml"],
        services_expected=["kafka"],
    )
    cmd = _build_cmd(scenario, "up", ["-d"])
    assert cmd[0] == "docker"
    assert cmd[1] == "compose"
    assert "-f" in cmd and "docker-compose.yml" in cmd
    assert "--profile" in cmd and "streaming-first" in cmd
    assert "up" in cmd
    assert "-d" in cmd


def test_build_cmd_with_multiple_profiles():
    """_build_cmd handles multiple profiles."""
    scenario = ScenarioModel(
        id="test",
        name="Test",
        description="Test",
        profiles=["streaming-first", "trino"],
        compose_files=["docker-compose.yml", "compose/scenario-2.yml"],
        services_expected=["kafka"],
    )
    cmd = _build_cmd(scenario, "down")
    assert cmd.count("--profile") == 2
    assert cmd.count("-f") == 2


def test_build_cmd_down_remove_orphans():
    """_build_cmd with extra args."""
    scenario = ScenarioModel(
        id="test",
        name="Test",
        description="Test",
        profiles=["streaming-first"],
        compose_files=["docker-compose.yml"],
        services_expected=["kafka"],
    )
    cmd = _build_cmd(scenario, "down", ["--remove-orphans"])
    assert "down" in cmd
    assert "--remove-orphans" in cmd


# ---------------------------------------------------------------------------
# State file persistence
# ---------------------------------------------------------------------------


def test_write_and_read_state():
    """State file write/read round-trip."""
    _write_state("scenario-1")
    assert _read_state() == "scenario-1"
    assert (BASE_DIR / ".active-scenario").exists()


def test_write_none_deletes_state():
    """Writing None removes the state file."""
    _write_state("scenario-1")
    assert _read_state() == "scenario-1"
    _write_state(None)
    assert _read_state() is None
    assert not (BASE_DIR / ".active-scenario").exists()


def test_read_state_invalid_id():
    """Reading an invalid scenario ID returns None."""
    (BASE_DIR / ".active-scenario").write_text("nonexistent")
    assert _read_state() is None


# ---------------------------------------------------------------------------
# API endpoints (with FastAPI TestClient)
# ---------------------------------------------------------------------------


def test_index_returns_html(client):
    """GET / returns HTML with scenario cards."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Data Architecture Playground" in response.text
    assert "Streaming First" in response.text
    assert "Airflow Orchestrated" in response.text


def test_layers_returns_html(client):
    """GET /layers returns HTML with layer table."""
    response = client.get("/layers")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Layer View" in response.text
    assert "Ingestion" in response.text
    assert "Apache Kafka" in response.text


def test_scenario_status_not_found(client):
    """GET /api/scenarios/nonexistent/status returns 404."""
    response = client.get("/api/scenarios/nonexistent/status")
    assert response.status_code == 404


def test_scenario_start_not_found(client):
    """POST start to nonexistent scenario returns 404."""
    response = client.post("/api/scenarios/nonexistent/start")
    assert response.status_code == 404


def test_scenario_stop_not_found(client):
    """POST stop to nonexistent scenario returns 404."""
    response = client.post("/api/scenarios/nonexistent/stop")
    assert response.status_code == 404


def test_active_scenario_endpoint(client, clean_state):
    """GET /api/active-scenario returns valid structure."""
    response = client.get("/api/active-scenario")
    assert response.status_code == 200
    data = response.json()
    assert "scenario_id" in data
    assert "source" in data
    assert data["source"] in ("state_file", "docker_detect", "none")


@patch("playground_web.subprocess.run")
def test_start_returns_command(mock_run, client):
    """POST start returns the docker compose command."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    response = client.post("/api/scenarios/scenario-1/start")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "started"
    assert data["scenario_id"] == "scenario-1"
    assert "cmd" in data
    assert "docker" in data["cmd"][0]

    # Verify state file was written
    assert _read_state() == "scenario-1"


@patch("playground_web.subprocess.run")
def test_start_writes_state(mock_run, client, clean_state):
    """Starting a scenario persists the state file."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    client.post("/api/scenarios/scenario-2/start")
    assert _read_state() == "scenario-2"


@patch("playground_web.subprocess.run")
def test_stop_clears_state(mock_run, client):
    """Stopping a scenario clears the state file."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    _write_state("scenario-1")
    playground_web.active_scenario_id = "scenario-1"
    client.post("/api/scenarios/scenario-1/stop")
    assert _read_state() is None


@patch("playground_web.subprocess.run")
def test_stop_all_clears_state(mock_run, client):
    """Stop All clears the state file."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    _write_state("scenario-1")
    client.post("/api/stop-all")
    assert _read_state() is None


@patch("playground_web.subprocess.run")
def test_switch_scenario_stops_old(mock_run, client):
    """Switching from scenario 1 to 2 stops the old one first."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    _write_state("scenario-1")
    playground_web.active_scenario_id = "scenario-1"

    client.post("/api/scenarios/scenario-2/start")

    # Check that down was called (first call to subprocess.run)
    calls = mock_run.call_args_list
    down_cmds = [c for c in calls if "down" in str(c)]
    up_cmds = [c for c in calls if "up" in str(c)]
    assert down_cmds, "down should have been called on old scenario"
    assert up_cmds, "up should have been called on new scenario"
    assert _read_state() == "scenario-2"
