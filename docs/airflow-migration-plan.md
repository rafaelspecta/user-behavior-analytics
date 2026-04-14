# Airflow Migration Plan: 2.3.0 → 2.4.x

---

## Executive Summary

This plan outlines the migration from Apache Airflow 2.3.0 to 2.4.x to enable the `@continuous` scheduling feature for streaming job orchestration.

**Why Migrate?**
- Airflow 2.4+ introduces `schedule="@continuous"` for continuous DAG execution
- This enables proper orchestration of streaming jobs within Airflow
- Better visibility and control over streaming pipelines

---

## 1. Breaking Changes Analysis

### 1.1 Changes That Affect Us

| Change | Our Impact | Action Required |
|--------|------------|-----------------|
| XCom tied to DagRun | Low - we don't heavily use XCom | Update any `execution_date` refs to `run_id` |
| `airflow db migrate` required | Medium | Run migration after upgrade |
| Flask App Builder 4.* | Low - no OAuth configured | None |

### 1.2 Changes That Don't Affect Us

| Change | Why Not Affected |
|--------|------------------|
| Smart Sensors removed | We don't use Smart Sensors |
| `DBApiHook`/`SQLSensor` moved | We don't import from old paths |
| `airflow.contrib` deprecation | We don't use contrib modules |

---

## 2. Pre-Migration Checklist

- [ ] Backup Airflow metadata database (postgres volume)
- [ ] Document current DAG states and schedules
- [ ] Review `dags/pipeline_dag.py` for deprecated imports
- [ ] Test DAGs syntax with Airflow 2.4 locally (optional)

---

## 3. Migration Steps

### Step 1: Update Docker Image Version

**File**: `docker-compose.yml` (or `docker/airflow/Dockerfile`)

```dockerfile
# Before
FROM apache/airflow:2.3.0

# After
FROM apache/airflow:2.4.3
```

**Note**: Using 2.4.3 (latest patch of 2.4.x) for stability.

### Step 2: Update Python Dependencies

**File**: `docker/airflow/requirements-airflow.txt`

Ensure provider packages are compatible with 2.4.x:
```
apache-airflow-providers-apache-spark>=4.0.0
apache-airflow-providers-common-sql>=1.0.0  # New dependency for SQL operators
```

### Step 3: Database Migration

After starting the new Airflow container, run:
```bash
docker compose exec airflow airflow db migrate
```

Or include in the startup command:
```yaml
command: >
  bash -c "
    airflow db migrate &&
    (airflow users delete --username admin || true) &&
    airflow users create --username admin --password admin ... &&
    airflow standalone
  "
```

### Step 4: Update DAG to Use @continuous

**File**: `dags/pipeline_dag.py`

```python
# Before (2.3.0 style)
dag = DAG(
    'clickstream_pipeline',
    schedule_interval='0 0 * * *',  # Daily cron
    ...
)

# After (2.4+ style with continuous)
from airflow.decorators import dag

@dag(
    schedule="@continuous",      # Continuous execution
    max_active_runs=1,           # Only one run at a time
    catchup=False,               # Don't backfill
    ...
)
def clickstream_streaming_pipeline():
    ...
```

---

## 4. New DAG Pattern for Streaming

### 4.1 Architecture with @continuous

```
┌─────────────────────────────────────────────────────────────┐
│                    Airflow DAG (@continuous)                │
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐   │
│  │ check_job    │───→│ submit_job   │───→│ health_check │   │
│  │ (is running?)│    │ (if needed)  │    │ (optional)   │   │
│  └──────────────┘    └──────────────┘    └──────────────┘   │
│         │                                                   │
│         │ Job already running? → Skip submission            │
│         └─────────────────────────────────────────────────  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              Spark Cluster (Standalone)                     │
│                                                             │
│  spark-submit --deploy-mode cluster --supervise             │
│  └──→ Streaming job runs continuously on worker             │
│  └──→ Auto-restarts if driver fails (--supervise)           │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Example DAG Code

```python
from datetime import datetime
from airflow.decorators import dag, task
from airflow.operators.bash import BashOperator
from airflow.operators.python import ShortCircuitOperator
import subprocess

