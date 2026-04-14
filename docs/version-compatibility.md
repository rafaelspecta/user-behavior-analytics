# Version Compatibility

> **Changing one version can break the entire stack.** This document explains the dependency chain and why each version was chosen.

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
| **Kafka** | 7.0.0 (CP) | Confluent Platform 7.0.0 images. No native ARM64 images — runs under QEMU emulation on Apple Silicon. |
| **Airflow** | 2.3.0 | Vanilla image (no custom build). Uses `LocalExecutor` with PostgreSQL. Future upgrade to 2.4+ enables `@continuous` scheduling. |
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
| Zookeeper | `confluentinc/cp-zookeeper:7.0.0` | amd64 only | Runs under QEMU on ARM Macs |
| Kafka | `confluentinc/cp-kafka:7.0.0` | amd64 only | Runs under QEMU on ARM Macs |
| Kafka Init | `confluentinc/cp-kafka:7.0.0` | amd64 only | One-shot topic creation |
| Kafdrop | `obsidiandynamics/kafdrop` | multi-arch | Kafka Web UI |
| Spark Master | `spark:3.5.3-scala2.12-java17-python3-ubuntu` | multi-arch | Includes Python 3 for PySpark |
| Spark Worker | `spark:3.5.3-scala2.12-java17-python3-ubuntu` | multi-arch | — |
| Streaming Job | `spark:3.5.3-scala2.12-java17-python3-ubuntu` | multi-arch | Runs spark-submit in client mode |
| Producer | Custom (`docker/producer/Dockerfile`) | multi-arch | Python 3.11-slim + kafka-python + faker |
| Airflow | `apache/airflow:2.3.0` | multi-arch | Vanilla image, no Spark/dbt |
| PostgreSQL | `postgres:13` | multi-arch | — |
| Trino | `trinodb/trino:380` | multi-arch | — |
| LocalStack | `localstack/localstack:3.8` | multi-arch | — |

## Future Version Considerations

### Custom Airflow Image (deferred)

When building a custom Airflow image for Architecture B (Airflow-orchestrated), the following versions are critical:

| Component | Version | Reason |
| --- | --- | --- |
| Airflow base image | `apache/airflow:2.3.0-python3.8` | Python 3.8 required for dbt-spark 1.4.0 (default image uses Python 3.7) |
| Java in Airflow | 17 | Must match Spark cluster to avoid serialization issues |
| Spark binaries | 3.5.3 | Needed for `spark-submit` inside the Airflow container |
| dbt-spark | 1.4.0 | Requires Python 3.8+, PyHive extras for Thrift connection |

See the reference Dockerfile and requirements in [roadmap.md](roadmap.md) under "Custom Airflow Image".

### Airflow 2.4+ Upgrade

Upgrading to Airflow 2.4+ enables `@continuous` scheduling for streaming job orchestration. See [airflow-migration-plan.md](airflow-migration-plan.md) for the migration plan.

## References

- [Delta Lake Releases](https://docs.delta.io/latest/releases.html)
- [Hadoop AWS Compatibility](https://stackoverflow.com/questions/77327653/hadoop-common-hadoop-aws-aws-java-sdk-bundle-version-compatibility)
- [Maven hadoop-aws 3.3.4 Dependencies](https://mvnrepository.com/artifact/org.apache.hadoop/hadoop-aws/3.3.4)
- [Spark Docker Hub](https://hub.docker.com/r/apache/spark)
- [Airflow Docker Hub Tags](https://hub.docker.com/r/apache/airflow)
- [dbt Python Compatibility](https://docs.getdbt.com/faqs/Core/install-python-compatibility)
- [dbt Spark Setup](https://docs.getdbt.com/docs/core/connect-data-platform/spark-setup)
