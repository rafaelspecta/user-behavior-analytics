# Roadmap: Data Architecture Playground

## Vision

This project aims to become a **Data Architecture Playground and Laboratory** where students can explore, compare, and compose different Modern Data Architecture patterns using real, running infrastructure -- all locally with Docker.

Rather than learning about data architectures in theory, students will be able to:

- **Start any architecture scenario** with a single command
- **Compare approaches** side-by-side (e.g., Delta Lake vs Hudi, Spark vs Trino)
- **Swap components** to understand trade-offs (e.g., switch the compute engine, change the storage format)
- **Create custom compositions** by mixing and matching components

---

## Current State

**Implemented: Scenario 1 (Delta Lake + Spark) -- minus Redshift sync**

```
Producer -> Kafka -> Spark Streaming -> Delta Lake Silver (S3) -> Spark Batch -> Delta Lake Gold (S3)
```

The pipeline runs end-to-end locally with Docker Compose. Events are produced, streamed, stored in Delta Lake, and aggregated from Silver to Gold layers. All steps are visible via web UIs (Kafdrop, Spark Master UI, Airflow).

---

## Deferred Items

Items not covered by the current implementation, organized by category.

### Summary


| Item                            | Category       | Blocked By                                                      | Effort |
| ------------------------------- | -------------- | --------------------------------------------------------------- | ------ |
| Redshift sync                   | Scenario 1     | No JDBC driver in Spark image                                   | Medium |
| Delta table compaction (ZORDER) | Scenario 1     | OSS Delta Lake limitation                                       | Low    |
| Trino catalog configuration     | Scenario 2     | Deleted `hive.properties`, no Delta connector                   | Medium |
| Spark Thrift Server             | Scenario 2     | Not deployed as Docker service                                  | Medium |
| dbt integration                 | Scenario 2     | Thrift Server missing, `profiles.yml` broken, dbt not installed | High   |
| Hudi storage format             | Scenario 3     | Code commented out, Hudi JARs not configured                    | Medium |
| Docker Compose profiles         | Infrastructure | Not implemented                                                 | Medium |
| Custom Airflow image            | Infrastructure | Requires Java 17 + Spark in image                               | High   |
| Airflow-orchestrated Spark      | Infrastructure | Requires custom Airflow image                                   | High   |
| Airflow 2.4+ migration          | Infrastructure | Depends on custom Airflow image                                 | Medium |


### Redshift Sync

**Category:** Scenario 1 completion
**Current state:** `sync_to_redshift()` in `src/batch/batch_job.py` is wrapped in a conditional and skipped when `REDSHIFT_URL` is not configured.
**What's needed:**

- Add PostgreSQL JDBC JAR to Spark packages
- Configure LocalStack Redshift endpoint properly
- Verify JDBC connectivity from Spark to LocalStack Redshift
- Test write from Gold layer to Redshift tables
**Reference:** The `.env` file already has Redshift connection variables defined.

### Delta Table Compaction (ZORDER)

**Category:** Scenario 1 optimization
**Current state:** `compact_delta_tables()` in `src/batch/batch_job.py` uses `OPTIMIZE ... ZORDER BY` which is a Databricks-only feature not available in OSS Delta Lake. The call is skipped.
**What's needed:**

- Replace ZORDER with plain `OPTIMIZE` (supported in Delta Lake 3.x OSS)
- Or remove ZORDER and rely on `VACUUM` only for storage management
- Consider adding partition-level compaction strategies

### Trino Catalog Configuration

**Category:** Scenario 2 enablement
**Current state:** Trino starts via Docker Compose (port 8082) but has no catalogs. The original `config/trino/catalog/hive.properties` was deleted from git.
**What's needed:**

- Create `config/trino/catalog/delta.properties` with Delta Lake connector configuration
- Configure S3A endpoint, credentials, and path-style access for LocalStack
- Test querying Delta Lake Silver and Gold tables via Trino CLI or UI
**Reference:** Trino config is mounted from `./config/trino` to `/etc/trino`.

### Spark Thrift Server

**Category:** Scenario 2 enablement
**Current state:** Not deployed. Required by dbt-spark for thrift connection method.
**What's needed:**

- Add `spark-thrift` service to `docker-compose.yml` (see `.aidocs/containerization-plan.md` section 2.3 for full spec)
- Configure with Delta Lake extensions and S3A access
- Add healthcheck on port 10000
- Expose port 10000 for dbt and external tools

### dbt Integration

