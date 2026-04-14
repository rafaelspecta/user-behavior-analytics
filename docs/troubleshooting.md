# Troubleshooting

Common issues encountered when running the pipeline locally on macOS, and how to fix them.

## Quick Diagnostics

```bash
# Check which containers are running/stopped/unhealthy
docker compose ps

# Check logs for a specific service
docker compose logs <service> --tail 50

# Check all recent errors
docker compose logs --tail 20 2>&1 | grep -i "error\|exception\|failed"

# Restart a single service
docker compose restart <service>

# Nuclear option: rebuild everything from scratch
docker compose down -v && docker compose up -d
```

---

## QEMU Emulation (ARM Mac / Apple Silicon)

### Problem

Confluent Kafka and Zookeeper images (`confluentinc/cp-kafka:7.0.0`, `confluentinc/cp-zookeeper:7.0.0`) are only available for `linux/amd64`. On ARM Macs, Docker runs these under QEMU emulation, which is **2-5x slower** than native.

### Symptoms

- `zookeeper` or `kafka` marked as `unhealthy` after startup
- `dependency failed to start: container ... is unhealthy`
- Services that depend on Kafka or Zookeeper refuse to start
- Everything works after waiting longer and restarting

### Fix

Healthcheck timers must be tuned for emulation overhead. The current `docker-compose.yml` already applies these, but if you're still seeing timeouts, increase them further:

```yaml
healthcheck:
  # Zookeeper
  start_period: 120s  # was 30s — QEMU needs 1-2 minutes
  interval: 15s       # was 10s
  timeout: 10s        # was 5s
  retries: 10         # was 5

  # Kafka
  start_period: 60s   # was 30s
  interval: 15s       # was 10s
  timeout: 15s        # was 10s
  retries: 10         # was 5
```

### Root Cause

The standard Zookeeper healthcheck (`nc -z localhost 2181`) can fail under emulation because the JVM takes longer to start. The improved healthcheck (`echo srvr | nc localhost 2181 | grep Zookeeper`) waits for the JVM to be fully initialized, not just the port to be open.

---

## LocalStack Init Scripts

### Problem: S3 buckets not created

**Symptoms:**
- `streaming-job` fails with `Bucket does not exist`
- `awslocal s3 ls` returns empty list
- LocalStack healthcheck passes but buckets are missing

**Cause:** The init script at `scripts/localstack-init/init-s3-buckets.sh` doesn't have execute permissions.

**Fix:**
```bash
chmod +x scripts/localstack-init/init-s3-buckets.sh
docker compose restart localstack
```

**Explanation:** macOS bind mounts preserve host file permissions. If the script is `rw-------` (not executable), LocalStack's init mechanism silently skips it. The volume mount must **not** use `:ro` because LocalStack needs to set permissions internally.

### Problem: LocalStack healthcheck says "unhealthy"

**Symptoms:**
- `localstack` container starts but health status is `unhealthy`
- Other services that depend on LocalStack won't start

**Cause:** The healthcheck looks for `"s3"` in the health response. Early in startup, the S3 service may report as `"initializing"` instead of `"running"`.

**Fix:** The current healthcheck (`grep -q '"s3"'`) matches any status string. If you're still seeing issues:
```bash
# Check what LocalStack reports
docker exec user-behavior-analytics-localstack-1 \
  curl -s http://localhost:4566/_localstack/health | python3 -m json.tool
```

---

## Spark / Streaming Job

### Problem: "Failed to find data source: kafka"

**Symptoms:**
- `streaming-job` logs show `java.lang.ClassNotFoundException` or `Failed to find data source: kafka`

**Cause:** The Kafka connector JAR isn't available. Packages specified in `spark.jars.packages` inside Python code are not always picked up in client mode.

**Fix:** Ensure the `spark-submit` command in `docker-compose.yml` includes `--packages`:
```
--packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.3,io.delta:delta-spark_2.12:3.2.0,...
```

### Problem: Ivy2 cache permission errors

**Symptoms:**
- `FileNotFoundException` when downloading Maven packages
- `Permission denied` errors pointing to `/tmp/ivy2` or `/root/.ivy2`

**Cause:** The `ivy2-cache` Docker volume was created by root, but Spark containers run as user `spark` (uid 185).

