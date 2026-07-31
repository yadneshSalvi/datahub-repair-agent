with source as (
    select * from {{ source('shop_raw', 'orders') }}
)
select
    order_id,
    customer_id,
    order_placed_at,
    order_status,
    CAST(gross_amount AS NUMBER(12,2)) AS gross_amount,
    CAST(gross_amount AS NUMBER(12,2)) - coalesce(discount_amount, 0) as net_amount
from source
where order_status != 'cancelled'

