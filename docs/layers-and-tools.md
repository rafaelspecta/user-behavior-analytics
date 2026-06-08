# Layers & Tools

The Layer View (/layers) organizes the playground into 11 architecture layers.
Each layer lists available tools — implemented (solid) and planned (dashed).

Click a scenario on the left sidebar to see which tools it activates per layer.

## Ingestion

| Tool | Status | Description |
|---|---|---|
| Apache Kafka | Implemented | Real-time event streaming and message broker |
| Debezium + Connect | Future | Change Data Capture from relational databases |
| Redpanda | Future | Kafka-API-compatible streaming platform, no ZooKeeper |

## Stream Processing

| Tool | Status | Description |
|---|---|---|
| Spark Structured Streaming | Implemented | Micro-batch stream processing with SQL and DataFrame APIs |
| Apache Flink | Future | Distributed stream processing with exactly-once semantics |
| RisingWave | Future | Streaming database with PostgreSQL wire compatibility |

## Storage Format

| Tool | Status | Description |
|---|---|---|
| Delta Lake | Implemented | ACID transactions, time travel, schema enforcement |
| Apache Hudi | Implemented | Upserts, incremental processing, record-level indexing |
| Apache Iceberg | Future | High-performance table format with partition evolution |

## Object Storage

| Tool | Status | Description |
|---|---|---|
| LocalStack S3 | Implemented | Local AWS S3 emulation for development |
| MinIO | Future | S3-compatible object storage for multi-cloud simulations |

## Orchestration

| Tool | Status | Description |
|---|---|---|
| Manual (docker compose exec) | Implemented | No orchestrator — run batch jobs manually |
| Apache Airflow | Implemented | DAG-based scheduling, streaming supervision, batch orchestration |
| Prefect | Future | Modern Pythonic workflow orchestration with dynamic DAGs |
| Dagster | Future | Asset-based orchestration with software-defined assets |

## Query Engine

| Tool | Status | Description |
|---|---|---|
| spark-sql | Implemented | Spark SQL REPL for direct Delta table queries |
| Trino | Implemented | Distributed SQL query engine with Delta Lake connector |
| Spark Thrift Server | Implemented | JDBC/ODBC SQL endpoint for BI tools and dbt |
| DuckDB | Future | In-process OLAP engine, zero config, reads Parquet/Delta directly |

## Transform

| Tool | Status | Description |
|---|---|---|
| spark-submit | Implemented | Spark batch jobs for Silver → Gold aggregations |
| Airflow DAGs | Implemented | Orchestrated batch jobs with verification steps |
| dbt | Future | Analytics engineering — SQL models with testing and docs |

## BI / Dashboard

| Tool | Status | Description |
|---|---|---|
| Metabase | Future | Self-serve BI — ask questions without SQL, embeddable dashboards |
| Apache Superset | Future | Full-featured data exploration and visualization platform |
| Grafana | Future | Observability dashboards with plugin ecosystem |

## Governance / Lineage

| Tool | Status | Description |
|---|---|---|
| OpenLineage + Marquez | Future | Open standard for data lineage collection and visualization |
| DataHub | Future | End-to-end metadata platform with 50+ integrations |
| OpenMetadata | Future | Unified metadata, quality, and observability platform |

## Data Quality

| Tool | Status | Description |
|---|---|---|
| Great Expectations | Future | Expectations-as-code — profiling, validation, auto-generated docs |
| Soda Core | Future | Declarative data quality checks in YAML |

## Exploration

| Tool | Status | Description |
|---|---|---|
| JupyterLab | Future | Interactive notebooks with PySpark kernel and 40+ languages |
| Apache Zeppelin | Future | Multi-purpose notebook with built-in charts and Spark support |
