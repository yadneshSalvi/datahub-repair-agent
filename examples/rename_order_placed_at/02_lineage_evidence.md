# Column-lineage evidence

```mermaid
graph LR
    n0["shop_prod.raw.orders.order_placed_at"] -->|"IDENTITY"| n1["stg_orders.order_placed_at"]
    n1["stg_orders.order_placed_at"] -->|"CAST_DATE"| n2["fct_orders.order_date"]
    n2["fct_orders.order_date"] -->|"IDENTITY"| n3["mart_daily_revenue.order_date"]
    n2["fct_orders.order_date"] -->|"MIN"| n4["mart_customer_ltv.first_order_date"]
    n0["shop_prod.raw.orders.order_placed_at"] -->|"DIRECT_SQL_REFERENCE"| n5["extract_recent_orders.order_placed_at"]
```

## Captured DataHub queries

No usage query text was captured for this window; DataHub fine-grained lineage supplied the evidence above.
