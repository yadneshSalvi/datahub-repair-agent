with source as (
    select * from {{ source('shop_raw', 'products') }}
)
select
    product_id,
    sku,
    product_name,
    category,
    list_price
from source

