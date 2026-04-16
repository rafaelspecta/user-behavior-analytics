# Infrastructure

This document describes every Docker service, how they connect, and how they're configured.

## Service Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         INFRASTRUCTURE LAYER                                │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────────────────┐ │
│  │ Zookeeper  │  │  Postgres  │  │ LocalStack │  │        Trino           │ │
│  │  :2181     │  │  (Airflow  │  │ (S3)       │  │  (SQL Query Engine)    │ │
│  │            │  │   metadata)│  │  :4566     │  │        :8082           │ │
│  └────────────┘  └────────────┘  └────────────┘  └────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                           MESSAGING LAYER                                   │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐                             │
│  │   Kafka    │──│ kafka-init │  │  Kafdrop   │                             │
│  │   :9092    │  │ (creates   │  │ (Kafka UI) │                             │
│  │            │  │  topics)   │  │   :9033    │                             │
│  └────────────┘  └────────────┘  └────────────┘                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                         PROCESSING LAYER                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  ┌────────────────┐  │
│  │ spark-master │  │ spark-worker │  │ streaming-job │  │    producer    │  │
│  │    :7077     │  │  (executes   │  │  (Spark app   │  │  (Python app   │  │
│  │    :8080     │  │   tasks)     │  │   on cluster) │  │   on Kafka)    │  │
│  └──────────────┘  └──────────────┘  └───────────────┘  └────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                 ORCHESTRATION LAYER (airflow-orchestrated profile)          │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                           Airflow :8081                              │   │
│  │  ┌──────────────────────┐  ┌─────────────────────────┐               │   │
│  │  │ clickstream_streaming│  │ clickstream_batch       │               │   │
│  │  │ _supervisor          │  │ (manual spark-submit    │               │   │
│  │  │ (check + restart via │  │  Silver -> Gold)        │               │   │
│  │  │  docker socket)      │  └─────────────────────────┘               │   │
│  │  └──────────────────────┘                                            │   │
│  │  ┌──────────────────────┐  ┌──────────────────────────┐              │   │
│  │  │ clickstream_pipeline │  │ pipeline_health_monitor  │              │   │
│  │  │ (demo)               │  │ (Kafka + S3 only)        │              │   │
│  │  └──────────────────────┘  └──────────────────────────┘              │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Services

### Zookeeper

| Property | Value |
| --- | --- |
| Image | `confluentinc/cp-zookeeper:7.0.0` |
| Platform | `linux/amd64` (no ARM64 version available) |
| Port | 2181 |
| Purpose | Kafka cluster coordination |
| Healthcheck | `echo srvr \| nc localhost 2181 \| grep Zookeeper` |
| Notes | Under QEMU emulation on ARM Macs, startup takes 1-2 minutes. `start_period` is set to 120s to accommodate this. |

### Kafka

| Property | Value |
| --- | --- |
| Image | `confluentinc/cp-kafka:7.0.0` |
| Platform | `linux/amd64` (no ARM64 version available) |
| Port | 9092 (external), 29092 (internal Docker network) |
| Purpose | Message broker for clickstream events |
| Healthcheck | `kafka-topics --bootstrap-server localhost:9092 --list` |
| Depends on | Zookeeper (healthy) |

**Listeners:**
- `PLAINTEXT://kafka:29092` — used by services inside the Docker network (producer, streaming-job, Kafdrop)
- `PLAINTEXT_HOST://localhost:9092` — used from the host machine

### kafka-init

| Property | Value |
| --- | --- |
| Image | `confluentinc/cp-kafka:7.0.0` |
| Purpose | One-shot container to create Kafka topics on startup |
| Depends on | Kafka (healthy) |
| Script | `scripts/kafka-init/init-kafka-topics.sh` |
| Restart | `no` (exits after topics are created) |

Creates two topics:
- `clickstream-events` (3 partitions) — main event stream
- `clickstream-errors` (1 partition) — dead-letter queue

### Kafdrop

| Property | Value |
| --- | --- |
| Image | `obsidiandynamics/kafdrop` |
| Port | 9033 (host) → 9000 (container) |
| Purpose | Kafka Web UI for topic inspection and message browsing |
| URL | http://localhost:9033 |
| Depends on | Kafka |

> Port 9033 is used because ports 9000-9002 are commonly occupied by other services (e.g., MinIO, Portainer).

### Spark Master

| Property | Value |
| --- | --- |
| Image | `spark:3.5.3-scala2.12-java17-python3-ubuntu` |
| Ports | 8080 (Web UI), 7077 (cluster manager) |
| Purpose | Spark standalone cluster manager |
| URL | http://localhost:8080 |
| Volumes | `./src` → `/opt/spark/app/src` (read-only), `ivy2-cache` → `/tmp/ivy2` |

### Spark Worker

| Property | Value |
| --- | --- |
| Image | `spark:3.5.3-scala2.12-java17-python3-ubuntu` |
| Purpose | Executes Spark tasks assigned by the master |
| Memory | 1G |
| Cores | 1 |
| Depends on | Spark Master |
| Volumes | Same as Spark Master |

### streaming-job

