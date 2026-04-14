import os

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, date_trunc, count, sum, avg, max, countDistinct, when
from datetime import datetime, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

redshift_url = os.getenv("REDSHIFT_URL")
redshift_user = os.getenv("REDSHIFT_USER")
redshift_pass = os.getenv("REDSHIFT_PASS")
redshift_driver = os.getenv("REDSHIFT_DRIVER")

def create_spark_session():
    """Create and configure Spark session with S3A and Delta Lake support."""
    s3_endpoint = os.environ.get('S3_ENDPOINT', 'http://localstack:4566')
    aws_access_key = os.environ.get('AWS_ACCESS_KEY_ID', 'test')
    aws_secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY', 'test')

    # Original production config (requires Hudi + different Spark version):
    # .config("spark.jars.packages",
    #         "io.delta:delta-core_2.12:2.2.0,"
    #         "org.apache.hudi:hudi-spark3.3-bundle_2.12:0.12.2")

    return SparkSession.builder \
        .appName("ClickstreamBatch") \
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension") \
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog") \
        .config("spark.jars.packages",
                "io.delta:delta-spark_2.12:3.2.0,"
                "org.apache.hadoop:hadoop-aws:3.3.4,"
                "com.amazonaws:aws-java-sdk-bundle:1.12.262") \
        .config("spark.hadoop.fs.s3a.endpoint", s3_endpoint) \
        .config("spark.hadoop.fs.s3a.access.key", aws_access_key) \
        .config("spark.hadoop.fs.s3a.secret.key", aws_secret_key) \
        .config("spark.hadoop.fs.s3a.path.style.access", "true") \
        .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem") \
        .getOrCreate()

def compact_delta_tables(spark):
    """Compact Delta tables to optimize performance.
    NOTE: OPTIMIZE ZORDER BY is only available in Databricks Delta, not OSS.
    Using VACUUM only for now. See docs/roadmap.md for details.
    """
    print("Running VACUUM on Silver Delta table (retaining 168 hours)...")
    spark.sql("""
        VACUUM delta.`s3a://user-behavior-analytics-silver/clickstream/delta`
        RETAIN 168 HOURS
    """)
    print("VACUUM complete.")

def create_aggregated_views(spark):
    """Create aggregated views for analytics (Silver -> Gold)."""
    df = spark.read.format("delta").load("s3a://user-behavior-analytics-silver/clickstream/delta")

    daily_activity = df.groupBy(
        date_trunc("day", col("timestamp")).alias("date"),
        "user_id"
    ).agg(
        count("*").alias("total_events"),
        countDistinct("session_id").alias("sessions"),
        countDistinct("product_id").alias("products_viewed"),
        sum(when(col("event_type") == "purchase", 1).otherwise(0)).alias("purchases"),
        avg("time_on_page").alias("avg_time_on_page")
    )

    daily_activity.write \
        .format("delta") \
        .mode("overwrite") \
        .partitionBy("date") \
        .save("s3a://user-behavior-analytics-gold/daily_user_activity")

    product_performance = df.groupBy(
        date_trunc("day", col("timestamp")).alias("date"),
        "product_id"
    ).agg(
        count("*").alias("total_views"),
        countDistinct("user_id").alias("unique_users"),
        sum(when(col("event_type") == "purchase", 1).otherwise(0)).alias("purchases"),
        avg("time_on_page").alias("avg_time_on_page")
    )

    product_performance.write \
        .format("delta") \
        .mode("overwrite") \
        .partitionBy("date") \
        .save("s3a://user-behavior-analytics-gold/product_performance")

def sync_to_redshift(spark):
    """Sync aggregated data to Redshift (when configured)."""
    daily_activity = spark.read.format("delta").load("s3a://user-behavior-analytics-gold/daily_user_activity")
    product_performance = spark.read.format("delta").load("s3a://user-behavior-analytics-gold/product_performance")

    daily_activity.write \
        .format("jdbc") \
        .option("url", redshift_url) \
        .option("dbtable", "daily_user_activity") \
        .option("user", redshift_user) \
        .option("password", redshift_pass) \
        .option("driver", redshift_driver) \
        .mode("overwrite") \
        .save()

    product_performance.write \
        .format("jdbc") \
        .option("url", redshift_url) \
        .option("dbtable", "product_performance") \
        .option("user", redshift_user) \
        .option("password", redshift_pass) \
        .option("driver", redshift_driver) \
        .mode("overwrite") \
        .save()

def main():
    spark = create_spark_session()

    try:
        try:
            compact_delta_tables(spark)
        except Exception as e:
            print(f"Warning: Delta compaction skipped: {e}")

        create_aggregated_views(spark)
        print("Silver -> Gold aggregation complete.")

        if redshift_url:
            sync_to_redshift(spark)
            print("Redshift sync complete.")
        else:
            print("Skipping Redshift sync (REDSHIFT_URL not configured)")

    except Exception as e:
        print(f"Error in batch processing: {str(e)}")
        raise
    finally:
        spark.stop()

if __name__ == "__main__":
    main()
