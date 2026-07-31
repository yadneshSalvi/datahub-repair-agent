# Column-lineage evidence

```mermaid
graph LR
    n0a["shop_prod.raw.customers.marketing_opt_in"] -->|"IDENTITY"| n0b["stg_customers.marketing_opt_in"]
    n1a["stg_customers.marketing_opt_in"] -->|"IDENTITY"| n1b["dim_customers.is_marketable"]
```

## Captured DataHub queries

No usage query text was captured for this window; DataHub fine-grained lineage supplied the evidence above.