| Property | Value |
| --- | --- |
| Image | `spark:3.5.3-scala2.12-java17-python3-ubuntu` |
| Purpose | Runs Spark Structured Streaming: Kafka → Delta Lake |
| Profiles | `streaming-first`, `airflow-orchestrated` (runs under both) |
| Depends on | Kafka (healthy), LocalStack (healthy), Spark Master (started), ivy2-cache-init (completed) |
| Volumes | `./src` → `/opt/spark/app/src` (read-only), `ivy2-cache` → `/tmp/ivy2` |

**Startup sequence:**
1. Waits for LocalStack init scripts to complete (polls `/_localstack/init/ready`)
2. Runs `spark-submit --master spark://spark-master:7077` with all Maven packages
3. Downloads Maven dependencies to ivy2-cache volume (first start takes 1-2 minutes)
4. Connects to Kafka, starts consuming from `clickstream-events`
5. Writes Delta Lake files to `s3a://user-behavior-analytics-silver/clickstream/delta`

**Environment variables:**
- `KAFKA_BOOTSTRAP_SERVERS=kafka:29092`
- `S3_ENDPOINT=http://localstack:4566`
- `AWS_ACCESS_KEY_ID=test`
- `AWS_SECRET_ACCESS_KEY=test`

### Producer

| Property | Value |
| --- | --- |
| Image | Custom (`docker/producer/Dockerfile`: Python 3.11-slim + kafka-python + faker) |
| Purpose | Generates synthetic clickstream events and sends to Kafka |
| Profiles | `streaming-first`, `airflow-orchestrated` (runs under both) |
| Depends on | Kafka (healthy) |
| Restart | `on-failure` |
| Volumes | `./src/producer` → `/app` (read-only) |

**Environment variables:**
- `KAFKA_BOOTSTRAP_SERVERS=kafka:29092`
- `PYTHONUNBUFFERED=1` (ensures logs are visible immediately)
- `EVENT_INTERVAL=1.0` (seconds between events, configurable)

### Airflow

| Property | Value |
| --- | --- |
| Image | Custom build from `docker/airflow/Dockerfile` (based on `apache/airflow:3.2.0`) |
| Port | 8081 (host) → 8080 (container) |
| Purpose | Supervises streaming container and orchestrates batch (Architecture B) |
| URL | http://localhost:8081 |
| Profile | `airflow-orchestrated` |
| Authentication | None required (`SimpleAuthManager` with all-admins mode) |
| Executor | LocalExecutor (backed by PostgreSQL) |
| Restart | `unless-stopped` (supervision DAG depends on Airflow staying alive) |
| Health endpoint | `http://localhost:8081/api/v2/monitor/health` |
| Depends on | PostgreSQL (healthy), Kafka (healthy), Spark Master (started), LocalStack (healthy), ivy2-cache-init (completed) |

**Custom image contents** (see [`docker/airflow/Dockerfile`](../docker/airflow/Dockerfile)):

- OpenJDK 17 (matches the Spark cluster image).
- Apache Spark 3.5.3, copied via multi-stage build from `spark:3.5.3-scala2.12-java17-python3-ubuntu` -- guarantees version parity and avoids flaky downloads from `archive.apache.org`.
- Python packages: `kafka-python`, `faker`, `python-dotenv`, `apache-airflow-providers-apache-spark`.
- `airflow` user (uid 50000) added to a `docker` group so the supervision DAG can talk to `/var/run/docker.sock`.
- `/tmp/ivy2` pre-created with 777 perms so the shared `ivy2-cache` volume is writable by uid 50000.

**Volumes:**
- `./dags` → `/opt/airflow/dags` (DAG definitions)
- `./src` → `/opt/airflow/dags/src` (source code, accessible from DAGs)
- `./dbt` → `/opt/airflow/dags/dbt` (dbt project, reserved for Scenario 2)
- `ivy2-cache` → `/tmp/ivy2` (shared Maven cache -- avoids ~200MB re-downloads per batch run)
- `/var/run/docker.sock` → `/var/run/docker.sock` (used by supervision DAG to restart the streaming-job container)

**Extra environment variables** (set on the service in addition to the Airflow core vars):

- `KAFKA_BOOTSTRAP_SERVERS=kafka:29092`
- `S3_ENDPOINT=http://localstack:4566`
- `AWS_ACCESS_KEY_ID=test` / `AWS_SECRET_ACCESS_KEY=test`
- `AIRFLOW_CONN_SPARK_DEFAULT=spark://spark-master:7077`

**DAGs:**

- [`clickstream_streaming_supervisor`](../dags/clickstream_streaming_dag.py) -- every 5 min, `max_active_runs=1`. Checks the Spark Master REST API for an active streaming application; if missing, restarts the `streaming-job` container via the Docker Engine API and waits 90s before reporting recovery status.

  ```mermaid
  graph LR
      CH["check_streaming_health (PythonOperator)"] -->|"FAILED: app not found"| RS["restart_streaming_container (BashOperator, ALL_FAILED)"]
      RS --> VR["verify_recovery (BashOperator, ALL_DONE, sleep 90s)"]
      CH -->|"SUCCESS: app is alive"| VR
  ```

