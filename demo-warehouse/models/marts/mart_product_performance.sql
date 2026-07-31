select
    p.product_id,
    p.sku,
    p.category,
    coalesce(sum(i.quantity), 0) as units_sold,
    coalesce(sum(i.line_total), 0) as revenue
from {{ ref('dim_products') }} p
left join {{ ref('stg_order_items') }} i on p.product_id = i.product_id
group by p.product_id, p.sku, p.category

