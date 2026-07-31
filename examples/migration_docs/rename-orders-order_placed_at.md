## Change
Rename `shop_prod.raw.orders.order_placed_at` to `order_created_at`.

The replacement has the same `TIMESTAMP_NTZ` type and ordinal position (3). Rename confidence: 0.95.

## Immutable patch scope
Apply the supplied deterministic patches without modification:

- `demo-warehouse/dags/shopflow_daily.py`: two exact references in `RECENT_ORDERS_SQL`.
- `demo-warehouse/models/marts/fct_orders.sql`: one exact AST column reference.
- `demo-warehouse/models/staging/stg_orders.sql`: one exact AST column reference.
- `demo-warehouse/models/staging/schema.yml`: rename the `stg_orders` metadata entry, preserve description provenance, and include the supplied built-in test.

No changes are required for `mart_customer_ltv` or `mart_daily_revenue`; review only. All listed skipped assets are outside the exact column-lineage path.

## Rollout
1. Confirm the source schema exposes `order_created_at` as `TIMESTAMP_NTZ` at ordinal position 3 and no longer exposes `order_placed_at`.
2. Deploy the four supplied patches together.
3. Run the staging model and its metadata test.
4. Run `fct_orders`.
5. Run `extract_recent_orders`.
6. Resume normal downstream scheduling after validation passes.

## Validation
- Confirm repair resolution remains **23/23**.
- Verify no patched asset still references `order_placed_at`.
- Verify `stg_orders` exposes the preserved downstream output contract expected by lineage consumers.
- Confirm the added built-in dbt test passes.
- Confirm `fct_orders` and `extract_recent_orders` complete successfully.
- Review `mart_customer_ltv` and `mart_daily_revenue` to confirm their upstream `order_date` remains populated and stable.

## Monitoring
For the first full production cycle, monitor:

- Airflow status and logs for `extract_recent_orders`.
- dbt failures or test regressions for `stg_orders` and `fct_orders`.
- Missing-column errors mentioning either timestamp name.
- Null-rate, row-count, and freshness changes along the affected order-date lineage.
- Unexpected changes in `mart_customer_ltv` and `mart_daily_revenue`.

## Rollback
If validation fails:

1. Pause affected downstream scheduling.
2. Revert the four supplied patches as one deployment unit.
3. Restore processing only if the source again exposes `order_placed_at`; otherwise keep affected jobs paused because the prior references cannot operate against the renamed source.
4. Re-run validation after source and deployment state are aligned.

Do not partially roll back or alter the deterministic patches.