**Category:** Scenario 2 completion
**Current state:** dbt directory exists with models and tests but: `profiles.yml` has duplicate YAML keys, `sources.yml` is missing, test files contain multiple queries, and dbt-spark is not installed anywhere.
**What's needed:**

- Fix `dbt/profiles.yml` (remove duplicate keys, use env vars for Spark Thrift connection)
- Create `dbt/models/staging/sources.yml`
- Split multi-query test files into individual test files
- Ensure dbt-spark is available (either in custom Airflow image or a dedicated dbt container)
- Test `dbt run` and `dbt test` against Spark Thrift Server
**Depends on:** Spark Thrift Server

### Hudi Storage Format

**Category:** Scenario 3 enablement
**Current state:** Hudi writeStream code is commented out in `src/streaming/streaming_job.py`. The producer and Kafka infrastructure are shared and already working.
**What's needed:**

- Uncomment Hudi writeStream configuration in `streaming_job.py`
- Add Hudi Maven packages (`hudi-spark3.5-bundle_2.12`) to `spark.jars.packages`
- Create a separate S3 bucket for Hudi data (or use a path prefix)
- Adjust batch job to read from Hudi tables
- Test Hudi timeline and compaction features

### Docker Compose Profiles

**Category:** Infrastructure
**Current state:** All services start together with `docker compose up -d`. No way to selectively enable architecture scenarios.
**What's needed:**

- Define profiles: `core` (Kafka, Spark, S3, Airflow), `scenario-1` (Delta + Spark), `scenario-2` (Delta + Trino + dbt), `scenario-3` (Hudi)
- Assign services to profiles (e.g., `spark-thrift` only in `scenario-2`)
- Document profile usage: `docker compose --profile scenario-1 up -d`
- Ensure shared infrastructure (Kafka, Spark cluster, S3) is in `core` profile

### Custom Airflow Image

**Category:** Infrastructure
**Current state:** Using vanilla `apache/airflow:2.3.0`. DAGs use PythonOperator workaround because Airflow cannot run spark-submit or kafka-python.
**What's needed:**

- Build custom Dockerfile based on `apache/airflow:2.3.0-python3.8` (Python 3.8 required for dbt-spark)
- Install Java 17 (must match Spark cluster), wget, netcat
- Download and install Spark binaries for `spark-submit`
- Install Python packages: kafka-python, faker, dbt-spark, python-dotenv
- Full spec in `.aidocs/containerization-plan.md` sections 3.1 and 3.2
**Depends on:** This is a prerequisite for Airflow-orchestrated Spark and dbt

### Airflow 2.4+ Migration

**Category:** Infrastructure
**Current state:** Running Airflow 2.3.0. Streaming job orchestration uses a separate docker-compose service.
**What's needed:**

- Upgrade to Airflow 2.4.3 for `@continuous` scheduling support
- Run `airflow db migrate` on upgrade
- Replace streaming job docker-compose service with Airflow-orchestrated `@continuous` DAG
- Full spec in `.aidocs/airflow-migration-plan.md`
**Depends on:** Custom Airflow image, Spark Thrift Server (for dbt DAGs)

---

## Architecture Scenario Roadmap

### Scenario 1: Delta Lake + Spark (Current)

```mermaid
graph TD
    A[Kafka Producer] --> B[Kafka]
    B --> C[Spark Streaming]
    C --> D["Delta Lake (Silver)"]
    D --> E["Spark Batch"]
    E --> F["Delta Lake (Gold)"]
    F --> G["Redshift (deferred)"]
    G --> H[BI Tools]
```



**Status:** Working (minus Redshift sync)


| Milestone                                                  | Status   | Description                                         |
| ---------------------------------------------------------- | -------- | --------------------------------------------------- |
| Core pipeline (Producer -> Kafka -> Spark -> Delta Silver) | Done     | Events flowing end-to-end                           |
| Batch aggregation (Silver -> Gold)                         | Done     | On-demand via `docker compose exec`                 |
| Redshift sync (Gold -> Redshift)                           | Deferred | Needs JDBC driver and LocalStack Redshift config    |
| BI Tools integration                                       | Future   | Depends on Redshift; could add Metabase or Superset |


### Scenario 2: Delta Lake + Trino + dbt

```mermaid
graph TD
    A[Kafka Producer] --> B[Kafka]
    B --> C[Spark Streaming]
    C --> D["Delta Lake (Silver)"]
    D --> E[Trino]
    E --> F[dbt]
    F --> G["Delta Lake (Gold)"]
    G --> H["Redshift (deferred)"]
    H --> I[BI Tools]
```



