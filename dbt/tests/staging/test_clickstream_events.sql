-- Test for unique event IDs
SELECT
    event_id,
    COUNT(*) as count
FROM {{ ref('stg_clickstream_events') }}
GROUP BY event_id
HAVING COUNT(*) > 1

-- Test for valid event types
SELECT
    event_type
FROM {{ ref('stg_clickstream_events') }}
WHERE event_type NOT IN ('page_view', 'product_view', 'add_to_cart', 'checkout', 'purchase')

-- Test for valid timestamps
SELECT
    timestamp
FROM {{ ref('stg_clickstream_events') }}
WHERE timestamp IS NULL OR timestamp > CURRENT_TIMESTAMP

-- Test for valid user IDs
SELECT
    user_id
FROM {{ ref('stg_clickstream_events') }}
WHERE user_id IS NULL

-- Test for valid session IDs
SELECT
    session_id
FROM {{ ref('stg_clickstream_events') }}
WHERE session_id IS NULL

-- Test for valid time_on_page values
SELECT
    time_on_page
FROM {{ ref('stg_clickstream_events') }}
WHERE time_on_page < 0 OR time_on_page > 3600

-- Test for valid scroll_depth values
SELECT
    scroll_depth
FROM {{ ref('stg_clickstream_events') }}
WHERE scroll_depth < 0 OR scroll_depth > 100

-- Test for valid click coordinates
SELECT
    click_coordinates
FROM {{ ref('stg_clickstream_events') }}
WHERE click_coordinates['x'] < 0 OR click_coordinates['x'] > 3840
   OR click_coordinates['y'] < 0 OR click_coordinates['y'] > 2160 