def is_streaming_job_running():
    """Check if streaming job is already running on Spark cluster."""
    try:
        result = subprocess.run(
            ["curl", "-s", "http://spark-master:8080/json/"],
            capture_output=True, text=True, timeout=10
        )
        # Parse JSON to check for running "TelcoStreamingJob" application
        import json
        data = json.loads(result.stdout)
        for app in data.get("activeapps", []):
            if "streaming" in app.get("name", "").lower():
                return False  # Job running, skip submission
        return True  # No job running, proceed with submission
    except Exception:
        return True  # On error, try to submit

@dag(
    start_date=datetime(2024, 1, 1),
    schedule="@continuous",
    max_active_runs=1,
    catchup=False,
    tags=["streaming", "spark", "kafka"]
)
def clickstream_streaming_pipeline():

    check_job = ShortCircuitOperator(
        task_id="check_if_job_needed",
        python_callable=is_streaming_job_running,
    )

    submit_streaming = BashOperator(
        task_id="submit_streaming_job",
        bash_command="""
            spark-submit \
                --master spark://spark-master:7077 \
                --deploy-mode cluster \
                --supervise \
                --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.3,io.delta:delta-spark_2.12:3.2.0 \
                --conf spark.hadoop.fs.s3a.endpoint=http://localstack:4566 \
                --conf spark.hadoop.fs.s3a.access.key=test \
                --conf spark.hadoop.fs.s3a.secret.key=test \
                --conf spark.hadoop.fs.s3a.path.style.access=true \
                /opt/airflow/dags/src/streaming/streaming_job.py
        """,
    )

    check_job >> submit_streaming

clickstream_streaming_pipeline()
```

---

## 5. Streaming Job Modifications

### 5.1 Remove awaitTermination() Call

The streaming job should NOT block indefinitely when submitted in cluster mode.

**File**: `src/streaming/streaming_job.py`

```python
# Before
query.awaitTermination()

# After - Let the job run, but don't block spark-submit
# The --supervise flag handles restarts
query.awaitTermination()  # This is fine in cluster mode - driver stays alive
```

**Note**: In cluster mode, `awaitTermination()` keeps the driver alive on the worker (desired behavior). The spark-submit command returns immediately regardless.

### 5.2 Checkpointing (Critical)

Ensure checkpoint location is configured for fault tolerance:

```python
query = df.writeStream \
    .outputMode("append") \
    .format("delta") \
    .option("checkpointLocation", "s3a://user-behavior-analytics-silver/checkpoints/streaming") \
    .start("s3a://user-behavior-analytics-silver/events")
```

---

## 6. Testing Plan

### 6.1 Pre-Migration Tests
- [ ] Verify current DAGs work in Airflow 2.3.0
- [ ] Document current task states

### 6.2 Post-Migration Tests
- [ ] Airflow UI accessible at http://localhost:8081
- [ ] `airflow db migrate` completes without errors
- [ ] DAGs load without import errors
- [ ] Continuous DAG triggers immediately
- [ ] Streaming job submits to Spark cluster
- [ ] Job visible in Spark UI (http://localhost:8080)
- [ ] Subsequent DAG runs detect running job and skip

---

## 7. Rollback Plan

If migration fails:

1. Stop all containers: `docker compose down`
2. Restore postgres volume from backup
3. Revert Dockerfile to `apache/airflow:2.3.0`
4. Restart: `docker compose up -d`

---

## 8. Timeline Recommendation

This migration should be done **after** the containerization plan is complete and tested, because:
1. Containerization changes are more fundamental
2. Easier to debug issues one change at a time
3. Can validate streaming works with frequent cron first, then upgrade to @continuous

**Order**:
1. Complete containerization (Airflow 2.3.0 + frequent cron schedule)
2. Test everything works
3. Migrate to Airflow 2.4.x
4. Switch to @continuous schedule
5. Test streaming orchestration

---

## References

- [Airflow 2.4.0 Release Notes](https://airflow.apache.org/docs/apache-airflow/2.4.0/release_notes.html)
- [Airflow Continuous Timetable](https://airflow.apache.org/docs/apache-airflow/stable/concepts/scheduling.html)
- [Spark Submitting Applications](https://spark.apache.org/docs/latest/submitting-applications.html)
