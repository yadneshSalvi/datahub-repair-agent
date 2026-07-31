## Change
Rename `shop_prod.raw.orders.order_placed_at` to `order_created_at`.

- Type unchanged: `TIMESTAMP_NTZ`
- Ordinal unchanged: `3`
- Rename confidence: `0.95`
- Validation status: **23/23 resolved**

## Immutable patch set
Apply the supplied deterministic patches without modification:

- `demo-warehouse/dags/shopflow_daily.py`
  - Updated the two exact references in `RECENT_ORDERS_SQL`.
- `demo-warehouse/models/marts/fct_orders.sql`
  - Updated the exact AST column reference; preserved aliases and formatting.
- `demo-warehouse/models/staging/stg_orders.sql`
  - Updated the exact AST column reference; preserved aliases and formatting.
- `demo-warehouse/models/staging/schema.yml`
  - Renamed the `stg_orders` metadata entry, retained its description with provenance, and added a built-in test.

## Rollout
1. Confirm the source schema exposes `order_created_at` as `TIMESTAMP_NTZ` at ordinal 3 and no longer exposes `order_placed_at`.
2. Deploy the complete patch set atomically through the normal promotion process.
3. Run the staging model and its metadata test.
4. Run `fct_orders` and the `extract_recent_orders` Airflow task.
5. Resume the normal downstream schedule after required validations pass.

## Validation
- Verify no exact `order_placed_at` references remain in the three repaired SQL locations or the `stg_orders` metadata entry.
- Confirm `stg_orders`, `fct_orders`, and `extract_recent_orders` complete successfully.
- Confirm timestamp values populate through the existing output aliases without type or semantic changes.
- Review, but do not patch, `mart_customer_ltv` and `mart_daily_revenue`; both consume upstream `order_date` aliases and contain no old-column reference.
- Record the supplied repair result: **23/23 resolved**.

## Monitoring
For the first scheduled production run, monitor:

- Airflow task status and SQL compilation/runtime errors.
- dbt model and test results for `stg_orders` and `fct_orders`.
- Null-rate, row-count, and freshness changes on the affected timestamp lineage.
- Failures mentioning either `order_placed_at` or `order_created_at`.
- Downstream health for `mart_customer_ltv` and `mart_daily_revenue`.

No action is required for the explicitly skipped assets; they are outside the exact column-lineage path.

## Rollback
Rollback is valid only if the source schema is also restored to `order_placed_at`.

1. Pause affected schedules.
2. Restore the prior immutable artifact containing the old references and metadata.
3. Restore or verify the source column name as `order_placed_at` with the original type and ordinal.
4. Re-run staging, `fct_orders`, metadata tests, and `extract_recent_orders`.
5. Resume schedules after validation succeeds.

If the source remains `order_created_at`, do not roll back the patch; pause processing and escalate the schema mismatch instead.