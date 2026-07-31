with source as (
    select * from {{ source('shop_raw', 'order_items') }}
)
select
    order_item_id,
    order_id,
    product_id,
    quantity,
    unit_price,
    quantity * unit_price as line_total
from source

