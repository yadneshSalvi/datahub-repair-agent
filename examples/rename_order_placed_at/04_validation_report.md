# Validation — 0 hallucinated columns · 23/23 references resolved

Resolution sources: **15** against live DataHub `schemaMetadata`, **6** against the projected post-repair schema of models patched earlier in this run, **2** locally derived CTE outputs. A model patched in this same run is not yet written back to DataHub, so its post-repair schema is the correct ground truth for its consumers.

| File | Table | Column | Line | Status | Detail |
|---|---|---|---:|---|---|
| `demo-warehouse/dags/shopflow_daily.py` | `shop_prod.raw.orders` | `order_id` | 2 | **OK** | Resolved `shop_prod.raw.orders.order_id` against the live DataHub schema. |
| `demo-warehouse/dags/shopflow_daily.py` | `shop_prod.raw.orders` | `customer_id` | 2 | **OK** | Resolved `shop_prod.raw.orders.customer_id` against the live DataHub schema. |
| `demo-warehouse/dags/shopflow_daily.py` | `shop_prod.raw.orders` | `order_created_at` | 2 | **OK** | Resolved `shop_prod.raw.orders.order_created_at` against the live DataHub schema. |
| `demo-warehouse/dags/shopflow_daily.py` | `shop_prod.raw.orders` | `gross_amount` | 2 | **OK** | Resolved `shop_prod.raw.orders.gross_amount` against the live DataHub schema. |
| `demo-warehouse/dags/shopflow_daily.py` | `shop_prod.raw.orders` | `order_created_at` | 4 | **OK** | Resolved `shop_prod.raw.orders.order_created_at` against the live DataHub schema. |
| `demo-warehouse/models/marts/fct_orders.sql` | `shop_prod.analytics.stg_order_items` | `order_id` | 5 | **OK** | Resolved `shop_prod.analytics.stg_order_items.order_id` against the live DataHub schema. |
| `demo-warehouse/models/marts/fct_orders.sql` | `shop_prod.analytics.stg_order_items` | `order_id` | 7 | **OK** | Resolved `shop_prod.analytics.stg_order_items.order_id` against the live DataHub schema. |
| `demo-warehouse/models/marts/fct_orders.sql` | `shop_prod.analytics.stg_orders` | `order_id` | 10 | **OK** | Resolved `shop_prod.analytics.stg_orders.order_id` against the projected repaired schema. |
| `demo-warehouse/models/marts/fct_orders.sql` | `shop_prod.analytics.stg_orders` | `customer_id` | 11 | **OK** | Resolved `shop_prod.analytics.stg_orders.customer_id` against the projected repaired schema. |
| `demo-warehouse/models/marts/fct_orders.sql` | `shop_prod.analytics.stg_orders` | `order_created_at` | 12 | **OK** | Resolved `shop_prod.analytics.stg_orders.order_created_at` against the projected repaired schema. |
| `demo-warehouse/models/marts/fct_orders.sql` | `shop_prod.analytics.stg_orders` | `order_status` | 13 | **OK** | Resolved `shop_prod.analytics.stg_orders.order_status` against the projected repaired schema. |
| `demo-warehouse/models/marts/fct_orders.sql` | `CTE i` | `item_count` | 14 | **OK** | Resolved `i.item_count` as a locally derived CTE output; its input references are validated separately. |
| `demo-warehouse/models/marts/fct_orders.sql` | `shop_prod.analytics.stg_orders` | `net_amount` | 15 | **OK** | Resolved `shop_prod.analytics.stg_orders.net_amount` against the projected repaired schema. |
| `demo-warehouse/models/marts/fct_orders.sql` | `shop_prod.analytics.stg_orders` | `order_id` | 17 | **OK** | Resolved `shop_prod.analytics.stg_orders.order_id` against the projected repaired schema. |
| `demo-warehouse/models/marts/fct_orders.sql` | `CTE i` | `order_id` | 17 | **OK** | Resolved `i.order_id` as a locally derived CTE output; its input references are validated separately. |
| `demo-warehouse/models/staging/stg_orders.sql` | `shop_prod.raw.orders` | `order_id` | 5 | **OK** | Resolved `shop_prod.raw.orders.order_id` against the live DataHub schema. |
| `demo-warehouse/models/staging/stg_orders.sql` | `shop_prod.raw.orders` | `customer_id` | 6 | **OK** | Resolved `shop_prod.raw.orders.customer_id` against the live DataHub schema. |
| `demo-warehouse/models/staging/stg_orders.sql` | `shop_prod.raw.orders` | `order_created_at` | 7 | **OK** | Resolved `shop_prod.raw.orders.order_created_at` against the live DataHub schema. |
| `demo-warehouse/models/staging/stg_orders.sql` | `shop_prod.raw.orders` | `order_status` | 8 | **OK** | Resolved `shop_prod.raw.orders.order_status` against the live DataHub schema. |
| `demo-warehouse/models/staging/stg_orders.sql` | `shop_prod.raw.orders` | `gross_amount` | 9 | **OK** | Resolved `shop_prod.raw.orders.gross_amount` against the live DataHub schema. |
| `demo-warehouse/models/staging/stg_orders.sql` | `shop_prod.raw.orders` | `gross_amount` | 10 | **OK** | Resolved `shop_prod.raw.orders.gross_amount` against the live DataHub schema. |
| `demo-warehouse/models/staging/stg_orders.sql` | `shop_prod.raw.orders` | `discount_amount` | 10 | **OK** | Resolved `shop_prod.raw.orders.discount_amount` against the live DataHub schema. |
| `demo-warehouse/models/staging/stg_orders.sql` | `shop_prod.raw.orders` | `order_status` | 12 | **OK** | Resolved `shop_prod.raw.orders.order_status` against the live DataHub schema. |

Hard gate: **PASSED**.
