select
    c.customer_id,
    c.country_code,
    count(o.order_id) as lifetime_orders,
    coalesce(sum(o.net_revenue), 0) as lifetime_revenue,
    min(o.order_date) as first_order_date
from {{ ref('dim_customers') }} c
left join {{ ref('fct_orders') }} o on c.customer_id = o.customer_id
group by c.customer_id, c.country_code

