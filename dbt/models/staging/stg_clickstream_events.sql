{{
    config(
        materialized='view',
        schema='staging'
    )
}}

WITH source AS (
    SELECT * FROM {{ source('clickstream', 'clickstream_events_delta') }}
),

renamed AS (
    SELECT
        event_id,
        user_id,
        session_id,
        event_type,
        product_id,
        timestamp,
        page_url,
        user_agent,
        ip_address,
        device_type,
        browser,
        os,
        country,
        referrer,
        screen_resolution,
        time_on_page,
        scroll_depth,
        click_coordinates
    FROM source
)

SELECT * FROM renamed 