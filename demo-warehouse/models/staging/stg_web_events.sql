with source as (
    select * from {{ source('shop_raw', 'web_events') }}
)
select
    event_id,
    session_id,
    customer_id,
    event_type,
    event_at
from source

