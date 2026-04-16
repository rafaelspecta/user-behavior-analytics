# Scalable Clickstream Data Pipeline for User Behavior Analytics

A Dockerized data pipeline for processing and analyzing user clickstream data at scale, designed as a hands-on laboratory for Modern Data Architecture patterns. You can spin it up under **two switchable orchestration architectures** and see, step by step, how events flow from producer to Kafka to Delta Lake and how Airflow supervises and orchestrates the pipeline.

This README is the practical operations guide. For architecture deep-dives see [`docs/architecture-guide.md`](docs/architecture-guide.md); for the service-by-service reference see [`docs/infrastructure.md`](docs/infrastructure.md).

---

## Quick reference

### Tech stack


| Component         | Technology                        | Purpose                                           |
| ----------------- | --------------------------------- | ------------------------------------------------- |
| Event Producer    | Python, Faker, kafka-python       | Synthetic clickstream generation                  |
| Message Broker    | Apache Kafka + Zookeeper          | Real-time event ingestion                         |
| Stream Processing | Apache Spark Structured Streaming | Kafka → Delta Lake streaming                      |
| Storage Format    | Delta Lake 3.2                    | ACID transactions, time travel                    |
| Object Storage    | LocalStack S3                     | Local AWS S3 emulation                            |
| Batch Processing  | Apache Spark                      | Silver → Gold aggregation                         |
| Orchestration     | Apache Airflow 3.2                | Streaming supervision + batch orchestration (B)   |
| SQL Query Engine  | Trino 380                         | Reserved for Scenario 2 (Trino + dbt)             |
| Kafka Web UI      | Kafdrop                           | Topic inspection and message browsing             |
| Database          | PostgreSQL 13                     | Airflow metadata                                  |


### Web UIs


