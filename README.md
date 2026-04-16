# Scalable Clickstream Data Pipeline for User Behavior Analytics

A Dockerized data pipeline for processing and analyzing user clickstream data at scale, designed as a hands-on laboratory for Modern Data Architecture patterns. You can spin it up under **two switchable orchestration architectures** and see, step by step, how events flow from producer to Kafka to Delta Lake and how Airflow supervises and orchestrates the pipeline.

This README is the practical operations guide. For architecture deep-dives see `[docs/architecture-guide.md](docs/architecture-guide.md)`; for the service-by-service reference see `[docs/infrastructure.md](docs/infrastructure.md)`.

---

## Quick reference

### Tech stack


| Component         | Technology                        | Purpose                                         |
| ----------------- | --------------------------------- | ----------------------------------------------- |
| Event Producer    | Python, Faker, kafka-python       | Synthetic clickstream generation                |
| Message Broker    | Apache Kafka + Zookeeper          | Real-time event ingestion                       |
| Stream Processing | Apache Spark Structured Streaming | Kafka → Delta Lake streaming                    |
| Storage Format    | Delta Lake 3.2                    | ACID transactions, time travel                  |
| Object Storage    | LocalStack S3                     | Local AWS S3 emulation                          |
| Batch Processing  | Apache Spark                      | Silver → Gold aggregation                       |
| Orchestration     | Apache Airflow 3.2                | Streaming supervision + batch orchestration (B) |
| SQL Query Engine  | Trino 380                         | Reserved for Scenario 2 (Trino + dbt)           |
| Kafka Web UI      | Kafdrop                           | Topic inspection and message browsing           |
| Database          | PostgreSQL 13                     | Airflow metadata                                |


### Web UIs


