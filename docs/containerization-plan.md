# Containerization Plan: User Behavior Analytics Pipeline

---

## Executive Summary

This plan outlines the steps to fully containerize the data pipeline so everything runs automatically through Airflow without requiring manual commands on the host machine.

**Key Discoveries from Review:**
1. Spark Thrift Server is missing (dbt cannot work)
2. Kafka has no healthcheck (init service won't work)
3. SparkSubmitOperator requires Spark binaries in Airflow image

**Critical Issues Found During Plan Review (2024-12-04):**
1. ⚠️ **Python Version Mismatch**: Airflow 2.3.0 default image uses Python 3.7, but dbt-spark 1.4.0 requires Python 3.8+. Fixed by using `apache/airflow:2.3.0-python3.8`.
2. ⚠️ **Cluster Deploy Mode File Access**: `--deploy-mode cluster` runs driver on Spark worker, which needs access to source files. Fixed by mounting `./src` volume to spark-worker.

---

## Version Compatibility Matrix

> **CRITICAL**: These versions must be used together for compatibility. Changing one may break the stack.

### Component Version Chain

```
Spark 3.5.3 (Java 17, Scala 2.12, Hadoop 3.3.4)
    └── Delta Lake 3.2.1 (compatible with Spark 3.5.3)
    └── hadoop-aws 3.3.4 (must match Spark's bundled Hadoop)
        └── aws-java-sdk-bundle 1.12.262 (required by hadoop-aws 3.3.4)
    └── spark-sql-kafka 3.5.3 (must match Spark version)
```

### Why These Specific Versions?

| Component | Version | Reason |
|-----------|---------|--------|
| **Java** | 17 | Spark Docker image uses `java17-ubuntu`; Airflow must match to avoid serialization issues |
| **Spark** | 3.5.3 | Current Docker image version |
| **Scala** | 2.12 | Dictates `_2.12` suffix on all Maven packages |
| **Delta Lake** | 3.2.1 | Delta 3.2.0 was for Spark 3.5.0-3.5.2; 3.2.1 has fixes for 3.5.3. [Source](https://github.com/delta-io/delta/releases) |
| **hadoop-aws** | 3.3.4 | Must match Spark's bundled Hadoop version exactly. [Source](https://stackoverflow.com/questions/77327653) |
| **aws-java-sdk-bundle** | 1.12.262 | Required by hadoop-aws 3.3.4; prevents `NoSuchMethodError` with S3A. [Source](https://hadoop.apache.org/docs/stable/hadoop-aws/tools/hadoop-aws/index.html) |
| **dbt-spark** | 1.4.0 | Requires Python 3.8+; PyHive extras for thrift connection. [Source](https://docs.getdbt.com/faqs/Core/install-python-compatibility) |
| **Airflow Image** | 2.3.0-python3.8 | Must use Python 3.8 tag (not default 3.7) for dbt-spark compatibility. [Source](https://hub.docker.com/r/apache/airflow) |

### References
- [Delta Lake Releases](https://docs.delta.io/latest/releases.html)
- [Hadoop AWS Compatibility](https://stackoverflow.com/questions/77327653/hadoop-common-hadoop-aws-aws-java-sdk-bundle-version-compatibility)
- [Spark Thrift Server Issue](https://stackoverflow.com/questions/79121815/spark-3-5-0-bin-without-hadoop-unable-to-start-thriftserver-sh)
- [dbt-spark Setup](https://docs.getdbt.com/docs/core/connect-data-platform/spark-setup)
- [dbt Python Compatibility](https://docs.getdbt.com/faqs/Core/install-python-compatibility)
- [Airflow Docker Hub Tags](https://hub.docker.com/r/apache/airflow)
- [SPARK_NO_DAEMONIZE for Docker](https://stackoverflow.com/questions/39671117/docker-container-with-apache-spark-in-standalone-cluster-mode)
- [Maven hadoop-aws Dependencies](https://mvnrepository.com/artifact/org.apache.hadoop/hadoop-aws/3.3.4)

**Streaming Strategy:**
- Streaming job will be **orchestrated by Airflow** (not a separate always-on container)
- Use `--deploy-mode cluster --supervise` for non-blocking spark-submit
- For Airflow 2.3.0: Use frequent cron schedule (`*/1 * * * *`) with job-running check
- Future: Upgrade to Airflow 2.4+ for `@continuous` schedule (see [airflow-migration-plan.md](airflow-migration-plan.md))

---

## Desired Architecture

### Architecture Diagram

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
│  │            │  │  topics)   │  │   :9000    │                             │
│  └────────────┘  └────────────┘  └────────────┘                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                         SPARK CLUSTER LAYER                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                       │
│  │ spark-master │  │ spark-worker │  │ spark-thrift │                       │
│  │    :7077     │  │  (executes   │  │   :10000     │                       │
│  │    :8080     │  │   drivers)   │  │  (for dbt)   │                       │
│  └──────────────┘  └──────────────┘  └──────────────┘                       │
│         │                 ▲                                                 │
│         │    ┌────────────┴────────────┐                                    │
│         └───→│  Streaming Job Driver   │←── Submitted by Airflow            │
│              │  (runs on worker,       │    (--deploy-mode cluster)         │
│              │   auto-restarts with    │                                    │
│              │   --supervise flag)     │                                    │
│              └─────────────────────────┘                                    │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                        ORCHESTRATION LAYER                                  │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                           Airflow :8081                              │   │
│  │                                                                      │   │
│  │  ┌─────────────────────────────────────────────────────────────────┐ │   │
│  │  │           DAG: clickstream_streaming (every minute)             │ │   │
│  │  │  ┌──────────────┐    ┌──────────────┐                           │ │   │
│  │  │  │ check_job    │───→│ submit_job   │  (skips if already        │ │   │
│  │  │  │ (is running?)│    │ (if needed)  │   running on cluster)     │ │   │
│  │  │  └──────────────┘    └──────────────┘                           │ │   │
│  │  └─────────────────────────────────────────────────────────────────┘ │   │
│  │                                                                      │   │
│  │  ┌─────────────────────────────────────────────────────────────────┐ │   │
│  │  │           DAG: clickstream_processing (daily)                   │ │   │
│  │  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │ │   │
│  │  │  │   Producer   │→→│  Batch Job   │→→│  dbt tests   │           │ │   │
│  │  │  │   (60 sec)   │  │ (SparkSubmit)│  │              │           │ │   │
│  │  │  └──────────────┘  └──────────────┘  └──────────────┘           │ │   │
│  │  └─────────────────────────────────────────────────────────────────┘ │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                            DATA FLOW                                        │
│                                                                             │
│   Producer ──→ Kafka ──→ Spark Streaming ──→ Delta Lake (S3 Silver)         │
│                          (on cluster)               │                       │
│                                                     ↓                       │
│                              Batch Job ──→ Delta Lake (S3 Gold)             │
│                                                     │                       │
│                                                     ↓                       │
│                              dbt ──→ Spark Thrift ──→ Data Quality Tests    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Services

| Service | Image | Port(s) | Purpose | Status |
|---------|-------|---------|---------|--------|
| **zookeeper** | confluentinc/cp-zookeeper:7.0.0 | 2181 | Kafka coordination | Existing |
| **kafka** | confluentinc/cp-kafka:7.0.0 | 9092 | Message broker | Existing (add healthcheck) |
| **kafka-init** | confluentinc/cp-kafka:7.0.0 | - | Create topics on startup | **NEW** |
| **kafdrop** | obsidiandynamics/kafdrop | 9000 | Kafka Web UI | Existing |
| **spark-master** | spark:3.5.3-scala2.12-java17-ubuntu | 7077, 8080 | Spark cluster manager | Existing |
| **spark-worker** | spark:3.5.3-scala2.12-java17-ubuntu | - | Spark executor + streaming driver | Existing (add volume mount for src/) |
| **spark-thrift** | spark:3.5.3-scala2.12-java17-ubuntu | 10000 | HiveServer2 for dbt | **NEW** |
| **airflow** | Custom (based on apache/airflow:2.3.0-python3.8) | 8081 | Pipeline orchestration | Existing (rebuild with Java 17, Python 3.8) |
| **postgres** | postgres:13 | 5432 | Airflow metadata DB | Existing |
| **trino** | trinodb/trino:380 | 8082 | SQL query engine | Existing |
| **localstack** | localstack/localstack:3.0.0 | 4566 | S3 emulation | Existing (pin version) |

> **Recommendation**: Pin LocalStack to a specific version (e.g., `3.0.0`) instead of using `latest` to avoid unexpected breaking changes.

**Note**: Streaming job runs as a Spark application on the cluster (submitted by Airflow), not as a separate Docker service.

### Data Storage (Medallion Architecture)

| Bucket | Layer | Contents |
|--------|-------|----------|
| `user-behavior-analytics-silver` | Silver | Raw processed events from streaming, checkpoints |
| `user-behavior-analytics-gold` | Gold | Aggregated analytics (daily_user_activity, product_performance) |

### Startup Dependencies

```
zookeeper ──→ kafka ──→ kafka-init
                    ↘ kafdrop

postgres ──→ airflow ──→ (submits streaming job to Spark cluster)

spark-master ──→ spark-worker
             ──→ spark-thrift

localstack (S3 buckets created via init script on startup)
```

### Persistence (Volumes)

| Volume | Service | Purpose |
|--------|---------|---------|
| `postgres-db-volume` | postgres | Airflow metadata, DAG run history, task states |
| `localstack-volume` | localstack | S3 bucket data (Delta Lake tables) |

### External Access Points

| URL | Service | Purpose |
|-----|---------|---------|
| http://localhost:8081 | Airflow | DAG management, task monitoring, logs |
| http://localhost:8080 | Spark Master | Spark cluster UI, job monitoring |
| http://localhost:9000 | Kafdrop | Kafka topic inspection, message viewing |
| http://localhost:8082 | Trino | SQL queries against data |
| http://localhost:4566 | LocalStack | AWS CLI access (`aws --endpoint-url=http://localhost:4566 s3 ls`) |

---

## 1. Architecture Decision: Streaming Job

### Problem
The streaming job (`streaming_job.py`) calls `awaitTermination()` which blocks forever. Airflow expects tasks to complete. We want Airflow to orchestrate ALL data workflows including streaming.

### Solution: Non-Blocking Spark Submit with Cluster Deploy Mode

Based on the article ["Streaming with Continuous Airflow"](https://medium.com/bentego-teknoloji/streaming-with-continuous-airflow-c9a00a12d433), we use:

1. **`--deploy-mode cluster`**: spark-submit exits immediately after submitting the job
2. **`--supervise`**: Spark master auto-restarts the driver if it fails
3. **Airflow DAG**: Checks if job is running before submitting

```bash
spark-submit \
  --master spark://spark-master:7077 \
  --deploy-mode cluster \   # Non-blocking! Driver runs on worker
  --supervise \             # Auto-restart on failure
  /path/to/streaming_job.py
```

### How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                     Airflow DAG (every minute)                  │
│                                                                 │
│  1. Check Spark Master API: Is streaming job running?           │
│     ├── YES → Skip submission, DAG completes                    │
│     └── NO  → Submit job with --deploy-mode cluster             │
│                                                                 │
│  2. spark-submit returns immediately (non-blocking)             │
│  3. DAG run completes                                           │
│  4. Next DAG run in 1 minute checks again                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Spark Cluster                               │
│                                                                 │
│  - Driver runs on spark-worker (not Airflow container)          │
│  - --supervise flag: Master restarts driver if it crashes       │
│  - awaitTermination() keeps driver alive (desired behavior)     │
│  - Checkpointing enables restart from last position             │
└─────────────────────────────────────────────────────────────────┘
```

### Benefits

| Benefit | Description |
|---------|-------------|
| **Visibility** | Streaming job visible in Airflow UI |
| **Auto-restart** | `--supervise` + Airflow DAG ensures job always runs |
| **Monitoring** | Airflow alerts if submission fails |
| **Single orchestrator** | All workflows managed by Airflow |
| **Checkpointing** | Kafka offsets preserved across restarts |

### Airflow Version Consideration

| Airflow Version | Schedule | Notes |
|-----------------|----------|-------|
| **2.3.0** (current) | `*/1 * * * *` (every minute) | Use ShortCircuitOperator to skip if running |
| **2.4+** (future) | `@continuous` | Native continuous scheduling, see [airflow-migration-plan.md](airflow-migration-plan.md) |

---

## 2. New Services Required

### 2.1 Kafka Init Service
**Purpose**: Auto-create Kafka topics on startup

> **Pattern**: Uses mounted init script (same pattern as LocalStack's `scripts/localstack-init/init-s3-buckets.sh`)

**File**: `scripts/kafka-init/init-kafka-topics.sh`
```bash
#!/bin/bash
# Kafka topic initialization script
# This script runs inside the kafka-init container (NOT via docker exec from host)

echo "Creating Kafka topics..."

# Create main clickstream events topic
kafka-topics --create \
  --topic clickstream-events \
  --partitions 3 \
  --replication-factor 1 \
  --if-not-exists \
  --bootstrap-server kafka:29092

# Create error/dead-letter topic
kafka-topics --create \
  --topic clickstream-errors \
  --partitions 1 \
  --replication-factor 1 \
  --if-not-exists \
  --bootstrap-server kafka:29092

# Verify topics created
echo "Listing Kafka topics..."
kafka-topics --list --bootstrap-server kafka:29092

echo "Kafka topic initialization complete!"
```

**docker-compose.yml**:
```yaml
kafka:
  # ... existing config ...
  healthcheck:
    test: ["CMD-SHELL", "kafka-topics --bootstrap-server localhost:9092 --list"]
    interval: 10s
    timeout: 10s
    retries: 5
    start_period: 30s

kafka-init:
  image: confluentinc/cp-kafka:7.0.0
  platform: linux/amd64
  depends_on:
    kafka:
      condition: service_healthy
  volumes:
    - ./scripts/kafka-init/init-kafka-topics.sh:/init-kafka-topics.sh:ro
  command: ["bash", "/init-kafka-topics.sh"]
  restart: "no"
```

> **Note**: The existing `scripts/start_kafka.sh` is for **manual host execution** (uses `docker-compose exec`).
> The new `scripts/kafka-init/init-kafka-topics.sh` is for **automatic container execution** (runs inside Docker network).

### 2.2 Spark Worker Volume Mount (for cluster deploy mode)
**Purpose**: Enable `--deploy-mode cluster` by making source files accessible on Spark workers

> **Why this is needed**: When using `--deploy-mode cluster`, the Spark driver runs on a worker node, not on the Airflow container. The worker needs access to the Python application files (`streaming_job.py`, `batch_job.py`). Without this volume mount, the worker would fail with "file not found" errors.

```yaml
spark-worker:
  image: spark:3.5.3-scala2.12-java17-ubuntu
  command: /opt/spark/bin/spark-class org.apache.spark.deploy.worker.Worker spark://spark-master:7077
  environment:
    - SPARK_WORKER_MEMORY=1G
    - SPARK_WORKER_CORES=1
    - SPARK_NO_DAEMONIZE=true
  depends_on:
    - spark-master
  volumes:
    # Mount source files so cluster deploy mode can access them
    # Path must match what's used in spark-submit commands
    - ./src:/opt/airflow/dags/src:ro
```

> **Path alignment**: The volume mounts `./src` to `/opt/airflow/dags/src` to match the path used in Airflow's spark-submit commands. This ensures the same path works whether running from Airflow (client mode) or on the worker (cluster mode).

### 2.3 Spark Thrift Server
**Purpose**: Required for dbt-spark to connect and run queries

> **Verified**: The `spark:3.5.3-scala2.12-java17-ubuntu` image includes `start-thriftserver.sh`.

> **Port Clarification**: We use port **10000** (the Spark Thrift Server default). Note that dbt-spark documentation mentions port 10001 for EMR/cluster environments where HiveServer2 runs on 10000. In our standalone setup without Hive, port 10000 is correct. If dbt connection fails, verify with `nc -z spark-thrift 10000`.

```yaml
spark-thrift:
  image: spark:3.5.3-scala2.12-java17-ubuntu
  command: >
    /opt/spark/sbin/start-thriftserver.sh
    --master spark://spark-master:7077
    --hiveconf hive.server2.thrift.port=10000
    --conf spark.sql.extensions=io.delta.sql.DeltaSparkSessionExtension
    --conf spark.sql.catalog.spark_catalog=org.apache.spark.sql.delta.catalog.DeltaCatalog
    --conf spark.hadoop.fs.s3a.endpoint=http://localstack:4566
    --conf spark.hadoop.fs.s3a.access.key=test
    --conf spark.hadoop.fs.s3a.secret.key=test
    --conf spark.hadoop.fs.s3a.path.style.access=true
    --packages io.delta:delta-spark_2.12:3.2.1,org.apache.hadoop:hadoop-aws:3.3.4,com.amazonaws:aws-java-sdk-bundle:1.12.262
  ports:
    - "10000:10000"
  environment:
    - SPARK_NO_DAEMONIZE=true
  depends_on:
    - spark-master
  healthcheck:
    test: ["CMD-SHELL", "nc -z localhost 10000"]
    interval: 10s
    timeout: 5s
    retries: 10
    start_period: 60s
```

---

## 3. Custom Airflow Image

### 3.1 Dockerfile
**File**: `docker/airflow/Dockerfile`

> **IMPORTANT**: Java version must match Spark cluster. Spark image uses `java17-ubuntu`, so Airflow must use Java 17.

```dockerfile
# IMPORTANT: Must use Python 3.8 tag because dbt-spark 1.4.0 requires Python 3.8+
# The default apache/airflow:2.3.0 uses Python 3.7 which is incompatible!
# See: https://docs.getdbt.com/faqs/Core/install-python-compatibility
FROM apache/airflow:2.3.0-python3.8

USER root

# Install Java 17 (MUST match Spark cluster: spark:3.5.3-scala2.12-java17-ubuntu)
# Using Java 11 would cause serialization/compatibility issues with the Spark cluster
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       openjdk-17-jdk-headless \
       wget \
       netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Set Java environment (Java 17 path)
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# Download and install Spark (for spark-submit binary)
# Version MUST match Spark cluster version
ENV SPARK_VERSION=3.5.3
ENV HADOOP_VERSION=3
RUN wget -q https://archive.apache.org/dist/spark/spark-${SPARK_VERSION}/spark-${SPARK_VERSION}-bin-hadoop${HADOOP_VERSION}.tgz \
    && tar -xzf spark-${SPARK_VERSION}-bin-hadoop${HADOOP_VERSION}.tgz -C /opt \
    && mv /opt/spark-${SPARK_VERSION}-bin-hadoop${HADOOP_VERSION} /opt/spark \
    && rm spark-${SPARK_VERSION}-bin-hadoop${HADOOP_VERSION}.tgz

ENV SPARK_HOME=/opt/spark
ENV PATH="${SPARK_HOME}/bin:${PATH}"

USER airflow

# Install Python dependencies
COPY requirements-airflow.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements-airflow.txt
```

### 3.2 requirements-airflow.txt
**File**: `docker/airflow/requirements-airflow.txt`

```
# Kafka producer
kafka-python
confluent-kafka
faker

# dbt with Spark Thrift support
# Using 1.4.0 for stability with Airflow 2.3.0
# PyHive extras required for thrift connection method
dbt-core==1.4.0
dbt-spark[PyHive]==1.4.0

# Spark provider for Airflow
apache-airflow-providers-apache-spark

# Utilities
python-dotenv
```

---

## 4. Network Address Fixes

### 4.1 Files to Modify

| File | Line | Change |
|------|------|--------|
| `src/producer/producer.py` | 12 | Use `os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')` |
| `src/streaming/streaming_job.py` | 53 | Use `os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')` |
| `src/streaming/streaming_job.py` | - | Add S3A config to Spark session |
| `src/batch/batch_job.py` | - | Add S3A config to Spark session |
| `dbt/profiles.yml` | All | Use environment variables |

### 4.2 Updated dbt/profiles.yml

```yaml
user_behavior_analytics:
  target: dev
  outputs:
    dev:
      type: spark
      method: thrift
      host: "{{ env_var('SPARK_THRIFT_HOST', 'localhost') }}"
      port: "{{ env_var('SPARK_THRIFT_PORT', '10000') | int }}"
      schema: default
      connect_retries: 5
      connect_timeout: 60
```

---

## 5. Updated DAGs

We now have **two DAGs**:

| DAG | Schedule | Purpose |
|-----|----------|---------|
| `clickstream_streaming` | `*/1 * * * *` (every minute) | Ensures streaming job is running on Spark cluster |
| `clickstream_processing` | `0 0 * * *` (daily) | Batch aggregations and dbt tests |

### 5.1 clickstream_streaming DAG (NEW)

**File**: `dags/clickstream_streaming_dag.py`

```python
from datetime import datetime, timedelta
import json
import subprocess
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import ShortCircuitOperator

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'retries': 1,
    'retry_delay': timedelta(seconds=30),
}

def is_streaming_job_needed():
    """Check if streaming job is already running on Spark cluster."""
    try:
        result = subprocess.run(
            ["curl", "-s", "http://spark-master:8080/json/"],
            capture_output=True, text=True, timeout=10
        )
        data = json.loads(result.stdout)
        # Check active applications for our streaming job
        for app in data.get("activeapps", []):
            if "streaming" in app.get("name", "").lower():
                print(f"Streaming job already running: {app.get('id')}")
                return False  # Job running, skip submission
        print("No streaming job found, will submit")
        return True  # No job running, proceed with submission
    except Exception as e:
        print(f"Error checking Spark master: {e}, will attempt submission")
        return True  # On error, try to submit

# Version justification (see Version Compatibility Matrix above):
# - spark-sql-kafka: 3.5.3 matches Spark cluster version
# - delta-spark: 3.2.1 for Spark 3.5.3 compatibility (3.2.0 was for 3.5.0-3.5.2)
# - hadoop-aws: 3.3.4 matches Spark's bundled Hadoop
# - aws-java-sdk-bundle: 1.12.262 required by hadoop-aws 3.3.4
SPARK_PACKAGES = (
    "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.3,"
    "io.delta:delta-spark_2.12:3.2.1,"
    "org.apache.hadoop:hadoop-aws:3.3.4,"
    "com.amazonaws:aws-java-sdk-bundle:1.12.262"
)

dag = DAG(
    'clickstream_streaming',
    default_args=default_args,
    description='Ensures streaming job is running on Spark cluster',
    schedule_interval='*/1 * * * *',  # Every minute
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=['streaming', 'spark', 'kafka'],
)

check_job = ShortCircuitOperator(
    task_id='check_if_submission_needed',
    python_callable=is_streaming_job_needed,
    dag=dag,
)

submit_streaming = BashOperator(
    task_id='submit_streaming_job',
    bash_command=f'''
        spark-submit \\
            --master spark://spark-master:7077 \\
            --deploy-mode cluster \\
            --supervise \\
            --name "ClickstreamStreaming" \\
            --packages {SPARK_PACKAGES} \\
            --conf spark.hadoop.fs.s3a.endpoint=http://localstack:4566 \\
            --conf spark.hadoop.fs.s3a.access.key=test \\
            --conf spark.hadoop.fs.s3a.secret.key=test \\
            --conf spark.hadoop.fs.s3a.path.style.access=true \\
            --conf spark.sql.extensions=io.delta.sql.DeltaSparkSessionExtension \\
            --conf spark.sql.catalog.spark_catalog=org.apache.spark.sql.delta.catalog.DeltaCatalog \\
            /opt/airflow/dags/src/streaming/streaming_job.py
    ''',
    dag=dag,
)

check_job >> submit_streaming
```

### 5.2 clickstream_processing DAG (Updated)

**File**: `dags/clickstream_processing_dag.py`

```python
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.providers.apache.spark.operators.spark_submit import SparkSubmitOperator

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'retries': 3,
    'retry_delay': timedelta(minutes=5),
}

# Version justification (see Version Compatibility Matrix above):
# - delta-spark: 3.2.1 for Spark 3.5.3 compatibility
# - hadoop-aws: 3.3.4 matches Spark's bundled Hadoop
# - aws-java-sdk-bundle: 1.12.262 required by hadoop-aws 3.3.4
SPARK_PACKAGES = (
    "io.delta:delta-spark_2.12:3.2.1,"
    "org.apache.hadoop:hadoop-aws:3.3.4,"
    "com.amazonaws:aws-java-sdk-bundle:1.12.262"
)

SPARK_CONF = {
    'spark.hadoop.fs.s3a.endpoint': 'http://localstack:4566',
    'spark.hadoop.fs.s3a.access.key': 'test',
    'spark.hadoop.fs.s3a.secret.key': 'test',
    'spark.hadoop.fs.s3a.path.style.access': 'true',
    'spark.sql.extensions': 'io.delta.sql.DeltaSparkSessionExtension',
    'spark.sql.catalog.spark_catalog': 'org.apache.spark.sql.delta.catalog.DeltaCatalog',
}

dag = DAG(
    'clickstream_processing',
    default_args=default_args,
    description='Daily batch processing and data quality for clickstream',
    schedule_interval='0 0 * * *',  # Daily at midnight
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=['batch', 'spark', 'dbt'],
)

# Generate test data (optional - streaming handles real-time ingestion)
generate_data = BashOperator(
    task_id='generate_test_data',
    bash_command='timeout 60 python /opt/airflow/dags/src/producer/producer.py || true',
    env={
        'KAFKA_BOOTSTRAP_SERVERS': 'kafka:29092',
    },
    dag=dag,
)

# Run batch aggregations (Silver → Gold)
run_batch = SparkSubmitOperator(
    task_id='run_batch_processing',
    application='/opt/airflow/dags/src/batch/batch_job.py',
    conn_id='spark_default',
    packages=SPARK_PACKAGES,
    conf=SPARK_CONF,
    dag=dag,
)

# Run dbt tests
run_dbt = BashOperator(
    task_id='run_dbt_tests',
    bash_command='cd /opt/airflow/dags/dbt && dbt test --profiles-dir .',
    env={
        'SPARK_THRIFT_HOST': 'spark-thrift',
        'SPARK_THRIFT_PORT': '10000',
    },
    dag=dag,
)

generate_data >> run_batch >> run_dbt
```

---

## 6. Environment Variables

### docker-compose.yml airflow service

```yaml
airflow:
  build:
    context: ./docker/airflow
    dockerfile: Dockerfile
  command: >
    bash -c "(airflow users delete --username admin || true) &&
    airflow users create --username admin --password admin --firstname Admin --lastname User --role Admin --email admin@example.com &&
    airflow standalone"
  environment:
    - AIRFLOW__CORE__EXECUTOR=LocalExecutor
    - AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql+psycopg2://airflow:airflow@postgres/airflow
    - AIRFLOW__CORE__FERNET_KEY=46BKJoQYlPPOexq0OhDZnIlNepKFf87WFwLbfzqDDho=
    - AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION=false
    - AIRFLOW__CORE__LOAD_EXAMPLES=false
    # Spark connection
    - AIRFLOW_CONN_SPARK_DEFAULT=spark://spark-master:7077
    # Kafka
    - KAFKA_BOOTSTRAP_SERVERS=kafka:29092
    # S3/LocalStack
    - AWS_ACCESS_KEY_ID=test
    - AWS_SECRET_ACCESS_KEY=test
    - S3_ENDPOINT=http://localstack:4566
    # dbt/Spark Thrift
    - SPARK_THRIFT_HOST=spark-thrift
    - SPARK_THRIFT_PORT=10000
  volumes:
    - ./dags:/opt/airflow/dags
    - ./src:/opt/airflow/dags/src
    - ./dbt:/opt/airflow/dags/dbt
  ports:
    - "8081:8080"
  depends_on:
    postgres:
      condition: service_healthy
    spark-thrift:
      condition: service_healthy
```

---

## 7. Complete File List

### New Files to Create

| File | Description |
|------|-------------|
| `docker/airflow/Dockerfile` | Custom Airflow image with Java 17, Spark, dbt |
| `docker/airflow/requirements-airflow.txt` | Python dependencies |
| `scripts/kafka-init/init-kafka-topics.sh` | **NEW** - Kafka topic initialization (container execution) |
| `dags/clickstream_streaming_dag.py` | **NEW** - Streaming orchestration DAG |
| `dags/clickstream_processing_dag.py` | **NEW** - Batch processing DAG (replaces pipeline_dag.py) |

### Files to Modify

| File | Changes |
|------|---------|
| `docker-compose.yml` | Add kafka healthcheck, kafka-init, spark-thrift services; add spark-worker volume mount; update airflow |
| `src/producer/producer.py` | Use env var for Kafka address |
| `src/streaming/streaming_job.py` | Use env vars, add S3A config, ensure checkpointing |
| `src/batch/batch_job.py` | Add S3A config |
| `dbt/profiles.yml` | Use env vars for Spark Thrift connection |

> **⚠️ spark-worker volume mount is CRITICAL**: Without mounting `./src:/opt/airflow/dags/src:ro` to spark-worker, the `--deploy-mode cluster` will fail because the worker cannot access the Python application files.

> **⚠️ IMPORTANT - Source File Updates Required**:
> The current source files have issues that must be fixed:
>
> 1. **Delta Lake version**: Files currently use `delta-spark_2.12:3.2.0` but should use `3.2.1` for Spark 3.5.3 compatibility
>    - `src/streaming/streaming_job.py:43-44`
>    - `src/batch/batch_job.py:31-32`
>    - `dags/pipeline_dag.py:30`
>
> 2. **Missing S3A packages**: Source files reference `s3a://` paths but don't include:
>    - `org.apache.hadoop:hadoop-aws:3.3.4`
>    - `com.amazonaws:aws-java-sdk-bundle:1.12.262`
>
>    These are provided via DAG spark-submit commands, but if running source files directly, they will fail.
>
> 3. **dbt/profiles.yml**: Current file has duplicate `user_behavior_analytics:` YAML keys (invalid). Must be fixed.

### Files to Delete (Optional)

| File | Reason |
|------|--------|
| `dags/pipeline_dag.py` | Replaced by `clickstream_streaming_dag.py` and `clickstream_processing_dag.py` |

---

## 8. Implementation Order

1. **Create docker/airflow/Dockerfile and requirements-airflow.txt** (with Java 17, Python 3.8 base)
2. **Create scripts/kafka-init/init-kafka-topics.sh**
3. **Update docker-compose.yml**:
   - Add Kafka healthcheck
   - Add kafka-init service (mounting init script)
   - Add spark-thrift service
   - **Add spark-worker volume mount** (`./src:/opt/airflow/dags/src:ro`) for cluster deploy mode
   - Update airflow to use custom image (Python 3.8 base)
4. **Fix network addresses in source files**:
   - `src/producer/producer.py`
   - `src/streaming/streaming_job.py` (also ensure checkpointing)
   - `src/batch/batch_job.py`
5. **Update dbt/profiles.yml**
6. **Create new DAG files**:
   - `dags/clickstream_streaming_dag.py`
   - `dags/clickstream_processing_dag.py`
7. **Delete old DAG**: `dags/pipeline_dag.py`
8. **Build and test**: `docker compose build && docker compose up -d`
9. **Verify**:
   - Kafka topics created (check Kafdrop http://localhost:9000)
   - S3 buckets exist (`aws --endpoint-url=http://localhost:4566 s3 ls`)
   - Spark Thrift Server running (port 10000)
   - Both DAGs visible in Airflow UI (http://localhost:8081)
   - Enable `clickstream_streaming` DAG → verify streaming job starts on cluster
   - Check Spark UI (http://localhost:8080) for running streaming application
   - Trigger `clickstream_processing` DAG manually and verify batch + dbt runs

---

## 9. Testing Checklist

### Infrastructure
- [ ] `docker compose up -d` starts all services without errors
- [ ] Kafka topics auto-created (verify in Kafdrop http://localhost:9000)
- [ ] S3 buckets exist (`aws --endpoint-url=http://localhost:4566 s3 ls`)
- [ ] Spark Thrift Server accessible on port 10000

### Streaming Orchestration
- [ ] `clickstream_streaming` DAG visible in Airflow UI
- [ ] DAG runs every minute with `max_active_runs=1`
- [ ] First run submits streaming job to Spark cluster
- [ ] Subsequent runs detect job is running and skip (ShortCircuit)
- [ ] Streaming job visible in Spark UI (http://localhost:8080) as "ClickstreamStreaming"
- [ ] If streaming job is killed, next DAG run restarts it

### Batch Processing
- [ ] `clickstream_processing` DAG visible in Airflow UI
- [ ] Manual trigger runs successfully
- [ ] Batch job reads from Silver layer, writes to Gold layer
- [ ] dbt tests pass

### End-to-End
- [ ] Producer sends events to Kafka
- [ ] Streaming job writes to S3 Silver layer (Delta format)
- [ ] Batch job aggregates Silver → Gold
- [ ] Data queryable via Spark Thrift/Trino

---

## 10. Rollback Plan

1. Keep backup of original docker-compose.yml
2. Keep backup of the existing `dags/pipeline_dag.py` before deleting it
3. Original source files unchanged until tested
4. Can revert by: `git checkout docker-compose.yml` and remove docker/airflow directory

---

## 11. Version Compatibility Verification (2024-12-04)

> This section documents the research verification of the version compatibility matrix.

### Verified Items

| Item | Status | Evidence |
|------|--------|----------|
| Delta 3.2.1 for Spark 3.5.3 | ✅ Verified | [GitHub Releases](https://github.com/delta-io/delta/releases) - Delta 3.2.1 built on Spark 3.5.3 |
| hadoop-aws 3.3.4 + aws-sdk 1.12.262 | ✅ Verified | [Hadoop 3.3.4 Release Notes](https://hadoop.apache.org/docs/r3.3.4/hadoop-project-dist/hadoop-common/release/3.3.4/RELEASENOTES.3.3.4.html) |
| Spark archive URL | ✅ Verified | `spark-3.5.3-bin-hadoop3.tgz` (382M) at [Apache Archive](https://archive.apache.org/dist/spark/spark-3.5.3/) |
| `--deploy-mode cluster --supervise` | ✅ Verified | [Spark Documentation](https://spark.apache.org/docs/latest/submitting-applications.html) confirms standalone cluster support |
| Java 17 in Airflow 2.3.0 | ✅ Verified | [Airflow Docker Docs](https://airflow.apache.org/docs/docker-stack/build.html) shows apt-get install pattern |
| dbt-spark PyHive for thrift | ✅ Verified | [dbt Spark Setup](https://docs.getdbt.com/docs/core/connect-data-platform/spark-setup) |
| dbt-spark 1.4.0 requires Python 3.8+ | ✅ Verified | [dbt Python Compatibility](https://docs.getdbt.com/faqs/Core/install-python-compatibility) - dbt-core 1.4.0 supports Python 3.8-3.11 |
| Airflow 2.3.0 default Python 3.7 | ✅ Verified | [Docker Hub](https://hub.docker.com/r/apache/airflow) - Must use `-python3.8` tag for dbt compatibility |
| SPARK_NO_DAEMONIZE for Docker | ✅ Verified | [Stack Overflow](https://stackoverflow.com/questions/39671117) - Required for foreground execution in containers |
| Kafka healthcheck command | ✅ Verified | `kafka-topics --bootstrap-server localhost:9092 --list` works inside container |

### Pre-Implementation Checks (Manual)

Before starting implementation, run these commands to verify environment:

```bash
# 1. Verify Spark image has start-thriftserver.sh
docker run --rm spark:3.5.3-scala2.12-java17-ubuntu ls -la /opt/spark/sbin/start-thriftserver.sh

# 2. Verify Airflow Python 3.8 image exists and check Python version
docker run --rm apache/airflow:2.3.0-python3.8 python --version
# Expected output: Python 3.8.x

# 3. Test Java 17 installation in Airflow base (Python 3.8 tag)
docker run --rm apache/airflow:2.3.0-python3.8 bash -c "apt-get update && apt-get install -y openjdk-17-jdk-headless && java -version"

# 4. Verify Spark archive download
curl -I https://archive.apache.org/dist/spark/spark-3.5.3/spark-3.5.3-bin-hadoop3.tgz

# 5. Verify dbt-spark can be installed with Python 3.8
docker run --rm apache/airflow:2.3.0-python3.8 pip install dbt-spark[PyHive]==1.4.0 --dry-run
```

### Research Sources

- [Delta Lake Releases](https://github.com/delta-io/delta/releases)
- [Delta Lake Official Release Docs](https://docs.delta.io/latest/releases.html)
- [Hadoop 3.3.4 Release Notes](https://hadoop.apache.org/docs/r3.3.4/hadoop-project-dist/hadoop-common/release/3.3.4/RELEASENOTES.3.3.4.html)
- [hadoop-aws Compatibility (Stack Overflow)](https://stackoverflow.com/questions/77327653/hadoop-common-hadoop-aws-aws-java-sdk-bundle-version-compatibility)
- [Maven hadoop-aws 3.3.4 Dependencies](https://mvnrepository.com/artifact/org.apache.hadoop/hadoop-aws/3.3.4)
- [dbt Spark Setup](https://docs.getdbt.com/docs/core/connect-data-platform/spark-setup)
- [dbt Python Version Compatibility](https://docs.getdbt.com/faqs/Core/install-python-compatibility)
- [Spark Submitting Applications](https://spark.apache.org/docs/latest/submitting-applications.html)
- [Airflow Docker Stack](https://airflow.apache.org/docs/docker-stack/build.html)
- [Airflow Docker Hub Tags](https://hub.docker.com/r/apache/airflow)
- [SPARK_NO_DAEMONIZE for Docker (Stack Overflow)](https://stackoverflow.com/questions/39671117/docker-container-with-apache-spark-in-standalone-cluster-mode)
- [Spark daemon.sh source](https://github.com/apache/spark/blob/master/sbin/spark-daemon.sh)
