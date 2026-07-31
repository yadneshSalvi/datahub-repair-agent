# Validation — 0 hallucinated columns · 10/10 references resolved

Resolution sources: **5** against live DataHub `schemaMetadata`, **5** against the projected post-repair schema of models patched earlier in this run, **0** locally derived CTE outputs. A model patched in this same run is not yet written back to DataHub, so its post-repair schema is the correct ground truth for its consumers.

| File | Table | Column | Line | Status | Detail |
|---|---|---|---:|---|---|
| `demo-warehouse/models/marts/dim_customers.sql` | `shop_prod.analytics.stg_customers` | `customer_id` | 2 | **OK** | Resolved `shop_prod.analytics.stg_customers.customer_id` against the projected repaired schema. |
| `demo-warehouse/models/marts/dim_customers.sql` | `shop_prod.analytics.stg_customers` | `email` | 3 | **OK** | Resolved `shop_prod.analytics.stg_customers.email` against the projected repaired schema. |
| `demo-warehouse/models/marts/dim_customers.sql` | `shop_prod.analytics.stg_customers` | `full_name` | 4 | **OK** | Resolved `shop_prod.analytics.stg_customers.full_name` against the projected repaired schema. |
| `demo-warehouse/models/marts/dim_customers.sql` | `shop_prod.analytics.stg_customers` | `signup_date` | 5 | **OK** | Resolved `shop_prod.analytics.stg_customers.signup_date` against the projected repaired schema. |
| `demo-warehouse/models/marts/dim_customers.sql` | `shop_prod.analytics.stg_customers` | `country_code` | 6 | **OK** | Resolved `shop_prod.analytics.stg_customers.country_code` against the projected repaired schema. |
| `demo-warehouse/models/staging/stg_customers.sql` | `shop_prod.raw.customers` | `customer_id` | 5 | **OK** | Resolved `shop_prod.raw.customers.customer_id` against the live DataHub schema. |
| `demo-warehouse/models/staging/stg_customers.sql` | `shop_prod.raw.customers` | `email` | 6 | **OK** | Resolved `shop_prod.raw.customers.email` against the live DataHub schema. |
| `demo-warehouse/models/staging/stg_customers.sql` | `shop_prod.raw.customers` | `full_name` | 7 | **OK** | Resolved `shop_prod.raw.customers.full_name` against the live DataHub schema. |
| `demo-warehouse/models/staging/stg_customers.sql` | `shop_prod.raw.customers` | `signup_date` | 8 | **OK** | Resolved `shop_prod.raw.customers.signup_date` against the live DataHub schema. |
| `demo-warehouse/models/staging/stg_customers.sql` | `shop_prod.raw.customers` | `country_code` | 9 | **OK** | Resolved `shop_prod.raw.customers.country_code` against the live DataHub schema. |

Hard gate: **PASSED**.
