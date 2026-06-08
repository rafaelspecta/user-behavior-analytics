import os
from pyspark.sql import SparkSession
from pyspark.sql.functions import from_json, col, current_timestamp, window
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, TimestampType, MapType

CLICKSTREAM_SCHEMA = StructType([
    StructField("event_id", StringType(), True),
    StructField("user_id", StringType(), True),
    StructField("session_id", StringType(), True),
    StructField("event_type", StringType(), True),
    StructField("product_id", StringType(), True),
    StructField("timestamp", StringType(), True),
    StructField("page_url", StringType(), True),
    StructField("user_agent", StringType(), True),
    StructField("ip_address", StringType(), True),
    StructField("device_type", StringType(), True),
    StructField("browser", StringType(), True),
    StructField("os", StringType(), True),
    StructField("country", StringType(), True),
    StructField("referrer", StringType(), True),
    StructField("screen_resolution", StringType(), True),
    StructField("time_on_page", IntegerType(), True),
    StructField("scroll_depth", IntegerType(), True),
    StructField("click_coordinates", MapType(StringType(), IntegerType()), True)
])

STORAGE_FORMAT = os.environ.get("STORAGE_FORMAT", "delta")


def _packages_for_format(fmt):
    """Return Spark packages string based on storage format."""
    base = [
        "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.3",
        "org.apache.hadoop:hadoop-aws:3.3.4",
        "com.amazonaws:aws-java-sdk-bundle:1.12.262",
    ]
    if fmt == "delta":
        base.append("io.delta:delta-spark_2.12:3.2.0")
    elif fmt == "hudi":
        base.append("org.apache.hudi:hudi-spark3.5-bundle_2.12:0.15.0")
    return ",".join(base)


def create_spark_session():
    """Create and configure Spark session with S3A and format support."""
    s3_endpoint = os.environ.get("S3_ENDPOINT", "http://localstack:4566")
    aws_access_key = os.environ.get("AWS_ACCESS_KEY_ID", "test")
    aws_secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY", "test")

    builder = SparkSession.builder \
        .appName("ClickstreamStreaming")

    if STORAGE_FORMAT == "delta":
        builder = builder \
            .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension") \
            .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")

    packages = _packages_for_format(STORAGE_FORMAT)
    builder = builder \
        .config("spark.jars.packages", packages) \
        .config("spark.hadoop.fs.s3a.endpoint", s3_endpoint) \
        .config("spark.hadoop.fs.s3a.access.key", aws_access_key) \
        .config("spark.hadoop.fs.s3a.secret.key", aws_secret_key) \
        .config("spark.hadoop.fs.s3a.path.style.access", "true") \
        .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem")

    return builder.getOrCreate()


def process_stream(spark):
    """Process the Kafka stream and write to the configured format."""
    kafka_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

    df = spark \
        .readStream \
        .format("kafka") \
        .option("kafka.bootstrap.servers", kafka_servers) \
        .option("subscribe", "clickstream-events") \
        .option("startingOffsets", "latest") \
        .load()

    parsed_df = df.select(
        from_json(col("value").cast("string"), CLICKSTREAM_SCHEMA).alias("data"),
        current_timestamp().alias("processing_timestamp")
    ).select("data.*", "processing_timestamp")

    if STORAGE_FORMAT == "delta":
        query = parsed_df.writeStream \
            .format("delta") \
            .outputMode("append") \
            .option("checkpointLocation", "s3a://user-behavior-analytics-silver/checkpoints/delta") \
            .option("path", "s3a://user-behavior-analytics-silver/clickstream/delta") \
            .trigger(processingTime="1 minute") \
            .start()
    elif STORAGE_FORMAT == "hudi":
        query = parsed_df.writeStream \
            .format("hudi") \
            .outputMode("append") \
            .option("hoodie.table.name", "clickstream_events") \
            .option("hoodie.datasource.write.recordkey.field", "event_id") \
            .option("hoodie.datasource.write.partitionpath.field", "event_type") \
            .option("hoodie.datasource.write.precombine.field", "timestamp") \
            .option("hoodie.upsert.shuffle.parallelism", "200") \
            .option("hoodie.insert.shuffle.parallelism", "200") \
            .option("checkpointLocation", "s3a://user-behavior-analytics-silver/checkpoints/hudi") \
            .option("path", "s3a://user-behavior-analytics-silver/clickstream/hudi") \
            .trigger(processingTime="1 minute") \
            .start()
    else:
        raise ValueError(f"Unsupported STORAGE_FORMAT: {STORAGE_FORMAT}")

    return query


def main():
    spark = create_spark_session()
    query = None
    try:
        query = process_stream(spark)
        query.awaitTermination()
    except KeyboardInterrupt:
        print("\nStopping streaming queries...")
        if query:
            query.stop()
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
