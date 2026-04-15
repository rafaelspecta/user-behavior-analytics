"""
Clickstream Analytics Pipeline DAG

Demonstrates a simplified data pipeline within Airflow:
  1. Generate sample clickstream events (JSON)
  2. Process/aggregate the events
  3. Validate data quality
  4. Create a summary report

The real streaming pipeline runs outside Airflow (producer -> Kafka ->
Spark Structured Streaming -> Delta Lake on S3). This DAG showcases
what an Airflow-orchestrated batch pipeline looks like using only the
Python standard library so it works in a vanilla Airflow image.

Trigger manually from the Airflow UI (schedule=None).
"""

import json
import os
import random
import uuid
from datetime import datetime, timedelta

from airflow.sdk import DAG
from airflow.operators.python import PythonOperator

# ---------------------------------------------------------------------------
# Original production commands (require Spark + Kafka inside the Airflow
# container — kept here for reference):
#
# SPARK_PACKAGES = (
#     "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.3,"
#     "io.delta:delta-spark_2.12:3.2.0"
# )
#
# start_producer = BashOperator(
#     task_id='start_kafka_producer',
#     bash_command='timeout 60 python /opt/airflow/dags/src/producer/producer.py || true',
# )
# start_streaming = BashOperator(
#     task_id='start_spark_streaming',
#     bash_command=f'spark-submit --master local[*] --packages {SPARK_PACKAGES} '
#                  '/opt/airflow/dags/src/streaming/streaming_job.py',
# )
# run_batch = BashOperator(
#     task_id='run_batch_processing',
#     bash_command=f'spark-submit --master local[*] --packages {SPARK_PACKAGES} '
#                  '/opt/airflow/dags/src/batch/batch_job.py',
# )
# run_dbt_tests = BashOperator(
#     task_id='run_dbt_tests',
#     bash_command='cd /opt/airflow/dags/dbt && dbt test',
# )
# ---------------------------------------------------------------------------

DATA_DIR = "/tmp/airflow_pipeline"

EVENT_TYPES = ["page_view", "product_view", "add_to_cart", "checkout", "purchase"]
PRODUCTS = ["laptop", "smartphone", "headphones", "tablet", "smartwatch"]
DEVICES = ["desktop", "mobile", "tablet"]

default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=1),
}

dag = DAG(
    "clickstream_pipeline",
    default_args=default_args,
    description="End-to-end clickstream data pipeline (simplified demo)",
    schedule=None,
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=["clickstream", "analytics", "demo"],
)


def generate_sample_events(**context):
    """Generate synthetic clickstream events and write them as JSON."""
    os.makedirs(DATA_DIR, exist_ok=True)
    events = []
    for _ in range(200):
        events.append({
            "event_id": str(uuid.uuid4()),
            "event_type": random.choice(EVENT_TYPES),
            "product_id": random.choice(PRODUCTS),
            "device_type": random.choice(DEVICES),
            "timestamp": datetime.utcnow().isoformat(),
            "time_on_page": random.randint(5, 300),
        })
    path = os.path.join(DATA_DIR, "raw_events.json")
    with open(path, "w") as f:
        json.dump(events, f)
    print(f"Generated {len(events)} events -> {path}")
    return path


def process_events(**context):
    """Read raw events, aggregate by event_type and device, write results."""
    raw_path = os.path.join(DATA_DIR, "raw_events.json")
    with open(raw_path) as f:
        events = json.load(f)

    agg = {}
    for e in events:
        key = (e["event_type"], e["device_type"])
        if key not in agg:
            agg[key] = {"count": 0, "total_time": 0}
        agg[key]["count"] += 1
        agg[key]["total_time"] += e.get("time_on_page", 0)

    results = [
        {
            "event_type": k[0],
            "device_type": k[1],
            "count": v["count"],
            "avg_time_on_page": round(v["total_time"] / v["count"], 1),
        }
        for k, v in sorted(agg.items())
    ]

    out_path = os.path.join(DATA_DIR, "aggregated.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Aggregated {len(events)} events into {len(results)} groups -> {out_path}")
    return out_path


def validate_data(**context):
    """Run basic quality checks on the aggregated output."""
    agg_path = os.path.join(DATA_DIR, "aggregated.json")
    with open(agg_path) as f:
        rows = json.load(f)

    checks_passed = 0
    checks_total = 0

    checks_total += 1
    assert len(rows) > 0, "No aggregated rows"
    checks_passed += 1

    checks_total += 1
    total_events = sum(r["count"] for r in rows)
    assert total_events == 200, f"Expected 200 events, got {total_events}"
    checks_passed += 1

    for r in rows:
        checks_total += 1
        assert r["avg_time_on_page"] > 0, f"Invalid avg_time_on_page for {r}"
        checks_passed += 1

        checks_total += 1
        assert r["event_type"] in EVENT_TYPES, f"Unknown event_type: {r['event_type']}"
        checks_passed += 1

    print(f"All {checks_passed}/{checks_total} quality checks passed")


def create_report(**context):
    """Produce a human-readable summary report."""
    agg_path = os.path.join(DATA_DIR, "aggregated.json")
    with open(agg_path) as f:
        rows = json.load(f)

    total = sum(r["count"] for r in rows)
    report_lines = [
        "=" * 50,
        " Clickstream Pipeline Report",
        f" Generated: {datetime.utcnow().isoformat()}",
        "=" * 50,
        f" Total events processed: {total}",
        "",
        " Breakdown by event type:",
    ]

    by_type = {}
    for r in rows:
        by_type.setdefault(r["event_type"], 0)
        by_type[r["event_type"]] += r["count"]
    for et, cnt in sorted(by_type.items(), key=lambda x: -x[1]):
        report_lines.append(f"   {et:<15} {cnt:>5}  ({cnt/total*100:.1f}%)")

    report_lines += ["", " Breakdown by device:"]
    by_device = {}
    for r in rows:
        by_device.setdefault(r["device_type"], 0)
        by_device[r["device_type"]] += r["count"]
    for dev, cnt in sorted(by_device.items(), key=lambda x: -x[1]):
        report_lines.append(f"   {dev:<15} {cnt:>5}  ({cnt/total*100:.1f}%)")

    report_lines.append("=" * 50)

    report = "\n".join(report_lines)
    report_path = os.path.join(DATA_DIR, "report.txt")
    with open(report_path, "w") as f:
        f.write(report)
    print(report)
    return report_path


generate = PythonOperator(
    task_id="generate_sample_events",
    python_callable=generate_sample_events,
    dag=dag,
)

process = PythonOperator(
    task_id="process_events",
    python_callable=process_events,
    dag=dag,
)

validate = PythonOperator(
    task_id="validate_data",
    python_callable=validate_data,
    dag=dag,
)

report = PythonOperator(
    task_id="create_report",
    python_callable=create_report,
    dag=dag,
)

generate >> process >> validate >> report