| Service                   | URL                                            | Available under        | Credentials       |
| ------------------------- | ---------------------------------------------- | ---------------------- | ----------------- |
| Kafdrop                   | [http://localhost:9033](http://localhost:9033) | A + B                  | —                 |
| Spark Master              | [http://localhost:8080](http://localhost:8080) | A + B                  | —                 |
| Spark Worker              | [http://localhost:8083](http://localhost:8083) | A + B                  | —                 |
| Spark Driver (app UI)     | [http://localhost:4040](http://localhost:4040) | A + B                  | —                 |
| Airflow                   | [http://localhost:8081](http://localhost:8081) | B only                 | No login required |
| Trino                     | [http://localhost:8082](http://localhost:8082) | `--profile trino` only | —                 |


> All three Spark UIs cross-link to each other (worker row on the Master, app-name link on the Master, "Back to Master" buttons). This works because every Spark container is started with `SPARK_PUBLIC_DNS=localhost`, which makes Spark rewrite generated URLs to use `localhost` instead of the container's internal hostname. If you add a new Spark service to `docker-compose.yml`, set the same env var and expose a matching host port to preserve this.

### Project structure

```
.
├── dags/                              Airflow DAGs
│   ├── pipeline_dag.py                  demo pipeline (manual trigger)
│   ├── pipeline_health_dag.py           Kafka + S3 health (every 5 min)
│   ├── clickstream_streaming_dag.py     supervisor: check + restart streaming container (every 5 min)
│   └── clickstream_batch_dag.py         Silver -> Gold spark-submit + verify (manual)
├── src/                               Application code
│   ├── producer/                        Kafka event producer
│   ├── streaming/                       Spark Structured Streaming job
│   └── batch/                           Spark batch aggregation job
├── docker/                            Custom images
│   ├── producer/                        Kafka producer container
│   └── airflow/                         Custom Airflow image (Java 17 + Spark 3.5.3)
├── scripts/                           Init scripts
│   ├── kafka-init/                      Kafka topic creation
│   └── localstack-init/                 S3 bucket creation
├── config/                            Service configurations
│   └── trino/                           Trino server config (deferred)
├── docs/                              Documentation
│   ├── architecture-guide.md            All architectures, trade-offs, switching
│   ├── infrastructure.md                Service-by-service reference
│   ├── data-flow.md                     Medallion layers, inspection commands
│   ├── roadmap.md                       Deferred work and future vision
│   └── troubleshooting.md               Common gotchas and fixes
├── docker-compose.yml                 All service definitions (with profiles)
└── env.sample                         Environment variable reference
```

---

## Architecture overview

Two runnable orchestration architectures share the same data pipeline containers. Pick one via a Docker Compose profile.

- **Architecture A — Streaming-First.** Streaming runs as a long-lived Docker container; batch is triggered manually. No Airflow.
- **Architecture B — Hybrid with Airflow.** Same streaming container, but Airflow supervises it (auto-restart via the Docker Engine API) and orchestrates batch (`spark-submit` from inside Airflow). This is the pattern most production teams use.

For the side-by-side comparison diagram, the profile-to-service mapping, and the explanation of why full Airflow submission is not possible on Spark Standalone (PySpark limitation), see `[docs/architecture-guide.md](docs/architecture-guide.md)`.

---

## Prerequisites

- [Docker Desktop](https://docs.docker.com/get-docker/) (or Docker Engine + Compose v2)
- **8 GB+ RAM** allocated to Docker -- the stack peaks around 5-6 GB under normal load
- A POSIX shell for the copy-paste commands in this guide: macOS/Linux terminal, **WSL2** on Windows, or Git Bash. PowerShell and `cmd.exe` will not run the multi-line blocks verbatim.

Clone and enter the project:

```bash
git clone <this-repo>
cd user-behavior-analytics
```

No Python virtualenv is required -- everything runs in containers.

### Cross-platform support

This project is intended to run on **Linux, macOS (Intel and Apple Silicon), and Windows 10/11**. Concretely:


| Host                        | Supported | How                                                                                                  |
| --------------------------- | --------- | ---------------------------------------------------------------------------------------------------- |
| Linux x86_64 / arm64        | Yes       | Docker Engine + Compose v2                                                                           |
| macOS Intel                 | Yes       | Docker Desktop                                                                                       |
| macOS Apple Silicon (arm64) | Yes       | Docker Desktop — all images resolve to native arm64 variants, no QEMU emulation                      |
| Windows 10/11               | Yes       | Docker Desktop with the **WSL2 backend** (run all commands from inside a WSL2 distro such as Ubuntu) |


All commands below assume a POSIX shell and Compose v2 (`docker compose`, not `docker-compose`).

**Contributor rule:** every image we pull or build must have **multi-arch manifests (amd64 + arm64)**. If a required image is single-arch, we either find an alternative, build our own multi-arch image, or explicitly pin `platform:` and document the emulation cost in `docs/troubleshooting.md`. History: the project originally pinned Kafka/Zookeeper to `linux/amd64`, which made the stack nearly unusable on Apple Silicon because QEMU emulation stretched Kafka startup to 3+ minutes and blew the healthcheck timeouts. The current `confluentinc/cp-*:7.6.1` images are multi-arch, so this is no longer an issue.

### Switching between architectures (important)

Docker Compose's `up` command is additive: if you run `--profile streaming-first up` and then later `--profile airflow-orchestrated up`, that's fine (B is a superset of A, so Compose just adds the `airflow` container). But the other direction (`airflow-orchestrated` → `streaming-first`) silently leaves `airflow` running in the background, because `up` never removes containers by itself.

To guarantee a clean switch between architectures, always run:

```bash
docker compose down --remove-orphans
```

before starting a different profile. The `--remove-orphans` flag tears down any container from this compose project that is not selected by the new profile. It's a ~1-10 second operation that will NOT rebuild any images -- the custom Airflow and producer images stay cached and are reused on the next `up`. The "Start" blocks below prepend this step so copy-paste is always safe.

> **Compose v2 quirk worth knowing.** `docker compose down --remove-orphans` *without* `--profile` flags only reaches services that have no `profiles:` attribute. To tear down everything including profile-scoped containers (`producer`, `streaming-job`, `airflow`, `trino`), use the "Reset state" command below, which explicitly lists every profile.

### Reset state (clean slate)

If something is stuck -- stale checkpoints, topic offsets that don't match Kafka reality, failed DAG runs, a corrupted LocalStack volume, mismatched Delta/Parquet metadata -- wipe everything and start over. This is the demo equivalent of a factory reset:

```bash
docker compose \
  --profile streaming-first \
  --profile airflow-orchestrated \
  --profile trino \
  down --remove-orphans --volumes
```

`--volumes` (`-v`) drops the named volumes (`localstack-volume`, `postgres-db-volume`, `ivy2-cache`). Next `up` will re-create the S3 buckets, the Postgres/Airflow schema, and the Maven cache from scratch. Image layers stay cached, so this completes in ~15 s; the subsequent `up` takes ~1-2 minutes longer than normal because Spark has to resolve Maven coordinates into the fresh `ivy2-cache` again.

Do NOT use this on a system that holds data you care about. For this project, there is no such data -- the producer generates synthetic events.

---

## Architecture A — Streaming-First

### Start

```bash
docker compose down --remove-orphans
docker compose --profile streaming-first up -d
```

This brings up the core infrastructure (Zookeeper, Kafka, Kafdrop, Spark master/worker, LocalStack, Postgres, `ivy2-cache-init`) plus the pipeline workers (`producer`, `streaming-job`). First-time startup downloads Maven dependencies for Spark (~200 MB into the `ivy2-cache` volume) and can take 3-5 minutes on a warm Docker Desktop. Subsequent starts are fast.

**You don't need to start anything manually.** The `producer` container begins emitting synthetic clickstream events to Kafka roughly 1 per second as soon as `kafka-init` has created the topics, and `streaming-job` starts consuming them as soon as Spark + LocalStack are ready. Everything from here on is observation.

Wait for healthchecks to settle, then check status:

```bash
docker compose ps
```

All services should show `Up`; the ones with a healthcheck (`kafka`, `localstack`, `postgres`, `zookeeper`) should read `(healthy)`.

### Step-by-step pipeline exploration

Follow these steps from "event arriving in Kafka" all the way to "aggregated rows in the Gold layer". Each step surfaces a different part of the system.

#### 1. Watch events arriving on Kafka via Kafdrop

Kafdrop is the Kafka Web UI. Open [http://localhost:9033](http://localhost:9033). What you see on the landing page is just the cluster summary (topics, brokers) — you have to click into the topic to actually see events. The walk-through below gets you from "is it working?" to seeing the raw JSON bodies.

**A. Click into the topic.** Under **Topics**, click `clickstream-events`. You land on the topic detail page at `http://localhost:9033/topic/clickstream-events`.

**B. Read the partitions table — this is how you know it's working.** You'll see a table with one row per partition (0, 1, 2):


| Column                        | What it means                                                                                                                      |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| **Partition**                 | Partition id. A Kafka topic is split into N independent, ordered logs; here N=3, so events are striped across 3 sub-logs.          |
| **First Offset**              | Oldest retained offset (usually 0 while nothing has been deleted by retention).                                                    |
| **Last Offset**               | Next offset to be written. Grows by ~1 every time the producer writes to this partition.                                           |
| **Size**                      | Number of messages currently in this partition = `Last Offset - First Offset`. **This is the "event count" you were looking for.** |
| **Leader / Preferred Leader** | Broker id serving this partition. `1` for all three, because we run a single broker.                                               |


Refresh the page. The **Last Offset** and **Size** columns should tick up every second or two, with writes spread fairly evenly across the three partitions. That is the direct evidence that events are flowing: producer → Kafka.

> **Quick aside on partitions:** partitions are Kafka's unit of parallelism. With 3 partitions, up to 3 consumers (or 3 Spark tasks) can read from this topic in parallel, and ordering is guaranteed *within* a partition but not across them. For a learning stack, 3 is enough to make parallelism visible without being wasteful.

**C. Browse the raw JSON bodies.** On the topic detail page, click **View Messages** (top right). Pick a partition (e.g. `0`), leave **Offset** at `0` and **Message Count** at the default, then click **View Messages**. You'll see the actual JSON events the producer is emitting — something like:

```json
{"event_id": "…-…-…", "timestamp": "2026-04-16T…", "user_id": "u_1234", "event_type": "product_view", "product_id": "headphones", "device_type": "mobile", …}
```

**D. Sanity-check the dead-letter topic.** Go back to the topic list. `clickstream-errors` should exist but have `Size = 0` on every partition. If it starts growing, the streaming job rejected messages as malformed — check `docker compose logs streaming-job` for parse errors.

**Prefer the CLI?** Two alternatives that show the same information:

```bash
docker compose logs producer --tail 10 --follow

docker exec user-behavior-analytics-kafka-1 \
  kafka-run-class kafka.tools.GetOffsetShell \
    --broker-list localhost:9092 --topic clickstream-events
```

The second command prints one line per partition in the form `clickstream-events:<partition>:<offset>`. Run it twice a few seconds apart; the offsets should grow.

#### 2. See Spark Structured Streaming at work

Spark actually exposes three related UIs; each serves a different purpose:

| UI | URL | What it shows |
| --- | --- | --- |
| **Master** | [http://localhost:8080](http://localhost:8080) | Cluster state: registered workers, running apps, completed apps. Entry point. |
| **Worker** | [http://localhost:8083](http://localhost:8083) | The worker process: running executors on this worker, their logs, RAM usage. |
| **Driver (per-app)** | [http://localhost:4040](http://localhost:4040) | The application's own UI: **Jobs**, **Stages**, **Executors**, and — most interesting for us — the **Structured Streaming** tab with input/processed rows, batch duration, and per-batch offsets. |

Start at the **Master UI** ([http://localhost:8080](http://localhost:8080)). Two sections matter:

- **Workers** — should list one worker with `State = ALIVE`, `Cores = 1 (1 Used)`, and `Memory` showing a non-zero "Used" figure. **If Cores shows `1 (0 Used)`, the streaming driver is not attached to the cluster** — see "Troubleshooting" below. Click the worker row and you'll land on the Worker UI at `http://localhost:8083`.
- **Running Applications** — should list a single app named `ClickstreamStreaming` in state `RUNNING`. Click the app name to reach the Driver UI at `http://localhost:4040`.

> All three UIs cross-link correctly thanks to `SPARK_PUBLIC_DNS=localhost`. If for some reason you get redirected to an internal Docker hostname (`<random-container-id>:<port>`), the env var didn't take effect — restart the affected service.

For raw driver logs:

```bash
docker compose logs streaming-job --tail 20 --follow
```

Each micro-batch log line shows `numInputRows`, `processedRowsPerSecond`, and batch duration.

**Troubleshooting: `ClickstreamStreaming` not listed / `0 Used` cores.** The streaming driver is dead. Check its exit status:

```bash
docker compose ps --all streaming-job
docker compose logs streaming-job --tail 80
```

If it's `Exited`, the `restart: on-failure` policy should already have brought it back once -- so seeing it persistently dead means the failure is non-transient (bad code, bad config, Kafka/S3 unreachable). Fix the underlying cause, then run `docker compose --profile streaming-first up -d streaming-job` to bring it back. If the checkpoint state on S3 is inconsistent (e.g. after resetting Kafka without resetting LocalStack), the cleanest recovery is the "Reset state" procedure below.

#### 3. Confirm data landing on S3 (LocalStack)

```bash
docker compose exec localstack \
  awslocal s3 ls s3://user-behavior-analytics-silver/clickstream/delta/ --recursive
```

You should see three kinds of files:

- `_delta_log/*.json` — the Delta transaction log (this is what makes it a Delta table, not just Parquet)
- `_delta_log/_last_checkpoint` — current checkpoint pointer
- `date=YYYY-MM-DD/part-*.snappy.parquet` — data files partitioned by event date

#### 4. Query the Silver layer with `spark-sql` (Delta Lake direct query)

This is the "before" experience in the Trino + dbt story: you already have a real lakehouse layer and can query it with SQL today, even without Trino. Launch a `spark-sql` REPL inside the master container:

```bash
docker compose exec -it spark-master \
  /opt/spark/bin/spark-sql \
    --master spark://spark-master:7077 \
    --conf spark.driver.extraJavaOptions=-Divy.home=/tmp/ivy2 \
    --conf spark.sql.extensions=io.delta.sql.DeltaSparkSessionExtension \
    --conf spark.sql.catalog.spark_catalog=org.apache.spark.sql.delta.catalog.DeltaCatalog \
    --conf spark.hadoop.fs.s3a.endpoint=http://localstack:4566 \
    --conf spark.hadoop.fs.s3a.access.key=test \
    --conf spark.hadoop.fs.s3a.secret.key=test \
    --conf spark.hadoop.fs.s3a.path.style.access=true \
    --conf spark.hadoop.fs.s3a.connection.ssl.enabled=false \
    --packages io.delta:delta-spark_2.12:3.2.0,org.apache.hadoop:hadoop-aws:3.3.4,com.amazonaws:aws-java-sdk-bundle:1.12.262
```

At the `spark-sql>` prompt:

```sql
-- Peek at the raw events
SELECT * FROM delta.`s3a://user-behavior-analytics-silver/clickstream/delta/` LIMIT 10;

-- Distribution of event types
SELECT event_type, COUNT(*) AS n
FROM delta.`s3a://user-behavior-analytics-silver/clickstream/delta/`
GROUP BY event_type
ORDER BY n DESC;

-- Time travel -- what did the table look like 1 version ago?
DESCRIBE HISTORY delta.`s3a://user-behavior-analytics-silver/clickstream/delta/`;
SELECT COUNT(*) FROM delta.`s3a://user-behavior-analytics-silver/clickstream/delta/` VERSION AS OF 0;
```

Exit with `quit;` (or Ctrl+D). When Scenario 2 (Trino + dbt) ships, the same tables will be queryable via Trino with a proper catalog and dbt models building Gold from Silver.

#### 5. Run the batch aggregation (Silver → Gold)

```bash
docker compose exec spark-master \
  /opt/spark/bin/spark-submit \
    --master spark://spark-master:7077 \
    --conf spark.driver.extraJavaOptions=-Divy.home=/tmp/ivy2 \
    --packages io.delta:delta-spark_2.12:3.2.0,org.apache.hadoop:hadoop-aws:3.3.4,com.amazonaws:aws-java-sdk-bundle:1.12.262 \
    /opt/spark/app/src/batch/batch_job.py
```

This produces two Gold-layer tables:

- `daily_user_activity` — events per user per day
- `product_performance` — views / cart-adds / purchases per product

Verify Gold objects on S3:

```bash
docker compose exec localstack \
  awslocal s3 ls s3://user-behavior-analytics-gold/ --recursive | head
```

Then query the Gold tables with the same `spark-sql` REPL from step 4:

```sql
SELECT * FROM delta.`s3a://user-behavior-analytics-gold/daily_user_activity/` LIMIT 10;
SELECT * FROM delta.`s3a://user-behavior-analytics-gold/product_performance/`  LIMIT 10;
```

### Stop

```bash
docker compose --profile streaming-first down          # stop containers, keep data
docker compose --profile streaming-first down -v       # also drop volumes (clean slate)
```

---

## Architecture B — Hybrid with Airflow

Everything from Architecture A is still true here -- the same `producer` and `streaming-job` containers run the data plane. The difference is that **Airflow is now the operator**: it supervises the streaming container and orchestrates the batch run.

### Start

```bash
docker compose down --remove-orphans
docker compose --profile airflow-orchestrated up -d
```

This adds the `airflow` service on top of the streaming-first stack. First-time startup also builds the custom Airflow image (Java 17 + Spark 3.5.3 copied from the official Spark image), which takes ~2-3 minutes.

Wait for Airflow to come up:

```bash
# Airflow is ready once this command prints the DAGs:
docker compose exec airflow airflow dags list 2>/dev/null | grep clickstream
```

You should see four DAGs: `clickstream_batch`, `clickstream_pipeline`, `clickstream_streaming_supervisor`, `pipeline_health_monitor`.

### Step-by-step pipeline exploration

Steps 1-5 below are identical to Architecture A (event arrives → Kafdrop → Spark UI → S3 → `spark-sql` → batch). The interesting new piece is step 6, where Airflow takes over orchestration.

#### 1. Watch events on Kafdrop

Same as Architecture A step 1 above -- [http://localhost:9033](http://localhost:9033) → `clickstream-events`.

#### 2. See streaming at work in the Spark UI

Same as Architecture A step 2 -- [http://localhost:8080](http://localhost:8080) → `ClickstreamStreaming`.

#### 3. Confirm data on S3

Same as Architecture A step 3.

#### 4. Query the Silver layer with `spark-sql`

Same as Architecture A step 4. The data is identical because the streaming container is the same.

#### 5. Run the batch aggregation — but this time via Airflow

Open [http://localhost:8081](http://localhost:8081). No login is required (SimpleAuthManager is enabled).

- Unpause the `**clickstream_batch**` DAG (toggle in the DAGs table)
- Click the DAG name → **Trigger DAG** (the play button)
- Watch the two tasks run in order: `run_batch_job` (spark-submit executed from inside Airflow) → `verify_gold_layer` (S3 object count check)
- Click `run_batch_job` → **Logs** to see the full `spark-submit` output, including Ivy resolution (which should be instant after the first run thanks to the shared `ivy2-cache` volume)

Verify the Gold data exists exactly as in Architecture A step 5 (via `awslocal s3 ls` or the `spark-sql` REPL).

#### 6. Overview the workflow in Airflow

The real differentiator of Architecture B is **streaming supervision**. Open [http://localhost:8081](http://localhost:8081) and explore these DAGs:

- `**clickstream_streaming_supervisor`** (every 5 min, `max_active_runs=1`). Unpause it. The DAG graph has three tasks:
  - `check_streaming_health` (Python) — calls the Spark Master REST API, raises `RuntimeError` if no streaming app is active
  - `restart_streaming_container` (Bash, trigger_rule=`all_failed`) — only fires when the check fails; uses the Docker Engine API over `/var/run/docker.sock` to restart the streaming-job container
  - `verify_recovery` (Bash, trigger_rule=`all_done`) — waits 90 s and re-checks
  Try the failure-injection drill:
  ```bash
  # kill the streaming job
  docker compose stop streaming-job
  ```
  Wait for the next supervisor run (≤ 5 min, or trigger manually). In the DAG graph you'll see `check_streaming_health` fail, `restart_streaming_container` succeed, and `verify_recovery` pass once the Spark driver re-registers (usually within 30-90 s).
- `**pipeline_health_monitor**` (every 5 min). Watches Kafka (via Kafdrop) and S3. Streaming health is intentionally NOT checked here to avoid duplicating the supervisor DAG.
- `**clickstream_batch**` — used in step 5 above. Good candidate for a cron schedule (`0 * * * *`) in a real deployment.
- `**clickstream_pipeline**` — a demo DAG retained for teaching.

### Stop

```bash
docker compose --profile airflow-orchestrated down
docker compose --profile airflow-orchestrated down -v    # clean slate
```

---

## Reset / clean slate

The `--profile` flag on `down` is optional -- you can always do a global clean:

```bash
docker compose down -v                # removes all volumes (Kafka offsets, Delta tables, Airflow metadata)
docker volume rm user-behavior-analytics_ivy2-cache 2>/dev/null || true
```

After `down -v` the next `up` will re-run all init scripts (Kafka topics, S3 buckets) and re-download Maven JARs.

---

## Further reading

- `[docs/architecture-guide.md](docs/architecture-guide.md)` — A vs B comparison, B-alt (why full Airflow submission is not possible on Spark Standalone), event-driven future, and the profile-to-service mapping.
- `[docs/infrastructure.md](docs/infrastructure.md)` — Service-by-service reference (image, ports, volumes, depends_on, the custom Airflow image, and per-DAG diagrams).
- `[docs/data-flow.md](docs/data-flow.md)` — Medallion layers, write paths, and inspection commands.
- `[docs/troubleshooting.md](docs/troubleshooting.md)` — Ivy cache permissions, Docker socket on Linux hosts, QEMU startup, etc.
- `[docs/roadmap.md](docs/roadmap.md)` — Deferred work (Trino + dbt, Hudi, Redshift sync) and the implementation priority.

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.