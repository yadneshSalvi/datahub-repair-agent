# Column-lineage evidence

```mermaid
graph LR
    n0a["shop_prod.raw.orders.gross_amount"] -->|"IDENTITY"| n0b["stg_orders.gross_amount"]
    n1a["shop_prod.raw.orders.gross_amount"] -->|"ARITHMETIC"| n1b["stg_orders.net_amount"]
    n2a["stg_orders.net_amount"] -->|"IDENTITY"| n2b["fct_orders.net_revenue"]
    n3a["fct_orders.net_revenue"] -->|"SUM"| n3b["mart_customer_ltv.lifetime_revenue"]
    n4a["fct_orders.net_revenue"] -->|"SUM"| n4b["mart_daily_revenue.gross_revenue"]
    n5a["shop_prod.raw.orders.gross_amount"] -->|"DIRECT_SQL_REFERENCE"| n5b["extract_recent_orders.gross_amount"]
```

## Captured DataHub queries

No usage query text was captured for this window; DataHub fine-grained lineage supplied the evidence above.
