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

def create_spark_session():
    """Create and configure Spark session with S3A and Delta Lake support."""
    s3_endpoint = os.environ.get('S3_ENDPOINT', 'http://localstack:4566')
    aws_access_key = os.environ.get('AWS_ACCESS_KEY_ID', 'test')
    aws_secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY', 'test')

    # Original production config (requires Hudi + different Spark version):
    # .config("spark.jars.packages",
    #         "org.apache.spark:spark-sql-kafka-0-10_2.12:3.3.0,"
    #         "io.delta:delta-core_2.12:2.2.0,"
    #         "org.apache.hudi:hudi-spark3.3-bundle_2.12:0.12.2")

    return SparkSession.builder \
        .appName("ClickstreamStreaming") \
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension") \
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog") \
        .config("spark.jars.packages",
                "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.3,"
                "io.delta:delta-spark_2.12:3.2.0,"
                "org.apache.hadoop:hadoop-aws:3.3.4,"
                "com.amazonaws:aws-java-sdk-bundle:1.12.262") \
        .config("spark.hadoop.fs.s3a.endpoint", s3_endpoint) \
        .config("spark.hadoop.fs.s3a.access.key", aws_access_key) \
        .config("spark.hadoop.fs.s3a.secret.key", aws_secret_key) \
        .config("spark.hadoop.fs.s3a.path.style.access", "true") \
        .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem") \
        .getOrCreate()

def process_stream(spark):
    """Process the Kafka stream and write to Delta Lake."""
    kafka_servers = os.environ.get('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')

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

    delta_query = parsed_df.writeStream \
        .format("delta") \
        .outputMode("append") \
        .option("checkpointLocation", "s3a://user-behavior-analytics-silver/checkpoints/delta") \
        .option("path", "s3a://user-behavior-analytics-silver/clickstream/delta") \
        .trigger(processingTime="1 minute") \
        .start()

    # Hudi writeStream (commented out -- see docs/roadmap.md for Scenario 3):
    # hudi_query = parsed_df.writeStream \
    #     .format("hudi") \
    #     .outputMode("append") \
    #     .option("hoodie.table.name", "clickstream_events") \
    #     .option("hoodie.datasource.write.recordkey.field", "event_id") \
    #     .option("hoodie.datasource.write.partitionpath.field", "event_type") \
    #     .option("hoodie.datasource.write.precombine.field", "timestamp") \
    #     .option("hoodie.upsert.shuffle.parallelism", 200) \
    #     .option("hoodie.insert.shuffle.parallelism", 200) \
    #     .option("checkpointLocation", "s3a://user-behavior-analytics-silver/checkpoints/hudi") \
    #     .option("path", "s3a://user-behavior-analytics-silver/clickstream/hudi") \
    #     .trigger(processingTime="1 minute") \
    #     .start()

    return delta_query

def main():
    spark = create_spark_session()

    try:
        delta_query = process_stream(spark)
        delta_query.awaitTermination()
    except KeyboardInterrupt:
        print("\nStopping streaming queries...")
        delta_query.stop()
    finally:
        spark.stop()

if __name__ == "__main__":
    main()
