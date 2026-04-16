# Version Compatibility

> **Changing one version can break the entire stack.** This document explains the dependency chain and why each version was chosen.

## Table of Contents

- [Dependency Chain](#dependency-chain)
- [Version Matrix](#version-matrix)
- [Maven Packages (spark-submit --packages)](#maven-packages-spark-submit---packages)
- [Docker Images](#docker-images)
- [Future Version Considerations](#future-version-considerations)
- [References](#references)

## Dependency Chain

```
Spark 3.5.3 (Java 17, Scala 2.12, Hadoop 3.3.4)
    ├── Delta Lake 3.2.0    (must match Spark minor version)
    ├── hadoop-aws 3.3.4    (must match Spark's bundled Hadoop)
    │   └── aws-java-sdk-bundle 1.12.262 (required by hadoop-aws)
    └── spark-sql-kafka 3.5.3 (must match Spark version exactly)
```

All Maven package names use the `_2.12` suffix because Spark is built with Scala 2.12.

## Version Matrix

| Component | Version | Why This Version |
| --- | --- | --- |
| **Java** | 17 | Spark Docker image uses `java17-ubuntu`. Any Spark client (including a future custom Airflow image) must use the same Java version to avoid serialization issues. |
| **Spark** | 3.5.3 | Docker Hub image `spark:3.5.3-scala2.12-java17-python3-ubuntu`. Includes Python 3 for PySpark. |
| **Scala** | 2.12 | Determines the `_2.12` suffix on all Maven artifacts. Cannot mix with `_2.13` packages. |
| **Delta Lake** | 3.2.0 | Compatible with Spark 3.5.x. Package: `io.delta:delta-spark_2.12:3.2.0`. |
| **hadoop-aws** | 3.3.4 | **Must exactly match** the Hadoop version bundled inside Spark 3.5.3. A mismatch causes `NoSuchMethodError` at runtime. |
| **aws-java-sdk-bundle** | 1.12.262 | Required by hadoop-aws 3.3.4. Using a different version causes class-loading conflicts with S3A filesystem. |
| **spark-sql-kafka** | 3.5.3 | Kafka connector for Structured Streaming. Must match the Spark version exactly. |
| **Kafka** | 7.6.1 (CP) | Confluent Platform 7.6.1 images. Multi-arch (amd64 + arm64), so native on Apple Silicon. Bumped from 7.0.0 which was amd64-only and unusably slow under QEMU. |
| **Airflow** | 3.2.0 | Vanilla image. Uses `LocalExecutor` with PostgreSQL. Supports `@continuous` scheduling, data-aware workflows, and modern FastAPI-based UI. No authentication required (`SimpleAuthManager` with all-admins). |
| **LocalStack** | 3.8 | Pinned to avoid breaking changes. Provides S3 and Redshift emulation. |
| **Trino** | 380 | SQL query engine. Currently starts but has no catalog configured (see [roadmap](roadmap.md)). |
| **PostgreSQL** | 13 | Airflow metadata database. |

## Maven Packages (spark-submit --packages)

These are the packages passed to `spark-submit` for the streaming job:

```
org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.3
io.delta:delta-spark_2.12:3.2.0
org.apache.hadoop:hadoop-aws:3.3.4
com.amazonaws:aws-java-sdk-bundle:1.12.262
```

The batch job uses the same packages minus `spark-sql-kafka` (it doesn't read from Kafka).

## Docker Images

| Service | Image | Architecture | Notes |
| --- | --- | --- | --- |
| Zookeeper | `confluentinc/cp-zookeeper:7.6.1` | multi-arch | Native on amd64 and arm64 |
| Kafka | `confluentinc/cp-kafka:7.6.1` | multi-arch | Native on amd64 and arm64 |
| Kafka Init | `confluentinc/cp-kafka:7.6.1` | multi-arch | One-shot topic creation |
| Kafdrop | `obsidiandynamics/kafdrop` | multi-arch | Kafka Web UI |
| Spark Master | `spark:3.5.3-scala2.12-java17-python3-ubuntu` | multi-arch | Includes Python 3 for PySpark |
| Spark Worker | `spark:3.5.3-scala2.12-java17-python3-ubuntu` | multi-arch | — |
| Streaming Job | `spark:3.5.3-scala2.12-java17-python3-ubuntu` | multi-arch | Runs spark-submit in client mode |
| Producer | Custom (`docker/producer/Dockerfile`) | multi-arch | Python 3.11-slim + kafka-python + faker |
| Airflow | `apache/airflow:3.2.0` | multi-arch | Vanilla image with Python 3.12, no Spark/dbt |
| PostgreSQL | `postgres:13` | multi-arch | — |
| Trino | `trinodb/trino:380` | multi-arch | — |
| LocalStack | `localstack/localstack:3.8` | multi-arch | — |

## Future Version Considerations

### Custom Airflow Image (deferred)

When building a custom Airflow image for Architecture B (Airflow-orchestrated), the following versions are critical:

| Component | Version | Reason |
| --- | --- | --- |
| Airflow base image | `apache/airflow:3.2.0` | Already includes Python 3.12. For dbt-spark, add `pip install dbt-spark[PyHive]`. |
| Java in Airflow | 17 | Must match Spark cluster to avoid serialization issues |
| Spark binaries | 3.5.3 | Needed for `spark-submit` inside the Airflow container |
| dbt-spark | 1.4.0 | Requires Python 3.8+, PyHive extras for Thrift connection |

See the reference Dockerfile and requirements in [roadmap.md](roadmap.md) under "Custom Airflow Image".

## References

- [Delta Lake Releases](https://docs.delta.io/latest/releases.html)
- [Hadoop AWS Compatibility](https://stackoverflow.com/questions/77327653/hadoop-common-hadoop-aws-aws-java-sdk-bundle-version-compatibility)
- [Maven hadoop-aws 3.3.4 Dependencies](https://mvnrepository.com/artifact/org.apache.hadoop/hadoop-aws/3.3.4)
- [Spark Docker Hub](https://hub.docker.com/r/apache/spark)
- [Airflow Docker Hub Tags](https://hub.docker.com/r/apache/airflow)
- [dbt Python Compatibility](https://docs.getdbt.com/faqs/Core/install-python-compatibility)
- [dbt Spark Setup](https://docs.getdbt.com/docs/core/connect-data-platform/spark-setup)
