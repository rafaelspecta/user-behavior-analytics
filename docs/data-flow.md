# Data Flow

This document describes how data *moves* through the pipeline: the journey an event takes from being generated in the producer, through Kafka and Spark, until it lands as an aggregated Gold-layer Delta table. Each stage includes the transformation applied, the resulting output location, and the exact commands to inspect what happened at that point.

For how the data *sits at rest* once it arrives (S3 bucket layout, S3A configuration, Delta Lake features, and the full Spark SQL → Delta → Parquet → S3A → S3 storage stack), see [data-storage.md](data-storage.md).

## Table of Contents

- [Overview](#overview)
  - [End-to-End Flow](#end-to-end-flow)
  - [Medallion Architecture](#medallion-architecture)
- [Pipeline Stages](#pipeline-stages)
  - [Stage 1: Event Generation (Producer)](#stage-1-event-generation-producer)
  - [Stage 2: Kafka (Bronze Layer)](#stage-2-kafka-bronze-layer)
  - [Stage 3: Stream Processing (Silver Layer)](#stage-3-stream-processing-silver-layer)
  - [Stage 4: Batch Processing (Gold Layer)](#stage-4-batch-processing-gold-layer)
- [See also](#see-also)

## Overview

### End-to-End Flow

```mermaid
graph LR
    subgraph "1. Generation"
        P[Producer<br>Python + Faker]
    end
    subgraph "2. Ingestion"
        K[Kafka<br>clickstream-events<br>3 partitions]
    end
    subgraph "3. Stream Processing"
        SS[Spark Structured<br>Streaming<br>1-min micro-batches]
    end
    subgraph "4. Silver Layer"
        S["Delta Lake<br>s3://...-silver/<br>clickstream/delta/"]
    end
    subgraph "5. Batch Processing"
        B[Spark Batch Job]
    end
    subgraph "6. Gold Layer"
        DA["Daily User Activity<br>s3://...-gold/<br>daily_user_activity/"]
        PP["Product Performance<br>s3://...-gold/<br>product_performance/"]
    end

    P --> K --> SS --> S --> B
    B --> DA
    B --> PP
```



### Medallion Architecture

The pipeline follows the **Medallion Architecture** pattern with three layers:


| Layer      | Location                                                  | Format               | Contents                                    |
| ---------- | --------------------------------------------------------- | -------------------- | ------------------------------------------- |
| **Bronze** | Kafka topic `clickstream-events`                          | JSON                 | Raw events as produced (no transformation)  |
| **Silver** | `s3a://user-behavior-analytics-silver/clickstream/delta/` | Delta Lake (Parquet) | Parsed JSON with processing timestamp added |
| **Gold**   | `s3a://user-behavior-analytics-gold/`                     | Delta Lake (Parquet) | Aggregated analytics tables                 |


## Pipeline Stages

### Stage 1: Event Generation (Producer)

The producer generates synthetic clickstream events at a configurable rate (default: 1 event/second).

#### Event Schema

```json
{
  "event_id": "uuid",
  "user_id": "uuid",
  "session_id": "uuid",
  "event_type": "page_view | product_view | add_to_cart | checkout | purchase",
  "product_id": "laptop | smartphone | headphones | tablet | smartwatch",
  "timestamp": "2026-04-14T21:30:00.000000",
  "page_url": "https://example.com/...",
  "user_agent": "Mozilla/5.0 ...",
  "ip_address": "192.168.1.1",
  "device_type": "mobile | desktop | tablet",
  "browser": "Chrome ...",
  "os": "Windows | macOS | Linux | iOS | Android",
  "country": "US",
  "referrer": "https://google.com/...",
  "screen_resolution": "1920x1080",
  "time_on_page": 42,
  "scroll_depth": 75,
  "click_coordinates": { "x": 500, "y": 300 }
}
```

#### How to inspect

```bash
# Check producer is generating events
docker compose logs producer --tail 5

# Check event count
docker compose logs producer 2>&1 | tail -1
```

### Stage 2: Kafka (Bronze Layer)

Events are serialized as JSON and sent to the `clickstream-events` topic (3 partitions, replication factor 1).

A second topic `clickstream-errors` (1 partition) exists for dead-letter messages but is not currently used.

#### How to inspect

```bash
# Via Kafdrop Web UI
open http://localhost:9033/topic/clickstream-events

# Via Kafka CLI (inside the container)
docker exec user-behavior-analytics-kafka-1 \
  kafka-console-consumer --bootstrap-server localhost:9092 \
    --topic clickstream-events --from-beginning --max-messages 1
```

### Stage 3: Stream Processing (Silver Layer)

Spark Structured Streaming reads from Kafka in **1-minute micro-batches**, parses the JSON, adds a `processing_timestamp`, and writes Delta Lake files to S3.

#### Transformation

```
Kafka message (key=null, value=JSON bytes)
    → Cast value to string
    → Parse JSON using CLICKSTREAM_SCHEMA
    → Add processing_timestamp (current_timestamp())
    → Write as Delta Lake to Silver bucket
```

#### Output location

```
s3://user-behavior-analytics-silver/
├── clickstream/delta/
│   ├── _delta_log/              # Delta Lake transaction log
│   │   ├── 00000000000000000000.json
│   │   ├── 00000000000000000001.json
│   │   └── ...
│   ├── part-00000-*.snappy.parquet   # Data files
│   └── ...
└── checkpoints/delta/           # Streaming checkpoint
    ├── commits/
    ├── metadata
    ├── offsets/
    └── sources/
```

#### How to inspect

```bash
# Check streaming job is processing micro-batches
docker compose logs streaming-job 2>&1 | grep "DeltaSink" | tail -5

# List files in Silver bucket
docker exec user-behavior-analytics-localstack-1 \
  awslocal s3 ls s3://user-behavior-analytics-silver/clickstream/delta/ --recursive

# Check Spark Master UI for the running application
open http://localhost:8080
```

### Stage 4: Batch Processing (Gold Layer)

The batch job reads from Silver, creates two aggregated tables, and writes to Gold. It is run on-demand (not scheduled).

#### Aggregation: Daily User Activity

Groups by `(date, user_id)` and computes:


| Column             | Aggregation                     |
| ------------------ | ------------------------------- |
| `total_events`     | `count(*)`                      |
| `sessions`         | `countDistinct(session_id)`     |
| `products_viewed`  | `countDistinct(product_id)`     |
| `purchases`        | `sum(event_type == 'purchase')` |
| `avg_time_on_page` | `avg(time_on_page)`             |


**Output:** `s3a://user-behavior-analytics-gold/daily_user_activity/` (partitioned by `date`)

#### Aggregation: Product Performance

Groups by `(date, product_id)` and computes:


| Column             | Aggregation                     |
| ------------------ | ------------------------------- |
| `total_views`      | `count(*)`                      |
| `unique_users`     | `countDistinct(user_id)`        |
| `purchases`        | `sum(event_type == 'purchase')` |
| `avg_time_on_page` | `avg(time_on_page)`             |


**Output:** `s3a://user-behavior-analytics-gold/product_performance/` (partitioned by `date`)

#### How to run

```bash
docker exec user-behavior-analytics-spark-master-1 \
  /opt/spark/bin/spark-submit \
    --master spark://spark-master:7077 \
    --conf spark.driver.extraJavaOptions=-Divy.home=/tmp/ivy2 \
    --packages io.delta:delta-spark_2.12:3.2.0,org.apache.hadoop:hadoop-aws:3.3.4,com.amazonaws:aws-java-sdk-bundle:1.12.262 \
    /opt/spark/app/src/batch/batch_job.py
```

#### How to inspect

```bash
# List Gold layer data
docker exec user-behavior-analytics-localstack-1 \
  awslocal s3 ls s3://user-behavior-analytics-gold/ --recursive

# Check output
docker exec user-behavior-analytics-localstack-1 \
  awslocal s3 ls s3://user-behavior-analytics-gold/daily_user_activity/
docker exec user-behavior-analytics-localstack-1 \
  awslocal s3 ls s3://user-behavior-analytics-gold/product_performance/
```

## See also

- [data-storage.md](data-storage.md) — S3 bucket layout, S3A configuration, Delta Lake features in use, and the full Spark SQL → Delta → Parquet → S3A → S3 storage stack.

