select
    order_date,
    count(*) as order_count,
    sum(net_revenue) as gross_revenue
from {{ ref('fct_orders') }}
group by order_date

