from pyspark.sql import SparkSession
from pyspark.sql.functions import from_json, col, current_timestamp, window
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, TimestampType, MapType

# Define the schema for clickstream events
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
    """Create and configure Spark session."""
    return SparkSession.builder \
        .appName("ClickstreamStreaming") \
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension") \
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog") \
        .config("spark.jars.packages", 
                "org.apache.spark:spark-sql-kafka-0-10_2.12:3.3.0,"
                "io.delta:delta-core_2.12:2.2.0,"
                "org.apache.hudi:hudi-spark3.3-bundle_2.12:0.12.2") \
        .getOrCreate()

def process_stream(spark):
    """Process the Kafka stream and write to both Delta and Hudi."""
    # Read from Kafka
    df = spark \
        .readStream \
        .format("kafka") \
        .option("kafka.bootstrap.servers", "localhost:9092") \
        .option("subscribe", "clickstream-events") \
        .option("startingOffsets", "latest") \
        .load()

    # Parse JSON and add processing timestamp
    parsed_df = df.select(
        from_json(col("value").cast("string"), CLICKSTREAM_SCHEMA).alias("data"),
        current_timestamp().alias("processing_timestamp")
    ).select("data.*", "processing_timestamp")

    # Write to Delta Lake (silver layer)
    delta_query = parsed_df.writeStream \
        .format("delta") \
        .outputMode("append") \
        .option("checkpointLocation", "s3a://user-behavior-analytics-silver/checkpoints/delta") \
        .option("path", "s3a://user-behavior-analytics-silver/clickstream/delta") \
        .trigger(processingTime="1 minute") \
        .start()

    # Write to Hudi (silver layer)
    hudi_query = parsed_df.writeStream \
        .format("hudi") \
        .outputMode("append") \
        .option("hoodie.table.name", "clickstream_events") \
        .option("hoodie.datasource.write.recordkey.field", "event_id") \
        .option("hoodie.datasource.write.partitionpath.field", "event_type") \
        .option("hoodie.datasource.write.precombine.field", "timestamp") \
        .option("hoodie.upsert.shuffle.parallelism", 200) \
        .option("hoodie.insert.shuffle.parallelism", 200) \
        .option("checkpointLocation", "s3a://user-behavior-analytics-silver/checkpoints/hudi") \
        .option("path", "s3a://user-behavior-analytics-silver/clickstream/hudi") \
        .trigger(processingTime="1 minute") \
        .start()

    return delta_query, hudi_query

def main():
    spark = create_spark_session()
    
    try:
        delta_query, hudi_query = process_stream(spark)
        
        # Wait for the streaming queries to terminate
        delta_query.awaitTermination()
        hudi_query.awaitTermination()
        
    except KeyboardInterrupt:
        print("\nStopping streaming queries...")
        delta_query.stop()
        hudi_query.stop()
    finally:
        spark.stop()

if __name__ == "__main__":
    main() 