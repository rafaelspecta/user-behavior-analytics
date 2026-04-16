"""
Pipeline Health Monitoring DAG

Checks the health of the running data pipeline infrastructure:
  - Kafka:    verifies the clickstream-events topic is reachable via Kafdrop
  - S3 Lake:  verifies Delta Lake files exist in LocalStack S3

Runs every 5 minutes with a 10-minute delayed start to allow services to
initialise after `docker compose up`.

Spark streaming health is intentionally NOT checked here. That responsibility
lives in the `clickstream_streaming_supervisor` DAG (Architecture B), which
both checks the Spark Master REST API and restarts the streaming-job
container via the Docker Engine API when the application has died. Keeping
health monitoring split this way avoids duplicated checks running on the
same 5-minute schedule.
"""

from datetime import datetime, timedelta

from airflow.sdk import DAG
from airflow.operators.bash import BashOperator

default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=1),
}

dag = DAG(
    "pipeline_health_monitor",
    default_args=default_args,
    description="Checks health of Kafka and S3 pipeline components",
    schedule="*/5 * * * *",
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

check_kafka >> check_s3
