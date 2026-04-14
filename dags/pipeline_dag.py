from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.email import EmailOperator
from airflow.utils.dates import days_ago

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'email': ['alerts@example.com'],
    'email_on_failure': True,
    'email_on_retry': True,
    'retries': 3,
    'retry_delay': timedelta(minutes=5),
}

dag = DAG(
    'clickstream_pipeline',
    default_args=default_args,
    description='End-to-end clickstream data pipeline',
    schedule_interval='0 0 * * *',  # Run daily at midnight
    start_date=days_ago(1),
    catchup=False,
    tags=['clickstream', 'analytics'],
)

# Spark packages for Delta Lake and Kafka integration
SPARK_PACKAGES = (
    "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.3,"
    "io.delta:delta-spark_2.12:3.2.0"
)

# Start Kafka producer (runs for a limited time to generate test data)
start_producer = BashOperator(
    task_id='start_kafka_producer',
    bash_command='timeout 60 python /opt/airflow/dags/src/producer/producer.py || true',
    dag=dag,
)

# Start Spark streaming job
# Note: For production, streaming job should run continuously (not via Airflow)
# This is for demo/testing purposes - runs in local mode
start_streaming = BashOperator(
    task_id='start_spark_streaming',
    bash_command=f'spark-submit --master local[*] --packages {SPARK_PACKAGES} /opt/airflow/dags/src/streaming/streaming_job.py',
    dag=dag,
)

# Run batch processing
run_batch = BashOperator(
    task_id='run_batch_processing',
    bash_command=f'spark-submit --master local[*] --packages {SPARK_PACKAGES} /opt/airflow/dags/src/batch/batch_job.py',
    dag=dag,
)

# Run dbt tests
run_dbt_tests = BashOperator(
    task_id='run_dbt_tests',
    bash_command='cd /opt/airflow/dags/dbt && dbt test',
    dag=dag,
)

# Send success notification
send_success_notification = EmailOperator(
    task_id='send_success_notification',
    to='analytics-team@example.com',
    subject='Clickstream Pipeline Success',
    html_content='The clickstream pipeline has completed successfully.',
    dag=dag,
)

# Send failure notification
send_failure_notification = EmailOperator(
    task_id='send_failure_notification',
    to='alerts@example.com',
    subject='Clickstream Pipeline Failure',
    html_content='The clickstream pipeline has failed. Please check the logs.',
    trigger_rule='one_failed',
    dag=dag,
)

# Define task dependencies
start_producer >> start_streaming >> run_batch >> run_dbt_tests >> [send_success_notification, send_failure_notification]
