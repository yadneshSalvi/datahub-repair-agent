with source as (
    select * from {{ source('shop_raw', 'orders') }}
)
select
    order_id,
    customer_id,
    order_created_at,
    order_status,
    gross_amount,
    gross_amount - coalesce(discount_amount, 0) as net_amount
from source
where order_status != 'cancelled'