- [`clickstream_batch`](../dags/clickstream_batch_dag.py) -- manual trigger. Runs `spark-submit` against the Spark Standalone cluster to aggregate Silver → Gold, then verifies Gold-layer objects exist on S3.

  ```mermaid
  graph LR
      BJ["run_batch_job (BashOperator) spark-submit batch_job.py"] --> VG["verify_gold_layer (BashOperator) check S3 objects"]
  ```

- [`pipeline_health_monitor`](../dags/pipeline_health_dag.py) -- every 5 min. Watches Kafka and S3. **Spark streaming health is no longer checked here** -- that responsibility lives in the supervisor DAG so the two DAGs do not duplicate work on the same schedule.
- [`clickstream_pipeline`](../dags/pipeline_dag.py) -- demo DAG (manual trigger) kept for teaching value.

> Airflow is part of **Architecture B (Hybrid)**. In Architecture A (`--profile streaming-first`) the Airflow service is not started.

### PostgreSQL

| Property | Value |
| --- | --- |
| Image | `postgres:13` |
| Port | 5432 (internal only, not exposed to host) |
| Purpose | Airflow metadata database |
| Credentials | airflow / airflow |
| Volume | `postgres-db-volume` |
| Healthcheck | `pg_isready -U airflow` |

### Trino

| Property | Value |
| --- | --- |
| Image | `trinodb/trino:380` |
| Port | 8082 (host) → 8080 (container) |
| Purpose | SQL query engine (deferred — no catalog configured) |
| Profile | `trino` (opt-in; not started by default) |
| URL | http://localhost:8082 |
| Volumes | `./config/trino` → `/etc/trino` |

> Trino is reserved for Scenario 2 (Trino + dbt). It lives behind its own profile so it does not consume resources when you only want to play with orchestration. See [roadmap.md](roadmap.md) for the Scenario 2 spec. To try it: `docker compose --profile trino up -d trino`.

### LocalStack

| Property | Value |
| --- | --- |
| Image | `localstack/localstack:3.8` |
| Ports | 4566 (gateway), 4510-4559 (external services) |
| Purpose | Local AWS S3 (and Redshift) emulation |
| Services | `s3`, `redshift` |
| Healthcheck | `curl -sf http://localhost:4566/_localstack/health \| grep '"s3"'` |

**Init scripts:**
- `scripts/localstack-init/init-s3-buckets.sh` is mounted at `/etc/localstack/init/ready.d/`
- Creates `user-behavior-analytics-silver` and `user-behavior-analytics-gold` buckets on startup
- The script **must have execute permissions** on the host (`chmod +x`)

## Startup Dependencies

```mermaid
graph TD
    ZK[Zookeeper] -->|healthy| KA[Kafka]
    KA -->|healthy| KI[kafka-init]
    KA -->|started| KD[Kafdrop]
    KA -->|healthy| PR[Producer]
    KA -->|healthy| SJ[streaming-job]
    KA -->|healthy| AF[Airflow]

    IVY[ivy2-cache-init] -->|completed| SM[Spark Master]
    IVY -->|completed| SW[Spark Worker]
    IVY -->|completed| SJ
    IVY -->|completed| AF

    SM -->|started| SW
    SM -->|started| SJ
    SM -->|started| AF

    LS[LocalStack] -->|healthy| SJ
    LS -->|healthy| AF

    PG[PostgreSQL] -->|healthy| AF
```

The `ivy2-cache-init` service is a one-shot helper (`busybox:1.36`) that `chmod`s the shared `/tmp/ivy2` volume to 777 so every Ivy-using container (uid 185 for Spark, uid 50000 for Airflow) can read and write. See [troubleshooting.md](troubleshooting.md) for the historical permission issue it now resolves automatically.

## Volumes

| Volume | Mounted To | Purpose |
| --- | --- | --- |
| `postgres-db-volume` | PostgreSQL `/var/lib/postgresql/data` | Airflow metadata persistence |
| `localstack-volume` | LocalStack `/var/lib/localstack` | S3 bucket data (Delta Lake tables) |
| `ivy2-cache` | Spark containers `/tmp/ivy2` | Maven dependency cache (avoids re-downloading JARs on restart) |

## Network

All services are on the default Docker Compose bridge network (`user-behavior-analytics_default`). Services reference each other by service name (e.g., `kafka:29092`, `spark-master:7077`, `localstack:4566`).

## Web UIs

| Service | URL | Purpose |
| --- | --- | --- |
| Spark Master | http://localhost:8080 | Cluster status, running/completed applications, worker details |
| Airflow | http://localhost:8081 | DAG management, task logs, trigger runs (no login needed) |
| Trino | http://localhost:8082 | SQL query interface (no catalog configured yet) |
| Kafdrop | http://localhost:9033 | Kafka topic inspection, message browsing, partition details |
| LocalStack | http://localhost:4566 | AWS API endpoint (use with `aws --endpoint-url=http://localhost:4566 s3 ls`) |

## Environment Variable Reference

See `env.sample` in the project root for all configurable environment variables with documentation.
