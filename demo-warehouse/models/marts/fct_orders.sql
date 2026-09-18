with orders as (
    select * from {{ ref('stg_orders') }}
),
items as (
    select order_id, count(*) as item_count
    from {{ ref('stg_order_items') }}
    group by order_id
)
select
    o.order_id,
    o.customer_id,
    cast(o.order_created_at as date) as order_date,
    o.order_status,
    coalesce(i.item_count, 0) as item_count,
    o.net_amount as net_revenue
from orders o
left join items i on o.order_id = i.order_id

