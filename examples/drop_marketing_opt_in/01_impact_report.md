# Impact report: drop-customers-marketing_opt_in

| Bucket | Asset | Hops | Catalog/code evidence |
|---|---|---:|---|
| REQUIRES_PATCH | `dim_customers` | 2 | SQL references `marketing_opt_in` exactly once on line 7; this lineage-bearing file requires repair. |
| REQUIRES_PATCH | `stg_customers` | 1 | SQL references `marketing_opt_in` exactly once on line 10; this lineage-bearing file requires repair. |
| SKIPPED | `dim_products` | 3 | In the table-level downstream graph, but consumes `stg_products` columns {category, list_price, product_id, product_name, sku}; none is on the exact `shop_prod.raw.customers.marketing_opt_in` column-lineage path. |
| SKIPPED | `extract_recent_orders` | — | No exact changed-column reference; configured Airflow SQL consumes `customer_id`, `gross_amount`, `order_id`, `order_placed_at`, not `marketing_opt_in`. |
| SKIPPED | `fct_orders` | 3 | In the table-level downstream graph, but consumes `stg_order_items` columns {order_id}; `stg_orders` columns {customer_id, net_amount, order_id, order_placed_at, order_status}; none is on the exact `shop_prod.raw.customers.marketing_opt_in` column-lineage path. |
| SKIPPED | `mart_customer_ltv` | 3 | In the table-level downstream graph, but consumes `dim_customers` columns {country_code, customer_id}; `fct_orders` columns {net_revenue, order_date, order_id}; none is on the exact `shop_prod.raw.customers.marketing_opt_in` column-lineage path. |
| SKIPPED | `mart_daily_revenue` | 3 | In the table-level downstream graph, but consumes `fct_orders` columns {net_revenue, order_date, order_id}; none is on the exact `shop_prod.raw.customers.marketing_opt_in` column-lineage path. |
| SKIPPED | `mart_product_performance` | 3 | In the table-level downstream graph, but consumes `dim_products` columns {category, product_id, sku}; `stg_order_items` columns {line_total, quantity}; none is on the exact `shop_prod.raw.customers.marketing_opt_in` column-lineage path. |
| SKIPPED | `stg_order_items` | 2 | In the table-level downstream graph, but consumes `order_items` columns {order_id, order_item_id, product_id, quantity, unit_price}; none is on the exact `shop_prod.raw.customers.marketing_opt_in` column-lineage path. |
| SKIPPED | `stg_orders` | 2 | In the table-level downstream graph, but consumes `orders` columns {customer_id, discount_amount, gross_amount, order_id, order_placed_at, order_status}; none is on the exact `shop_prod.raw.customers.marketing_opt_in` column-lineage path. |
| SKIPPED | `stg_products` | 2 | In the table-level downstream graph, but consumes `products` columns {category, list_price, product_id, product_name, sku}; none is on the exact `shop_prod.raw.customers.marketing_opt_in` column-lineage path. |
| SKIPPED | `stg_web_events` | 2 | In the table-level downstream graph, but consumes `web_events` columns {customer_id, event_at, event_id, event_type, session_id}; none is on the exact `shop_prod.raw.customers.marketing_opt_in` column-lineage path. |

Scanned **12** code-bearing assets.
