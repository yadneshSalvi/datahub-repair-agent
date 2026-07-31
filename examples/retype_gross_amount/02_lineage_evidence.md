# Column-lineage evidence

```mermaid
graph LR
    n0["shop_prod.raw.orders.gross_amount"] -->|"IDENTITY"| n1["stg_orders.gross_amount"]
    n0["shop_prod.raw.orders.gross_amount"] -->|"ARITHMETIC"| n2["stg_orders.net_amount"]
    n2["stg_orders.net_amount"] -->|"IDENTITY"| n3["fct_orders.net_revenue"]
    n3["fct_orders.net_revenue"] -->|"SUM"| n4["mart_daily_revenue.gross_revenue"]
    n3["fct_orders.net_revenue"] -->|"SUM"| n5["mart_customer_ltv.lifetime_revenue"]
    n0["shop_prod.raw.orders.gross_amount"] -->|"DIRECT_SQL_REFERENCE"| n6["extract_recent_orders.gross_amount"]
```

## Captured DataHub queries

No usage query text was captured for this window; DataHub fine-grained lineage supplied the evidence above.
