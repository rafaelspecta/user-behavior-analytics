from pyspark.sql import SparkSession
from pyspark.sql.functions import col, date_trunc, count, sum, avg, max
from datetime import datetime, timedelta

def create_spark_session():
    """Create and configure Spark session."""
    return SparkSession.builder \
        .appName("ClickstreamBatch") \
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension") \
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog") \
        .config("spark.jars.packages", 
                "io.delta:delta-core_2.12:2.2.0,"
                "org.apache.hudi:hudi-spark3.3-bundle_2.12:0.12.2") \
        .getOrCreate()

def compact_delta_tables(spark):
    """Compact Delta tables to optimize performance."""
    # Compact Delta tables
    spark.sql("""
        OPTIMIZE delta.`s3a://user-behavior-analytics-silver/clickstream/delta`
        ZORDER BY (event_type, timestamp)
    """)
    
    # Vacuum old files
    spark.sql("""
        VACUUM delta.`s3a://user-behavior-analytics-silver/clickstream/delta`
        RETAIN 168 HOURS
    """)

def create_aggregated_views(spark):
    """Create aggregated views for analytics."""
    # Read from Delta
    df = spark.read.format("delta").load("s3a://user-behavior-analytics-silver/clickstream/delta")
    
    # Daily user activity
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
    
    # Write to gold layer
    daily_activity.write \
        .format("delta") \
        .mode("overwrite") \
        .partitionBy("date") \
        .save("s3a://user-behavior-analytics-gold/daily_user_activity")
    
    # Product performance
    product_performance = df.groupBy(
        date_trunc("day", col("timestamp")).alias("date"),
        "product_id"
    ).agg(
        count("*").alias("total_views"),
        countDistinct("user_id").alias("unique_users"),
        sum(when(col("event_type") == "purchase", 1).otherwise(0)).alias("purchases"),
        avg("time_on_page").alias("avg_time_on_page")
    )
    
    # Write to gold layer
    product_performance.write \
        .format("delta") \
        .mode("overwrite") \
        .partitionBy("date") \
        .save("s3a://user-behavior-analytics-gold/product_performance")

def sync_to_redshift(spark):
    """Sync aggregated data to Redshift."""
    # Read from gold layer
    daily_activity = spark.read.format("delta").load("s3a://user-behavior-analytics-gold/daily_user_activity")
    product_performance = spark.read.format("delta").load("s3a://user-behavior-analytics-gold/product_performance")
    
    # Write to Redshift
    daily_activity.write \
        .format("jdbc") \
        .option("url", "jdbc:redshift://your-redshift-endpoint:5439/analytics") \
        .option("dbtable", "daily_user_activity") \
        .option("user", "your_username") \
        .option("password", "your_password") \
        .option("driver", "com.amazon.redshift.jdbc42.Driver") \
        .mode("overwrite") \
        .save()
    
    product_performance.write \
        .format("jdbc") \
        .option("url", "jdbc:redshift://your-redshift-endpoint:5439/analytics") \
        .option("dbtable", "product_performance") \
        .option("user", "your_username") \
        .option("password", "your_password") \
        .option("driver", "com.amazon.redshift.jdbc42.Driver") \
        .mode("overwrite") \
        .save()

def main():
    spark = create_spark_session()
    
    try:
        # Compact tables
        compact_delta_tables(spark)
        
        # Create aggregated views
        create_aggregated_views(spark)
        
        # Sync to Redshift (if configured)
        sync_to_redshift(spark)
        
    except Exception as e:
        print(f"Error in batch processing: {str(e)}")
        raise
    finally:
        spark.stop()

if __name__ == "__main__":
    main() 