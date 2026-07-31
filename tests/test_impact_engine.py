"""The complete seeded rename classification without network access."""

from __future__ import annotations

from datahub.emitter.mce_builder import make_data_job_urn, make_dataset_urn

from repair_agent.config import Settings
from repair_agent.drift.detect import declare_drift
from repair_agent.impact.engine import analyze
from repair_agent.models import ColumnImpactHit, FglEdge, ImpactBucket
from scripts.seed_datahub import DATASET_DEFINITIONS, MODEL_LINEAGE


def _urn(key: str) -> str:
    definition = DATASET_DEFINITIONS[key]
    return make_dataset_urn(definition.platform, definition.name, "PROD")


class FakeDataHubIO:
    def column_impact(self, dataset_urn: str, column: str, max_hops: int = 3) -> list[ColumnImpactHit]:
        del dataset_urn, column, max_hops
        return [
            ColumnImpactHit(
                urn=_urn("stg_orders"),
                entity_type="DATASET",
                hops=1,
                direction="downstream",
                matched_columns=["order_placed_at"],
            ),
            ColumnImpactHit(
                urn=_urn("fct_orders"),
                entity_type="DATASET",
                hops=2,
                direction="downstream",
                matched_columns=["order_placed_at", "order_date"],
            ),
            ColumnImpactHit(
                urn=_urn("mart_daily_revenue"),
                entity_type="DATASET",
                hops=3,
                direction="downstream",
                matched_columns=["order_placed_at", "order_date"],
            ),
            ColumnImpactHit(
                urn=_urn("mart_customer_ltv"),
                entity_type="DATASET",
                hops=3,
                direction="downstream",
                matched_columns=["order_placed_at", "order_date", "first_order_date"],
            ),
        ]

    def table_downstreams(self, dataset_urn: str, max_hops: int = 3) -> list[ColumnImpactHit]:
        del dataset_urn, max_hops
        hits = [
            ColumnImpactHit(
                urn=_urn(key),
                entity_type="DATASET",
                hops=min(3, 1 + int(not key.startswith("stg_"))),
                direction="downstream",
            )
            for key in MODEL_LINEAGE
        ]
        hits.append(
            ColumnImpactHit(
                urn=make_data_job_urn("airflow", "shopflow_daily", "extract_recent_orders", "PROD"),
                name="extract_recent_orders",
                entity_type="DATA_JOB",
                hops=1,
                direction="downstream",
            )
        )
        return hits

    def list_namespace_datasets(self, prefix: str, *, skip_cache: bool = True) -> list[str]:
        del prefix, skip_cache
        return [_urn(key) for key in MODEL_LINEAGE]

    def fine_grained_lineage(self, dataset_urn: str, *, skip_cache: bool = True) -> list[FglEdge]:
        del skip_cache
        key = next(key for key in MODEL_LINEAGE if _urn(key) == dataset_urn)
        edges = []
        for output, mapping in MODEL_LINEAGE[key].items():
            for upstream_key, upstream_column in mapping["upstreams"]:
                edges.append(
                    FglEdge(
                        upstream_urn=_urn(upstream_key),
                        upstream_path=upstream_column,
                        downstream_urn=dataset_urn,
                        downstream_path=output,
                        transform_operation=mapping["operation"],
                    )
                )
        return edges

    def dataset_queries(self, dataset_urn: str, column: str | None = None, *, skip_cache: bool = True) -> list[str]:
        del dataset_urn, column, skip_cache
        return []


def test_seeded_rename_has_the_full_expected_three_bucket_classification() -> None:
    settings = Settings(_env_file=None)
    drift = declare_drift(
        kind="RENAME",
        dataset_urn=_urn("raw.orders"),
        old_column="order_placed_at",
        new_column="order_created_at",
        old_type="TIMESTAMP_NTZ",
        new_type="TIMESTAMP_NTZ",
    )
    report = analyze(drift, FakeDataHubIO(), settings)  # type: ignore[arg-type]
    buckets = {bucket: {asset.name for asset in report.assets if asset.bucket is bucket} for bucket in ImpactBucket}
    assert buckets[ImpactBucket.REQUIRES_PATCH] == {"stg_orders", "fct_orders", "extract_recent_orders"}
    assert buckets[ImpactBucket.DOWNSTREAM_UNAFFECTED] == {"mart_daily_revenue", "mart_customer_ltv"}
    assert buckets[ImpactBucket.SKIPPED] == {
        "stg_customers",
        "stg_order_items",
        "stg_products",
        "stg_web_events",
        "dim_customers",
        "dim_products",
        "mart_product_performance",
    }
    assert all(asset.reason for asset in report.assets)
    assert report.stats == {
        "requires_patch": 3,
        "downstream_unaffected": 2,
        "skipped": 7,
        "total_scanned": 12,
        "max_hops_reached": 3,
    }
