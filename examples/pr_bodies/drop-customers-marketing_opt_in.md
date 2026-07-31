## Summary

Repair shop_prod.raw.customers: `marketing_opt_in` → `∅` (DROP, 1.00 confidence).

`marketing_opt_in` disappeared from the live schema and no added column met the 0.55 rename-similarity threshold — detected as a drop.

The upstream drop was traced through DataHub column lineage. The deterministic engine generated 4 surgical patch(es), while 0 downstream model(s) were proven insulated and 10 asset(s) were skipped with explicit evidence.

> **Risk note:** Risk is bounded by the validator hard gate: 10/10 generated references resolved and no unresolved column is allowed into the PR. Review the lineage-derived skip reasons and deploy dbt models before dependent Airflow jobs.

## Lineage evidence

```mermaid
graph LR
    n0["shop_prod.raw.customers.marketing_opt_in"] -->|"IDENTITY"| n1["stg_customers.marketing_opt_in"]
    n1["stg_customers.marketing_opt_in"] -->|"IDENTITY"| n2["dim_customers.is_marketable"]
```

## Files changed

| File | Kind | Deterministic strategy |
|---|---|---|
| `demo-warehouse/models/marts/dim_customers.sql` | dbt_sql | Commented every SELECT entry derived from dropped `marketing_opt_in` with repair provenance and a data-team TODO; nothing was silently deleted. |
| `demo-warehouse/models/marts/schema.yml` | dbt_schema_yml | Removed metadata and tests for outputs derived from dropped `marketing_opt_in` after preserving the SQL as a commented deprecation record. |
| `demo-warehouse/models/staging/stg_customers.sql` | dbt_sql | Commented every SELECT entry derived from dropped `marketing_opt_in` with repair provenance and a data-team TODO; nothing was silently deleted. |
| `demo-warehouse/models/staging/schema.yml` | dbt_schema_yml | Removed metadata and tests for outputs derived from dropped `marketing_opt_in` after preserving the SQL as a commented deprecation record. |

### Reviewer checklist

- [ ] Confirm the upstream schema change and rollout order with the source owner.
- [ ] Review every downstream-unaffected and correctly-skipped reason against the lineage graph.
- [ ] Run the dbt tests and dependent Airflow task in staging before production deployment.
- [ ] Verify the DataHub incident, field documentation, tags, and corrected column lineage after merge.

## Validation — 0 hallucinated columns · 10/10 references resolved

Every column reference below was resolved before this PR was allowed to open. References to
datasets DataHub already knows about are checked against **live `schemaMetadata`**; references
to models patched earlier in this same repair set are checked against their **projected
post-repair schema**, because DataHub still holds their pre-repair schema until write-back.
A single unresolvable reference blocks the whole patch — the gate is enforced, not advisory.

| Table | Column | Line | Status | Evidence |
|---|---|---:|---|---|
| `shop_prod.analytics.stg_customers` | `customer_id` | 2 | **OK** | Resolved `shop_prod.analytics.stg_customers.customer_id` against the projected repaired schema. |
| `shop_prod.analytics.stg_customers` | `email` | 3 | **OK** | Resolved `shop_prod.analytics.stg_customers.email` against the projected repaired schema. |
| `shop_prod.analytics.stg_customers` | `full_name` | 4 | **OK** | Resolved `shop_prod.analytics.stg_customers.full_name` against the projected repaired schema. |
| `shop_prod.analytics.stg_customers` | `signup_date` | 5 | **OK** | Resolved `shop_prod.analytics.stg_customers.signup_date` against the projected repaired schema. |
| `shop_prod.analytics.stg_customers` | `country_code` | 6 | **OK** | Resolved `shop_prod.analytics.stg_customers.country_code` against the projected repaired schema. |
| `shop_prod.raw.customers` | `customer_id` | 5 | **OK** | Resolved `shop_prod.raw.customers.customer_id` against the live DataHub schema. |
| `shop_prod.raw.customers` | `email` | 6 | **OK** | Resolved `shop_prod.raw.customers.email` against the live DataHub schema. |
| `shop_prod.raw.customers` | `full_name` | 7 | **OK** | Resolved `shop_prod.raw.customers.full_name` against the live DataHub schema. |
| `shop_prod.raw.customers` | `signup_date` | 8 | **OK** | Resolved `shop_prod.raw.customers.signup_date` against the live DataHub schema. |
| `shop_prod.raw.customers` | `country_code` | 9 | **OK** | Resolved `shop_prod.raw.customers.country_code` against the live DataHub schema. |

