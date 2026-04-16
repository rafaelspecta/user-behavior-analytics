"""
Clickstream Streaming Supervisor DAG (Architecture B).

Monitors the long-running Spark Structured Streaming application and restarts
the underlying Docker container when the app has disappeared from the Spark
Master. This is a *supervision* DAG -- it does not submit the streaming job
itself, because PySpark on Spark Standalone does not support --deploy-mode
cluster and client mode would block the Airflow task indefinitely
(see docs/architecture-guide.md and docs/roadmap.md for the full explanation).

Task flow (see docs/infrastructure.md for the diagram):

  check_streaming_health (PythonOperator)
      |-- SUCCESS: app alive -----------------------> verify_recovery
      |-- FAILED:  app not found --> restart_streaming_container --> verify_recovery

`restart_streaming_container` uses the Docker Engine API over the Unix socket
bind-mounted at /var/run/docker.sock. No Docker CLI is installed in the image.
"""

from datetime import datetime, timedelta

from airflow.sdk import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from airflow.utils.trigger_rule import TriggerRule

SPARK_MASTER_URL = "http://spark-master:8080/json/"
DOCKER_SOCKET = "/var/run/docker.sock"
STREAMING_APP_NAME_FRAGMENT = "streaming"
STREAMING_CONTAINER_NAME_FRAGMENT = "streaming-job"
# Chosen because Spark driver launch on Standalone typically takes 30-90s even
# with a populated ivy2-cache. A shorter wait produces false negatives during
# normal startup.
VERIFY_RECOVERY_SLEEP_SECONDS = 90


def check_streaming_health():
    """Query the Spark Master REST API and fail if no matching streaming app is active.

    Raising any exception here fails the task, which causes
    `restart_streaming_container` (trigger_rule=ALL_FAILED) to fire. A clean
    return signals the supervisor that the streaming app is alive.
    """
    import json
    import urllib.request

    with urllib.request.urlopen(SPARK_MASTER_URL, timeout=10) as response:
        data = json.load(response)

    apps = data.get("activeapps", [])
    matching = [a for a in apps if STREAMING_APP_NAME_FRAGMENT in a.get("name", "").lower()]

    print(f"Active Spark applications: {len(apps)}")
    for app in apps:
        print(f"  - {app.get('name')} (state: {app.get('state')})")

    if not matching:
        raise RuntimeError(
            "No active Spark application matching "
            f"'{STREAMING_APP_NAME_FRAGMENT}' found -- streaming job is dead."
        )

    print(f"Streaming app is alive: {matching[0].get('name')} "
          f"(state: {matching[0].get('state')})")


default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "retries": 0,
}

dag = DAG(
    "clickstream_streaming_supervisor",
    default_args=default_args,
    description=(
        "Monitors the Spark streaming app and restarts the streaming-job "
        "container via the Docker Engine API when the app is missing."
    ),
    schedule="*/5 * * * *",
    start_date=datetime(2026, 4, 14, 0, 10, 0),
    catchup=False,
    max_active_runs=1,
    tags=["architecture-b", "streaming", "supervision"],
)

check_streaming = PythonOperator(
    task_id="check_streaming_health",
    python_callable=check_streaming_health,
    dag=dag,
)

# Bash pipeline uses `set -euo pipefail` so any failing step (curl, json parse,
# restart call) produces a clear error in the Airflow task log instead of a
# silent success on a partially-completed pipe.
restart_streaming = BashOperator(
    task_id="restart_streaming_container",
    trigger_rule=TriggerRule.ALL_FAILED,
    bash_command=f"""
set -euo pipefail

echo "Looking up streaming-job container via Docker Engine API..."
CONTAINER_ID=$(curl -sf --unix-socket {DOCKER_SOCKET} \
    'http://localhost/containers/json?all=true' | \
  python3 -c "
import sys, json
cs = json.load(sys.stdin)
match = next(
    (c['Id'] for c in cs
     if any('{STREAMING_CONTAINER_NAME_FRAGMENT}' in n for n in c.get('Names', []))),
    ''
)
print(match)
")

if [ -z "$CONTAINER_ID" ]; then
  echo "ERROR: no container whose name contains '{STREAMING_CONTAINER_NAME_FRAGMENT}' found"
  exit 1
fi

echo "Restarting container $CONTAINER_ID"
curl -sf --unix-socket {DOCKER_SOCKET} \
    -X POST "http://localhost/containers/$CONTAINER_ID/restart"
echo "Restart request accepted for $CONTAINER_ID"
""",
    dag=dag,
)

verify_recovery = BashOperator(
    task_id="verify_recovery",
    trigger_rule=TriggerRule.ALL_DONE,
    bash_command=f"""
set -euo pipefail

echo "Waiting {VERIFY_RECOVERY_SLEEP_SECONDS}s for Spark driver to register..."
sleep {VERIFY_RECOVERY_SLEEP_SECONDS}

echo "Re-checking Spark Master for active streaming application..."
curl -sf {SPARK_MASTER_URL} | python3 -c "
import sys, json
data = json.load(sys.stdin)
apps = data.get('activeapps', [])
match = [a for a in apps if '{STREAMING_APP_NAME_FRAGMENT}' in a.get('name', '').lower()]
if match:
    print(f'Recovery OK: {{match[0][\"name\"]}} is {{match[0][\"state\"]}}')
    sys.exit(0)
print(f'WARNING: no streaming app visible after {VERIFY_RECOVERY_SLEEP_SECONDS}s wait')
sys.exit(1)
"
""",
    dag=dag,
)

check_streaming >> restart_streaming >> verify_recovery
check_streaming >> verify_recovery
