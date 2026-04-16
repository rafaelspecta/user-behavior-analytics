# Custom Airflow image for Architecture B (Hybrid with Airflow).
#
# Adds to the base image:
#   - OpenJDK 17              -- required by spark-submit, matches Spark cluster (java17-ubuntu)
#   - Apache Spark 3.5.3       -- provides spark-submit binary, matches cluster version
#   - Python packages          -- producer/faker utilities and Airflow Spark provider
#   - docker group membership  -- lets uid 50000 (airflow) talk to /var/run/docker.sock
#   - /tmp/ivy2 pre-created    -- placeholder for the shared ivy2-cache volume
#
# Spark binaries are copied from the official Spark image (same version as the
# cluster) via a multi-stage build. This avoids downloading from archive.apache.org
# which is flaky and slow from many regions, and guarantees version parity.
#
# See docs/infrastructure.md and docs/troubleshooting.md for details.

FROM spark:3.5.3-scala2.12-java17-python3-ubuntu AS spark-src

FROM apache/airflow:3.2.0

USER root

# Utilities:
#   - openjdk-17-jdk-headless : JVM for spark-submit (the Spark image ships only a JRE layout)
#   - curl                    : used by the supervision DAG to talk to /var/run/docker.sock
#   - netcat-openbsd          : readiness probes
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        openjdk-17-jdk-headless \
        curl \
        netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# JAVA_HOME path differs between amd64 and arm64 Debian packages. Resolve it at
# build time so the image works on both architectures (Apple Silicon + Linux x86_64).
RUN JAVA_HOME_PATH="$(dirname "$(dirname "$(readlink -f "$(which javac)")")")" \
    && ln -sfn "${JAVA_HOME_PATH}" /usr/lib/jvm/default-java
ENV JAVA_HOME=/usr/lib/jvm/default-java
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# Copy Spark 3.5.3 from the official image. Identical bits to the Spark master
# and worker containers, so --packages coordinates resolved on the cluster also
# resolve from Airflow-launched spark-submit without surprises.
COPY --from=spark-src /opt/spark /opt/spark
ENV SPARK_HOME=/opt/spark
ENV PATH="${SPARK_HOME}/bin:${PATH}"

# Create a docker group and add the airflow user to it so the supervision DAG
# can talk to /var/run/docker.sock when the socket is bind-mounted from the host.
# GID 999 matches the conventional docker group on Debian/Ubuntu hosts. On macOS
# Docker Desktop the socket is usually accessible regardless; on Linux hosts
# whose docker GID differs, use `group_add: ["<gid>"]` on the airflow service
# (see docs/troubleshooting.md).
RUN groupadd -f -g 999 docker && usermod -aG docker airflow

# Pre-create /tmp/ivy2 with world-writable perms so the directory exists even
# before the ivy2-cache volume mount lands on top. The actual permission fix
# for the shared volume is applied by the ivy2-cache-init service in
# docker-compose.yml on every `up`.
RUN mkdir -p /tmp/ivy2 && chmod 777 /tmp/ivy2

USER airflow

# Python dependencies. dbt-spark[PyHive] intentionally omitted -- deferred to
# Scenario 2 (Trino + dbt) per docs/roadmap.md.
RUN pip install --no-cache-dir \
        kafka-python \
        faker \
        python-dotenv \
        apache-airflow-providers-apache-spark
