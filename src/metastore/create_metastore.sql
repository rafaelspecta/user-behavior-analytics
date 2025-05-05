-- Create database
CREATE DATABASE IF NOT EXISTS user_behavior_analytics;

USE user_behavior_analytics;

-- Register Delta tables
CREATE EXTERNAL TABLE IF NOT EXISTS clickstream_events_delta
USING DELTA
LOCATION 's3a://user-behavior-analytics-silver/clickstream/delta';

CREATE EXTERNAL TABLE IF NOT EXISTS daily_user_activity
USING DELTA
LOCATION 's3a://user-behavior-analytics-gold/daily_user_activity';

CREATE EXTERNAL TABLE IF NOT EXISTS product_performance
USING DELTA
LOCATION 's3a://user-behavior-analytics-gold/product_performance';

-- Register Hudi tables
CREATE EXTERNAL TABLE IF NOT EXISTS clickstream_events_hudi
USING HUDI
LOCATION 's3a://user-behavior-analytics-silver/clickstream/hudi'
TBLPROPERTIES (
  'hoodie.table.name' = 'clickstream_events',
  'hoodie.datasource.write.recordkey.field' = 'event_id',
  'hoodie.datasource.write.partitionpath.field' = 'event_type',
  'hoodie.datasource.write.precombine.field' = 'timestamp'
);

-- Create views for common queries
CREATE OR REPLACE VIEW user_session_metrics AS
SELECT
  user_id,
  session_id,
  MIN(timestamp) as session_start,
  MAX(timestamp) as session_end,
  COUNT(*) as total_events,
  COUNT(DISTINCT product_id) as products_viewed,
  SUM(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END) as purchases
FROM clickstream_events_delta
GROUP BY user_id, session_id;

CREATE OR REPLACE VIEW product_conversion_rates AS
SELECT
  product_id,
  COUNT(*) as total_views,
  COUNT(DISTINCT user_id) as unique_users,
  SUM(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END) as purchases,
  ROUND(SUM(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as conversion_rate
FROM clickstream_events_delta
GROUP BY product_id;

-- Create materialized views for performance optimization
CREATE MATERIALIZED VIEW IF NOT EXISTS daily_aggregates
USING DELTA
AS
SELECT
  date_trunc('day', timestamp) as date,
  event_type,
  COUNT(*) as event_count,
  COUNT(DISTINCT user_id) as unique_users,
  COUNT(DISTINCT session_id) as sessions
FROM clickstream_events_delta
GROUP BY date_trunc('day', timestamp), event_type; 