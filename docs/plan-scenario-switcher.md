# Scenario Switcher Implementation Plan

## Branch
`feat/scenario-switcher-webui`

## Goal
Students open a browser at `http://localhost:5000`, see scenario cards (Scenario 1: Delta+Spark, Scenario 2: Delta+Trino, Scenario 3: Hudi), read descriptions, click **Launch** to run `docker compose`, and watch service health status in real time.

## Architecture (Option A — Host Subprocess)
- **Backend**: FastAPI (`playground_web.py`) running on the host, port `5000`
- **Frontend**: Jinja2 templates + vanilla JS polling for status
- **Execution**: FastAPI calls `subprocess.run(["docker", "compose", ...])` directly. Requires Docker Desktop / `docker compose` on the host PATH.
- **No DinD**: The web UI is a lightweight host process, not a Docker service.

## UX Decisions
| Decision | Chosen |
|---|---|
| Port | `5000` |
| Logs in browser | "Check Status" button sufficient (no live stream) |
| Switching scenarios | "Stop All" button first, then launch new scenario |

## Scenario Definitions
Scenario definitions live in `scenarios.yml` and are loaded by the web UI.

### Scenario 1: Delta Lake + Spark
- **What**: Streaming-first pipeline. Kafka → Spark Structured Streaming → Delta Lake Silver (S3)
- **Architecture**: Architecture A (streaming container, Airflow monitors)
- **Compose**: `docker-compose.yml` + `compose/scenario-1.yml`
- **Env**: `.env.scenario-1`
- **Extra services**: none

### Scenario 2: Delta Lake + Trino
- **What**: Adds Trino SQL engine + Spark Thrift Server for querying Delta tables
- **Architecture**: Architecture A + SQL query layer
- **Compose**: `docker-compose.yml` + `compose/scenario-2.yml`
- **Env**: `.env.scenario-2`
- **Extra services**: `trino`, `spark-thrift`
- **dbt**: Deferred to Phase 2 (custom Airflow image)

### Scenario 3: Hudi + Spark
- **What**: Lakehouse format comparison. Kafka → Spark Streaming → Hudi tables
- **Architecture**: Architecture A
- **Compose**: `docker-compose.yml` + `compose/scenario-3.yml`
- **Env**: `.env.scenario-3`
- **Extra services**: none

## File Changes

### Create
| File | Purpose |
|---|---|
| `.env.scenario-1` | Delta packages, STORAGE_FORMAT=delta |
| `.env.scenario-2` | Delta packages, ENABLE_TRINO=true |
| `.env.scenario-3` | Hudi packages, STORAGE_FORMAT=hudi |
| `compose/scenario-1.yml` | streaming-job with Delta command |
| `compose/scenario-2.yml` | streaming-job + spark-thrift + trino |
| `compose/scenario-3.yml` | streaming-job with Hudi command |
| `playground_web.py` | FastAPI app (scenarios, launch, stop, status) |
| `templates/index.html` | Scenario cards + Stop All + status |
| `templates/logs.html` | Docker compose logs view |
| `scenarios.yml` | Scenario definitions |
| `requirements-web.txt` | fastapi, uvicorn, jinja2, pyyaml |
| `docs/plan-scenario-switcher.md` | This plan |

### Edit
| File | Change |
|---|---|
| `docker-compose.yml` | Add profiles to optional services (kafdrop), remove streaming-job `command` into overrides, keep shared infra |
| `src/streaming/streaming_job.py` | Parameterize format/packages/paths via STORAGE_FORMAT |
| `src/batch/batch_job.py` | Same parameterization |

## Docker Compose Profile Strategy
- **No `core` profile**: Shared infrastructure (kafka, spark, localstack, airflow, postgres, zookeeper) is always started. The base `docker-compose.yml` defines these.
- **Profiles for optional services**: `kafdrop` gets `profiles: ["ui"]`
- **Scenario overrides**: Each `compose/scenario-X.yml` adds the scenario-specific `streaming-job` service and any extra services. This avoids profile conflicts and makes overrides explicit.

## Parameterized Spark Jobs
Both `streaming_job.py` and `batch_job.py` read `STORAGE_FORMAT` env var:
- `"delta"` (default): Delta extensions, Delta packages, Delta paths
- `"hudi"`: No Delta extensions, Hudi packages (`hudi-spark3.5-bundle_2.12`), Hudi table options, Hudi paths

## Phase 1 Explicitly Excludes
- Custom Airflow image
- dbt integration
- Architecture B/C/D DAGs
- KafkaSensor / event-driven

These are Phase 2 triggers after a future `feat/custom-airflow-image` branch.

## Testing Plan
1. `python -m venv .venv && source .venv/bin/activate` (or `. .venv/bin/activate` on Mac/Linux)
2. `pip install -r requirements-web.txt`
3. `python playground_web.py`
4. In browser at `http://localhost:5000`:
   - Click **Scenario 1** → verify services start, events flow to S3
   - Click **Stop All**
   - Click **Scenario 2** → verify Trino UI accessible at `8082`, Spark Thrift on port `10000`
   - Click **Stop All**
   - Click **Scenario 3** → verify Hudi paths in S3

## Future Work
- Phase 2 (Custom Airflow image): Architecture B/C/D, dbt DAGs, Airflow-orchestrated streaming/batch
- Iceberg scenario
- Flink scenario
- Real-time dashboards (Superset/Metabase)
