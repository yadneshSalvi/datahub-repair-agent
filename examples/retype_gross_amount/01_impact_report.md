# Impact report: retype-orders-gross_amount

| Bucket | Asset | Hops | Catalog/code evidence |
|---|---|---:|---|
| REQUIRES_PATCH | `extract_recent_orders` | 1 | DataHub table lineage links this Airflow task to `shop_prod.raw.orders`, and its configured SQL constant references `gross_amount` exactly once on line 2. |
| REQUIRES_PATCH | `stg_orders` | 1 | SQL references `gross_amount` exactly 2 times on lines 9, 10; this lineage-bearing file requires repair. |
| DOWNSTREAM_UNAFFECTED | `fct_orders` | 2 | Reads `net_amount`, aliases created upstream on the changed column's lineage path; `gross_amount` does not appear in this file's SQL. Flagged for review only. |
| DOWNSTREAM_UNAFFECTED | `mart_customer_ltv` | 3 | Reads `net_revenue`, aliases created upstream on the changed column's lineage path; `gross_amount` does not appear in this file's SQL. Flagged for review only. |
| DOWNSTREAM_UNAFFECTED | `mart_daily_revenue` | 3 | Reads `net_revenue`, aliases created upstream on the changed column's lineage path; `gross_amount` does not appear in this file's SQL. Flagged for review only. |
| SKIPPED | `dim_customers` | 3 | In the table-level downstream graph, but consumes `stg_customers` columns {country_code, customer_id, email, full_name, marketing_opt_in, signup_date}; none is on the exact `shop_prod.raw.orders.gross_amount` column-lineage path. |
| SKIPPED | `dim_products` | 3 | In the table-level downstream graph, but consumes `stg_products` columns {category, list_price, product_id, product_name, sku}; none is on the exact `shop_prod.raw.orders.gross_amount` column-lineage path. |
| SKIPPED | `mart_product_performance` | 3 | In the table-level downstream graph, but consumes `dim_products` columns {category, product_id, sku}; `stg_order_items` columns {line_total, quantity}; none is on the exact `shop_prod.raw.orders.gross_amount` column-lineage path. |
| SKIPPED | `stg_customers` | 2 | In the table-level downstream graph, but consumes `customers` columns {country_code, customer_id, email, full_name, marketing_opt_in, signup_date}; none is on the exact `shop_prod.raw.orders.gross_amount` column-lineage path. |
| SKIPPED | `stg_order_items` | 2 | In the table-level downstream graph, but consumes `order_items` columns {order_id, order_item_id, product_id, quantity, unit_price}; none is on the exact `shop_prod.raw.orders.gross_amount` column-lineage path. |
| SKIPPED | `stg_products` | 2 | In the table-level downstream graph, but consumes `products` columns {category, list_price, product_id, product_name, sku}; none is on the exact `shop_prod.raw.orders.gross_amount` column-lineage path. |
| SKIPPED | `stg_web_events` | 2 | In the table-level downstream graph, but consumes `web_events` columns {customer_id, event_at, event_id, event_type, session_id}; none is on the exact `shop_prod.raw.orders.gross_amount` column-lineage path. |

Scanned **12** code-bearing assets.