| Service      | URL                                            | Available under       | Credentials       |
| ------------ | ---------------------------------------------- | --------------------- | ----------------- |
| Kafdrop      | [http://localhost:9033](http://localhost:9033) | A + B                 | —                 |
| Spark Master | [http://localhost:8080](http://localhost:8080) | A + B                 | —                 |
| Airflow      | [http://localhost:8081](http://localhost:8081) | B only                | No login required |
| Trino        | [http://localhost:8082](http://localhost:8082) | `--profile trino` only | —                |


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

For the side-by-side comparison diagram, the profile-to-service mapping, and the explanation of why full Airflow submission is not possible on Spark Standalone (PySpark limitation), see [`docs/architecture-guide.md`](docs/architecture-guide.md).

---

## Prerequisites

- [Docker Desktop](https://docs.docker.com/get-docker/) (or Docker Engine + Compose v2)
- **8 GB+ RAM** allocated to Docker -- the stack peaks around 5-6 GB under normal load
- **Apple Silicon note:** the Confluent Kafka/Zookeeper images run under amd64 emulation via QEMU. Initial startup can take 2-3 minutes.

Clone and enter the project:

```bash
git clone <this-repo>
cd user-behavior-analytics
```

No Python virtualenv is required -- everything runs in containers.

---

## Architecture A — Streaming-First

### Start

```bash
docker compose --profile streaming-first up -d
```

This brings up the core infrastructure (Zookeeper, Kafka, Kafdrop, Spark master/worker, LocalStack, Postgres, `ivy2-cache-init`) plus the pipeline workers (`producer`, `streaming-job`). First-time startup downloads Maven dependencies for Spark (~200 MB into the `ivy2-cache` volume) and can take 3-5 minutes on a warm Docker Desktop. Subsequent starts are fast.

Wait for healthchecks to settle, then check status:

```bash
docker compose ps
```

All services should show `Up`; the ones with a healthcheck (`kafka`, `localstack`, `postgres`, `zookeeper`) should read `(healthy)`.

### Step-by-step pipeline exploration

Follow these steps from "event arriving in Kafka" all the way to "aggregated rows in the Gold layer". Each step surfaces a different part of the system.

#### 1. Watch events arriving on Kafka via Kafdrop

Open [http://localhost:9033](http://localhost:9033):

- **Topics** → `clickstream-events` (3 partitions)
- Click the topic, then **View Messages** on any partition to see raw JSON events landing in near-real-time
- The dead-letter topic `clickstream-errors` should stay empty during normal runs

You can also tail the producer container directly:

```bash
docker compose logs producer --tail 10 --follow
```

#### 2. See Spark Structured Streaming at work

Open [http://localhost:8080](http://localhost:8080):

- **Running Applications** lists a single app `ClickstreamStreaming` in `RUNNING` state
- Click the app name to see the driver/executor layout, then **Streaming** tab (once a micro-batch has completed) for input-rate / processed-rows graphs

For raw driver logs:

```bash
docker compose logs streaming-job --tail 20 --follow
```

Each micro-batch log line shows `numInputRows`, `processedRowsPerSecond`, and batch duration.

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

- Unpause the **`clickstream_batch`** DAG (toggle in the DAGs table)
- Click the DAG name → **Trigger DAG** (the play button)
- Watch the two tasks run in order: `run_batch_job` (spark-submit executed from inside Airflow) → `verify_gold_layer` (S3 object count check)
- Click `run_batch_job` → **Logs** to see the full `spark-submit` output, including Ivy resolution (which should be instant after the first run thanks to the shared `ivy2-cache` volume)

Verify the Gold data exists exactly as in Architecture A step 5 (via `awslocal s3 ls` or the `spark-sql` REPL).

#### 6. Overview the workflow in Airflow

The real differentiator of Architecture B is **streaming supervision**. Open [http://localhost:8081](http://localhost:8081) and explore these DAGs:

- **`clickstream_streaming_supervisor`** (every 5 min, `max_active_runs=1`). Unpause it. The DAG graph has three tasks:
  - `check_streaming_health` (Python) — calls the Spark Master REST API, raises `RuntimeError` if no streaming app is active
  - `restart_streaming_container` (Bash, trigger_rule=`all_failed`) — only fires when the check fails; uses the Docker Engine API over `/var/run/docker.sock` to restart the streaming-job container
  - `verify_recovery` (Bash, trigger_rule=`all_done`) — waits 90 s and re-checks

  Try the failure-injection drill:

  ```bash
  # kill the streaming job
  docker compose stop streaming-job
  ```

  Wait for the next supervisor run (≤ 5 min, or trigger manually). In the DAG graph you'll see `check_streaming_health` fail, `restart_streaming_container` succeed, and `verify_recovery` pass once the Spark driver re-registers (usually within 30-90 s).

- **`pipeline_health_monitor`** (every 5 min). Watches Kafka (via Kafdrop) and S3. Streaming health is intentionally NOT checked here to avoid duplicating the supervisor DAG.

- **`clickstream_batch`** — used in step 5 above. Good candidate for a cron schedule (`0 * * * *`) in a real deployment.

- **`clickstream_pipeline`** — a demo DAG retained for teaching.

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

- [`docs/architecture-guide.md`](docs/architecture-guide.md) — A vs B comparison, B-alt (why full Airflow submission is not possible on Spark Standalone), event-driven future, and the profile-to-service mapping.
- [`docs/infrastructure.md`](docs/infrastructure.md) — Service-by-service reference (image, ports, volumes, depends_on, the custom Airflow image, and per-DAG diagrams).
- [`docs/data-flow.md`](docs/data-flow.md) — Medallion layers, write paths, and inspection commands.
- [`docs/troubleshooting.md`](docs/troubleshooting.md) — Ivy cache permissions, Docker socket on Linux hosts, QEMU startup, etc.
- [`docs/roadmap.md`](docs/roadmap.md) — Deferred work (Trino + dbt, Hudi, Redshift sync) and the implementation priority.

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
