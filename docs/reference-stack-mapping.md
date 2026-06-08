# Reference Stack Mapping

The Layer View (/layers) also compares the open-source playground stack against
three all-in-one proprietary platforms. Check a platform above the table to see
which tool it uses for each layer.

## Databricks

| Layer | Databricks Tool |
|---|---|
| Ingestion | Auto Loader / Delta Live Tables |
| Stream Processing | Spark Structured Streaming (Photon) |
| Storage Format | Delta Lake |
| Object Storage | DBFS |
| Orchestration | Databricks Workflows |
| Query Engine | Databricks SQL (Photon) |
| Transform | Delta Live Tables / Notebooks |
| BI / Dashboard | Databricks Dashboards / AI-BI |
| Governance / Lineage | Unity Catalog |
| Data Quality | Delta Live Tables Expectations |
| Exploration | Databricks Notebooks |

## Microsoft Fabric

| Layer | Microsoft Fabric Tool |
|---|---|
| Ingestion | Data Factory / Eventstreams |
| Stream Processing | Eventstreams (Real-Time Intelligence) |
| Storage Format | OneLake (Delta-Parquet) |
| Object Storage | OneLake |
| Orchestration | Data Factory Pipelines |
| Query Engine | SQL Analytics Endpoint |
| Transform | Dataflows Gen2 / Notebooks |
| BI / Dashboard | Power BI |
| Governance / Lineage | Microsoft Purview |
| Data Quality | Purview Data Quality |
| Exploration | Fabric Notebooks |

## AWS

| Layer | AWS Tool |
|---|---|
| Ingestion | Kinesis / MSK |
| Stream Processing | Kinesis Data Analytics (Flink) |
| Storage Format | S3 + Glue Catalog |
| Object Storage | S3 |
| Orchestration | MWAA / Step Functions |
| Query Engine | Athena |
| Transform | Glue ETL / EMR |
| BI / Dashboard | QuickSight |
| Governance / Lineage | Glue Catalog / Lake Formation |
| Data Quality | Glue Data Quality |
| Exploration | SageMaker / EMR Studio |
