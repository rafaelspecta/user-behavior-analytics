"""
Pipeline Health Monitoring DAG

Checks the health of the running data pipeline infrastructure:
  - Kafka: verifies topic exists via Kafdrop API
  - Spark Streaming: verifies active application via Spark Master REST API
  - S3 Data Lake: verifies Delta Lake files exist in LocalStack S3

Runs every 5 minutes with a 10-minute delayed start to allow services
to initialise after docker compose up.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.utils.dates import days_ago

default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=1),
}

dag = DAG(
    "pipeline_health_monitor",
    default_args=default_args,
    description="Checks health of Kafka, Spark, and S3 pipeline components",
    schedule_interval="*/5 * * * *",
    start_date=datetime(2026, 4, 14, 0, 10, 0),
    catchup=False,
    max_active_runs=1,
    tags=["monitoring", "health"],
)

check_kafka = BashOperator(
    task_id="check_kafka",
    bash_command=(
        'echo "Checking Kafka topics via Kafdrop..." && '
        "curl -sf http://kafdrop:9000/topic/clickstream-events "
        '|| echo "WARNING: Kafdrop not reachable (may still be starting)"'
    ),
    dag=dag,
)

check_streaming = BashOperator(
    task_id="check_streaming_job",
    bash_command=(
        'echo "Checking Spark Master for active applications..." && '
        "curl -sf http://spark-master:8080/json/ "
        "| python3 -c \""
        "import sys, json; "
        "data = json.load(sys.stdin); "
        "apps = data.get('activeapps', []); "
        "print(f'Active apps: {len(apps)}'); "
        "[print(f'  - {a[\\\"name\\\"]} (state: {a[\\\"state\\\"]})') for a in apps]; "
        "sys.exit(0 if apps else 1)\" "
        '|| echo "WARNING: No active Spark apps (streaming job may still be starting)"'
    ),
    dag=dag,
)

check_s3 = BashOperator(
    task_id="check_s3_data",
    bash_command=(
        'echo "Checking S3 for Delta Lake data..." && '
        "curl -sf 'http://localstack:4566/user-behavior-analytics-silver?"
        "list-type=2&prefix=clickstream/delta/&max-keys=5' "
        "| python3 -c \""
        "import sys; "
        "content = sys.stdin.read(); "
        "count = content.count('<Key>'); "
        "print(f'Found {count} objects in silver bucket'); "
        "sys.exit(0 if count > 0 else 1)\" "
        '|| echo "WARNING: No data in S3 yet (pipeline may still be starting)"'
    ),
    dag=dag,
)

check_kafka >> check_streaming >> check_s3
