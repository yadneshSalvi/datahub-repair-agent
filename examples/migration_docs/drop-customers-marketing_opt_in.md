# Migration: shop_prod.raw.customers.marketing_opt_in

## Change

`marketing_opt_in` disappeared from the live schema and no added column met the 0.55 rename-similarity threshold — detected as a drop.

The repair changes `marketing_opt_in` to `∅` for `shop_prod.raw.customers`.
Code was produced only by deterministic sqlglot/dbt/Airflow transforms; language-model
output is prose-only.

## Blast radius

- **2** code-bearing asset(s) require a patch.
- **0** downstream asset(s) are insulated by existing aliases and need review only.
- **10** asset(s) were correctly skipped because DataHub exposes no changed-column path.

## Validation and rollout

All 10 generated SQL reference(s) were checked before review; 10 resolved.
Apply the dbt changes before dependent Airflow code, run the declared dbt tests, and
monitor the DataHub incident until consumers are healthy.

## Rollback

Revert the PR commit and restore the upstream field contract. Then re-run the repair agent
so DataHub lineage and documentation match the restored schema.
