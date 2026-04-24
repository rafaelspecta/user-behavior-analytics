import os
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, date_trunc, count, sum, avg, countDistinct, when
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

STORAGE_FORMAT = os.environ.get("STORAGE_FORMAT", "delta")


def _packages_for_format(fmt):
    """Return Spark packages string based on storage format."""
    base = [
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
        .appName("ClickstreamBatch")

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


def compact_tables(spark):
    """Compact tables to optimize performance (Delta only)."""
    if STORAGE_FORMAT != "delta":
        print(f"Skipping compaction for format: {STORAGE_FORMAT}")
        return

    print("Running VACUUM on Silver Delta table (retaining 168 hours)...")
    spark.sql("""
        VACUUM delta.`s3a://user-behavior-analytics-silver/clickstream/delta`
        RETAIN 168 HOURS
    """)
    print("VACUUM complete.")


def create_aggregated_views(spark):
    """Create aggregated views for analytics (Silver -> Gold)."""
    if STORAGE_FORMAT == "delta":
        silver_path = "s3a://user-behavior-analytics-silver/clickstream/delta"
        gold_path = "s3a://user-behavior-analytics-gold"
        df = spark.read.format("delta").load(silver_path)
    elif STORAGE_FORMAT == "hudi":
        silver_path = "s3a://user-behavior-analytics-silver/clickstream/hudi"
        gold_path = "s3a://user-behavior-analytics-gold"
        df = spark.read.format("hudi").load(silver_path)
    else:
        raise ValueError(f"Unsupported STORAGE_FORMAT: {STORAGE_FORMAT}")

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
        .format(STORAGE_FORMAT) \
        .mode("overwrite") \
        .partitionBy("date") \
        .save(f"{gold_path}/daily_user_activity")

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
        .format(STORAGE_FORMAT) \
        .mode("overwrite") \
        .partitionBy("date") \
        .save(f"{gold_path}/product_performance")


def sync_to_redshift(spark):
    """Sync aggregated data to Redshift (when configured)."""
    gold_path = "s3a://user-behavior-analytics-gold"
    daily_activity = spark.read.format(STORAGE_FORMAT).load(f"{gold_path}/daily_user_activity")
    product_performance = spark.read.format(STORAGE_FORMAT).load(f"{gold_path}/product_performance")

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
            compact_tables(spark)
        except Exception as e:
            print(f"Warning: compaction skipped: {e}")

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