## Downstream but unaffected

- None for this drift.

## Correctly skipped

- **dim_products** — In the table-level downstream graph, but consumes `stg_products` columns {category, list_price, product_id, product_name, sku}; none is on the exact `shop_prod.raw.customers.marketing_opt_in` column-lineage path.
- **extract_recent_orders** — No exact changed-column reference; configured Airflow SQL consumes `customer_id`, `gross_amount`, `order_id`, `order_placed_at`, not `marketing_opt_in`.
- **fct_orders** — In the table-level downstream graph, but consumes `stg_order_items` columns {order_id}; `stg_orders` columns {customer_id, net_amount, order_id, order_placed_at, order_status}; none is on the exact `shop_prod.raw.customers.marketing_opt_in` column-lineage path.
- **mart_customer_ltv** — In the table-level downstream graph, but consumes `dim_customers` columns {country_code, customer_id}; `fct_orders` columns {net_revenue, order_date, order_id}; none is on the exact `shop_prod.raw.customers.marketing_opt_in` column-lineage path.
- **mart_daily_revenue** — In the table-level downstream graph, but consumes `fct_orders` columns {net_revenue, order_date, order_id}; none is on the exact `shop_prod.raw.customers.marketing_opt_in` column-lineage path.
- **mart_product_performance** — In the table-level downstream graph, but consumes `dim_products` columns {category, product_id, sku}; `stg_order_items` columns {line_total, quantity}; none is on the exact `shop_prod.raw.customers.marketing_opt_in` column-lineage path.
- **stg_order_items** — In the table-level downstream graph, but consumes `order_items` columns {order_id, order_item_id, product_id, quantity, unit_price}; none is on the exact `shop_prod.raw.customers.marketing_opt_in` column-lineage path.
- **stg_orders** — In the table-level downstream graph, but consumes `orders` columns {customer_id, discount_amount, gross_amount, order_id, order_placed_at, order_status}; none is on the exact `shop_prod.raw.customers.marketing_opt_in` column-lineage path.
- **stg_products** — In the table-level downstream graph, but consumes `products` columns {category, list_price, product_id, product_name, sku}; none is on the exact `shop_prod.raw.customers.marketing_opt_in` column-lineage path.
- **stg_web_events** — In the table-level downstream graph, but consumes `web_events` columns {customer_id, event_at, event_id, event_type, session_id}; none is on the exact `shop_prod.raw.customers.marketing_opt_in` column-lineage path.

## Captured queries

No captured usage queries were present in DataHub for this repair window; column lineage remains the impact authority.

## DataHub deep links

- [shop_prod.raw.customers](http://localhost:9002/dataset/urn%3Ali%3Adataset%3A%28urn%3Ali%3AdataPlatform%3Asnowflake%2Cshop_prod.raw.customers%2CPROD%29)
- [dim_customers](http://localhost:9002/dataset/urn%3Ali%3Adataset%3A%28urn%3Ali%3AdataPlatform%3Adbt%2Cshop_prod.analytics.dim_customers%2CPROD%29)
- [stg_customers](http://localhost:9002/dataset/urn%3Ali%3Adataset%3A%28urn%3Ali%3AdataPlatform%3Adbt%2Cshop_prod.analytics.stg_customers%2CPROD%29)

---

Generated by **Schema-Drift Auto-Repair Agent** · run `example-drop_marketing_opt_in` · DataHub `http://localhost:8081` · 2026-07-31T23:12:18.839140+00:00
