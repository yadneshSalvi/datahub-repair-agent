# Migration: shop_prod.raw.orders.gross_amount

## Change

`gross_amount` remains present, but its native type changed from NUMBER(12,2) to VARCHAR(20) — detected as a retype.

The repair changes `gross_amount` to `gross_amount` for `shop_prod.raw.orders`.
Code was produced only by deterministic sqlglot/dbt/Airflow transforms; language-model
output is prose-only.

## Blast radius

- **2** code-bearing asset(s) require a patch.
- **3** downstream asset(s) are insulated by existing aliases and need review only.
- **7** asset(s) were correctly skipped because DataHub exposes no changed-column path.

## Validation and rollout

All 13 generated SQL reference(s) were checked before review; 13 resolved.
Apply the dbt changes before dependent Airflow code, run the declared dbt tests, and
monitor the DataHub incident until consumers are healthy.

## Rollback

Revert the PR commit and restore the upstream field contract. Then re-run the repair agent
so DataHub lineage and documentation match the restored schema.
