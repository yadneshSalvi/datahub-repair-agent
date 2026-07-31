"""Hard-gate proof for hallucinated column rejection."""

from __future__ import annotations

from repair_agent.drift.detect import declare_drift
from repair_agent.models import ColumnSpec, DatasetSchema, Patch
from repair_agent.validate.validator import validate_patch

ORDERS_URN = "urn:li:dataset:(urn:li:dataPlatform:snowflake,shop_prod.raw.orders,PROD)"


class FakeDataHubIO:
    """Minimal live-schema facade for validator unit tests."""

    def get_schema(self, dataset_urn: str, *, skip_cache: bool = True) -> DatasetSchema:
        del skip_cache
        if dataset_urn != ORDERS_URN:
            return DatasetSchema(dataset_urn=dataset_urn)
        return DatasetSchema(
            dataset_urn=dataset_urn,
            columns=[
                ColumnSpec(name="order_id", native_type="NUMBER", data_type="number"),
                ColumnSpec(name="order_created_at", native_type="TIMESTAMP_NTZ", data_type="time"),
                ColumnSpec(name="gross_amount", native_type="VARCHAR(20)", data_type="string"),
            ],
        )


def test_zero_hallucinated_columns_gate_rejects_specific_nonexistent_reference() -> None:
    patch = Patch(
        asset_urn="urn:li:dataJob:test",
        file_path="corrupted.sql",
        before="select order_id from shop_prod.raw.orders\n",
        after="select definitely_not_a_real_column from shop_prod.raw.orders\n",
        unified_diff="",
        kind="dbt_sql",
        references=[],
        valid=True,
        strategy="Deliberately corrupted test fixture.",
    )
    checks = validate_patch(patch, FakeDataHubIO())  # type: ignore[arg-type]
    failing = next(check for check in checks if check.column == "definitely_not_a_real_column")
    assert failing.status == "UNKNOWN_COLUMN"
    assert failing.table == "shop_prod.raw.orders"
    assert "absent" in failing.detail
    assert patch.valid is False


def test_retype_keeps_the_same_column_name_without_stale_name_failure() -> None:
    patch = Patch(
        asset_urn="urn:li:dataJob:test",
        file_path="retype.sql",
        before="select gross_amount from shop_prod.raw.orders\n",
        after="select CAST(gross_amount AS NUMBER(12,2)) AS gross_amount from shop_prod.raw.orders\n",
        unified_diff="",
        kind="dbt_sql",
        valid=False,
        strategy="Preserve numeric semantics.",
    )
    drift = declare_drift(
        kind="RETYPE",
        dataset_urn=ORDERS_URN,
        old_column="gross_amount",
        new_column="gross_amount",
        old_type="NUMBER(12,2)",
        new_type="VARCHAR(20)",
    )
    checks = validate_patch(patch, FakeDataHubIO(), drift)  # type: ignore[arg-type]
    assert all(check.status == "OK" for check in checks)
    assert patch.valid is True