**Fix:**
```bash
# Fix permissions on the ivy2-cache volume
docker run --rm -v user-behavior-analytics_ivy2-cache:/tmp/ivy2 --user root \
  spark:3.5.3-scala2.12-java17-python3-ubuntu \
  bash -c "chown -R 185:185 /tmp/ivy2 && chmod -R 777 /tmp/ivy2"

# Restart the streaming job
docker compose restart streaming-job
```

The `spark-submit` command uses `--conf spark.driver.extraJavaOptions=-Divy.home=/tmp/ivy2` to redirect Ivy to the writable volume.

### Problem: Spark worker can't create directories

**Symptoms:**
- `spark-worker` fails with `Failed to create directory /opt/spark/work/...`

**Cause:** Volume mounts placed inside `/opt/spark/work/` make the parent directory read-only. The worker needs to create temporary directories there.

**Fix:** Mount source code to `/opt/spark/app/src:ro` instead of `/opt/spark/work/src:ro`. Update `spark-submit` paths accordingly.

### Problem: spark-submit command parsing errors

**Symptoms:**
- `--master: command not found`
- Arguments seem to be concatenated or broken

**Cause:** YAML multiline string folding (`>` or `|`) can insert unwanted characters. Multi-line `command:` strings get interpreted incorrectly.

**Fix:** Use JSON array format for the command:
```yaml
command: ["bash", "-c", "... && /opt/spark/bin/spark-submit --master spark://spark-master:7077 ..."]
```

---

## Kafka Producer

### Problem: No logs visible

**Symptoms:**
- `docker compose logs producer` shows nothing or only startup messages
- Container is running but appears silent

**Cause:** Python buffers stdout by default in non-interactive mode. Logs are generated but held in the buffer.

**Fix:** Ensure `PYTHONUNBUFFERED=1` is set in the producer's environment:
```yaml
producer:
  environment:
    - PYTHONUNBUFFERED=1
```

### Problem: Producer can't connect to Kafka

**Symptoms:**
- `NoBrokersAvailable` error
- Connection refused to `localhost:9092`

**Cause:** Inside Docker, the producer must use the internal Kafka listener (`kafka:29092`), not the host listener (`localhost:9092`).

**Fix:** Ensure `KAFKA_BOOTSTRAP_SERVERS=kafka:29092` is set in the producer's environment.

---

## Port Conflicts

### Problem: "Bind for 0.0.0.0:XXXX failed: port is already allocated"

**Symptoms:**
- `docker compose up` fails for a specific service
- Error mentions port conflict

**Common culprits:**
| Port | Used By | Conflicts With |
| --- | --- | --- |
| 8080 | Spark Master UI | Other web services (e.g., Jenkins) |
| 9000 | Kafdrop (default) | MinIO, Portainer, PHP-FPM |
| 8081 | Airflow | Other web services |

**Fix:**
```bash
# Find what's using the port
lsof -i :9000

# Or for Docker containers specifically
docker ps --format "table {{.Names}}\t{{.Ports}}" | grep 9000
```

Then change the **host** port mapping in `docker-compose.yml` (left side of `:`):
```yaml
ports:
  - "9033:9000"  # host:container — change the left side
```

---

## Airflow

### Problem: DAGs not visible

**Symptoms:**
- Airflow UI shows no DAGs or only example DAGs
- Custom DAGs don't appear

**Cause:** DAG parsing errors, or the volume mount is incorrect.

**Fix:**
```bash
# Check DAG parsing errors
docker exec user-behavior-analytics-airflow-1 airflow dags list-import-errors

# Verify files are mounted
docker exec user-behavior-analytics-airflow-1 ls -la /opt/airflow/dags/
```

### Problem: "airflow db init" errors on restart

**Symptoms:** Warning messages about database initialization on restart.

**Explanation:** The Airflow command includes `airflow db init` which is idempotent — running it on a database that already has tables is safe and just shows warnings. These can be ignored.

---

## Complete Reset

If everything is broken beyond repair:

```bash
# Stop and remove all containers, volumes, and networks
docker compose down -v

# Remove all images (optional, forces full re-pull)
docker compose down -v --rmi all

# Fix permissions
chmod +x scripts/localstack-init/init-s3-buckets.sh
chmod +x scripts/kafka-init/init-kafka-topics.sh

# Start fresh
docker compose up -d

# Wait for services to become healthy (2-5 minutes on ARM Macs)
watch docker compose ps
```