**Status:** Not started -- Trino starts but has no catalog; dbt not configured


| Milestone                    | Status      | Description                                                |
| ---------------------------- | ----------- | ---------------------------------------------------------- |
| Trino catalog for Delta Lake | Not started | Create `delta.properties` with S3A/Delta connector         |
| Spark Thrift Server          | Not started | Deploy as Docker service for dbt connection                |
| dbt models and tests         | Not started | Fix `profiles.yml`, install dbt-spark                      |
| dbt-driven Gold layer        | Not started | Use dbt to transform Silver -> Gold instead of Spark batch |
| Redshift sync                | Not started | Same as Scenario 1                                         |


### Scenario 3: Hudi instead of Delta Lake

```mermaid
graph TD
    A[Kafka Producer] --> B[Kafka]
    B --> C[Spark Streaming]
    C --> D["Hudi (Silver)"]
    D --> E[Spark Batch]
    E --> F["Hudi (Gold)"]
    F --> G[...]
```



**Status:** Not started -- code is commented out


| Milestone                | Status      | Description                                                    |
| ------------------------ | ----------- | -------------------------------------------------------------- |
| Hudi streaming write     | Not started | Uncomment and configure Hudi writeStream in `streaming_job.py` |
| Hudi Maven packages      | Not started | Add `hudi-spark3.5-bundle_2.12` to packages                    |
| Hudi batch aggregation   | Not started | Adapt batch job to read/write Hudi tables                      |
| Hudi timeline management | Not started | Configure compaction strategy, explore timeline API            |


### Future Scenarios (Ideas)

These are additional architecture patterns that could be added to expand the playground:


| Scenario                         | Description                                               | New Components                                              |
| -------------------------------- | --------------------------------------------------------- | ----------------------------------------------------------- |
| **Iceberg**                      | Apache Iceberg as an alternative lakehouse format         | Iceberg Spark runtime, Iceberg catalog                      |
| **Flink instead of Spark**       | Replace Spark Streaming with Apache Flink                 | Flink JobManager, TaskManager, Flink SQL                    |
| **Debezium CDC**                 | Change Data Capture from a relational database            | Debezium, Kafka Connect, source database (MySQL/Postgres)   |
| **Real-time dashboards**         | Live dashboards on streaming data                         | Apache Superset or Metabase, connected to Trino             |
| **Data mesh**                    | Multiple domain-specific pipelines sharing infrastructure | Multiple producers, domain-specific schemas, data contracts |
| **Lakehouse with Unity Catalog** | Centralized governance and catalog                        | Unity Catalog (OSS), or Polaris catalog                     |
| **Stream processing patterns**   | Windowing, joins, late data handling                      | Enhanced streaming jobs, watermarking                       |
| **Data quality framework**       | Great Expectations or Soda for data validation            | Great Expectations container, quality reports UI            |
| **ML feature store**             | Feature engineering pipeline feeding an ML store          | Feast, feature tables in Gold layer                         |
| **Multi-cloud simulation**       | MinIO instead of LocalStack for S3                        | MinIO, multi-region replication                             |


---

## Implementation Priority

Recommended order for expanding the playground beyond the current state:

```mermaid
graph TD
    Current["Scenario 1: Delta + Spark\n(DONE)"] --> Profiles["Docker Compose Profiles"]
    Profiles --> S2["Scenario 2: Trino + dbt"]
    Profiles --> S3["Scenario 3: Hudi"]
    S2 --> CustomAirflow["Custom Airflow Image"]
    CustomAirflow --> AirflowMigration["Airflow 2.4+ Migration"]
    S2 --> Dashboards["Real-time Dashboards\n(Superset/Metabase)"]
    S3 --> Iceberg["Scenario: Iceberg"]
    Current --> Redshift["Redshift Sync"]
    CustomAirflow --> Flink["Scenario: Flink"]
    Dashboards --> DataMesh["Scenario: Data Mesh"]
```



The recommended approach is:

1. **Docker Compose Profiles** first -- enables selective architecture startup
2. **Scenario 2 (Trino + dbt)** -- most requested by data engineering students
3. **Custom Airflow Image** -- unlocks Airflow-orchestrated Spark jobs
4. **Scenario 3 (Hudi)** -- introduces lakehouse format comparison
5. **Future scenarios** -- based on student interest and course curriculum

