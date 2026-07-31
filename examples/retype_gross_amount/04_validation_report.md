# Validation — 0 hallucinated columns · 13/13 references resolved

Resolution sources: **13** against live DataHub `schemaMetadata`, **0** against the projected post-repair schema of models patched earlier in this run, **0** locally derived CTE outputs. A model patched in this same run is not yet written back to DataHub, so its post-repair schema is the correct ground truth for its consumers.

| File | Table | Column | Line | Status | Detail |
|---|---|---|---:|---|---|
| `demo-warehouse/dags/shopflow_daily.py` | `shop_prod.raw.orders` | `order_id` | 2 | **OK** | Resolved `shop_prod.raw.orders.order_id` against the live DataHub schema. |
| `demo-warehouse/dags/shopflow_daily.py` | `shop_prod.raw.orders` | `customer_id` | 2 | **OK** | Resolved `shop_prod.raw.orders.customer_id` against the live DataHub schema. |
| `demo-warehouse/dags/shopflow_daily.py` | `shop_prod.raw.orders` | `order_placed_at` | 2 | **OK** | Resolved `shop_prod.raw.orders.order_placed_at` against the live DataHub schema. |
| `demo-warehouse/dags/shopflow_daily.py` | `shop_prod.raw.orders` | `gross_amount` | 2 | **OK** | Resolved `shop_prod.raw.orders.gross_amount` against the live DataHub schema. |
| `demo-warehouse/dags/shopflow_daily.py` | `shop_prod.raw.orders` | `order_placed_at` | 4 | **OK** | Resolved `shop_prod.raw.orders.order_placed_at` against the live DataHub schema. |
| `demo-warehouse/models/staging/stg_orders.sql` | `shop_prod.raw.orders` | `order_id` | 5 | **OK** | Resolved `shop_prod.raw.orders.order_id` against the live DataHub schema. |
| `demo-warehouse/models/staging/stg_orders.sql` | `shop_prod.raw.orders` | `customer_id` | 6 | **OK** | Resolved `shop_prod.raw.orders.customer_id` against the live DataHub schema. |
| `demo-warehouse/models/staging/stg_orders.sql` | `shop_prod.raw.orders` | `order_placed_at` | 7 | **OK** | Resolved `shop_prod.raw.orders.order_placed_at` against the live DataHub schema. |
| `demo-warehouse/models/staging/stg_orders.sql` | `shop_prod.raw.orders` | `order_status` | 8 | **OK** | Resolved `shop_prod.raw.orders.order_status` against the live DataHub schema. |
| `demo-warehouse/models/staging/stg_orders.sql` | `shop_prod.raw.orders` | `gross_amount` | 9 | **OK** | Resolved `shop_prod.raw.orders.gross_amount` against the live DataHub schema. |
| `demo-warehouse/models/staging/stg_orders.sql` | `shop_prod.raw.orders` | `gross_amount` | 10 | **OK** | Resolved `shop_prod.raw.orders.gross_amount` against the live DataHub schema. |
| `demo-warehouse/models/staging/stg_orders.sql` | `shop_prod.raw.orders` | `discount_amount` | 10 | **OK** | Resolved `shop_prod.raw.orders.discount_amount` against the live DataHub schema. |
| `demo-warehouse/models/staging/stg_orders.sql` | `shop_prod.raw.orders` | `order_status` | 12 | **OK** | Resolved `shop_prod.raw.orders.order_status` against the live DataHub schema. |

Hard gate: **PASSED**.
