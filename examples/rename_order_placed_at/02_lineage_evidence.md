# Column-lineage evidence

```mermaid
graph LR
    n0a["shop_prod.raw.orders.order_placed_at"] -->|"IDENTITY"| n0b["stg_orders.order_placed_at"]
    n1a["stg_orders.order_placed_at"] -->|"CAST_DATE"| n1b["fct_orders.order_date"]
    n2a["fct_orders.order_date"] -->|"IDENTITY"| n2b["mart_daily_revenue.order_date"]
    n3a["fct_orders.order_date"] -->|"MIN"| n3b["mart_customer_ltv.first_order_date"]
    n4a["shop_prod.raw.orders.order_placed_at"] -->|"DIRECT_SQL_REFERENCE"| n4b["extract_recent_orders.order_placed_at"]
```

## Captured DataHub queries

No usage query text was captured for this window; DataHub fine-grained lineage supplied the evidence above.
