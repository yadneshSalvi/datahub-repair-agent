"""Offline DataHub facade that mirrors the seeded ShopFlow catalog."""

from __future__ import annotations

from datahub.emitter.mce_builder import make_data_job_urn, make_dataset_urn

from repair_agent.models import ColumnImpactHit, ColumnSpec, DatasetSchema, FglEdge
from scripts.seed_datahub import DATASET_DEFINITIONS, MODEL_LINEAGE


def dataset_urn(key: str) -> str:
    definition = DATASET_DEFINITIONS[key]
    return make_dataset_urn(definition.platform, definition.name, "PROD")


class OfflineDataHubIO:
    """Implement engine reads from the static seed definitions with rename drift active."""

    def preflight(self) -> dict[str, object]:
        return {"datahub": {"serverType": "offline-test"}}

    def get_schema(self, urn: str, *, skip_cache: bool = True) -> DatasetSchema:
        del skip_cache
        key = next((name for name in DATASET_DEFINITIONS if dataset_urn(name) == urn), None)
        if key is None:
            return DatasetSchema(dataset_urn=urn)
        columns = []
        for field in DATASET_DEFINITIONS[key].columns:
            name = "order_created_at" if key == "raw.orders" and field.name == "order_placed_at" else field.name
            columns.append(
                ColumnSpec(
                    name=name,
                    native_type=field.native_type,
                    data_type=field.logical_type,
                    description=field.description,
                    nullable=field.nullable,
                )
            )
        return DatasetSchema(dataset_urn=urn, columns=columns)

    def column_impact(self, urn: str, column: str, max_hops: int = 3) -> list[ColumnImpactHit]:
        del urn, column, max_hops
        return [
            _hit("stg_orders", 1, ["order_placed_at"]),
            _hit("fct_orders", 2, ["order_placed_at", "order_date"]),
            _hit("mart_daily_revenue", 3, ["order_placed_at", "order_date"]),
            _hit("mart_customer_ltv", 3, ["order_placed_at", "order_date", "first_order_date"]),
        ]

    def table_downstreams(self, urn: str, max_hops: int = 3) -> list[ColumnImpactHit]:
        del urn, max_hops
        hits = [_hit(key, min(3, 1 + int(not key.startswith("stg_"))), []) for key in MODEL_LINEAGE]
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
        return [dataset_urn(key) for key in DATASET_DEFINITIONS]

    def fine_grained_lineage(self, urn: str, *, skip_cache: bool = True) -> list[FglEdge]:
        del skip_cache
        key = next((name for name in MODEL_LINEAGE if dataset_urn(name) == urn), None)
        if key is None:
            return []
        edges = []
        for output, mapping in MODEL_LINEAGE[key].items():
            for upstream_key, upstream_column in mapping["upstreams"]:
                edges.append(
                    FglEdge(
                        upstream_urn=dataset_urn(upstream_key),
                        upstream_path=upstream_column,
                        downstream_urn=urn,
                        downstream_path=output,
                        transform_operation=mapping["operation"],
                    )
                )
        return edges

    def dataset_queries(self, urn: str, column: str | None = None, *, skip_cache: bool = True) -> list[str]:
        del urn, column, skip_cache
        return []


def _hit(key: str, hops: int, columns: list[str]) -> ColumnImpactHit:
    return ColumnImpactHit(
        urn=dataset_urn(key),
        entity_type="DATASET",
        hops=hops,
        direction="downstream",
        matched_columns=columns,
    )
