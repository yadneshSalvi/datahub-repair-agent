# Migration: shop_prod.raw.orders.order_placed_at

## Change

`order_placed_at` disappeared and `order_created_at` appeared with the same type TIMESTAMP_NTZ at the same ordinal position (3) — inferred as a rename with 0.95 confidence.

The repair changes `order_placed_at` to `order_created_at` for `shop_prod.raw.orders`.
Code was produced only by deterministic sqlglot/dbt/Airflow transforms; language-model
output is prose-only.

## Blast radius

- **3** code-bearing asset(s) require a patch.
- **2** downstream asset(s) are insulated by existing aliases and need review only.
- **7** asset(s) were correctly skipped because DataHub exposes no changed-column path.

## Validation and rollout

All 23 generated SQL reference(s) were checked before review; 23 resolved.
Apply the dbt changes before dependent Airflow code, run the declared dbt tests, and
monitor the DataHub incident until consumers are healthy.

## Rollback

Revert the PR commit and restore the upstream field contract. Then re-run the repair agent
so DataHub lineage and documentation match the restored schema.
