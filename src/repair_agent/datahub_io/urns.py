"""URN helpers encoding the ShopFlow namespace conventions."""

from __future__ import annotations

from datahub.emitter.mce_builder import make_dataset_urn, make_schema_field_urn

from repair_agent.config import Settings, get_settings


def raw_urn(table: str, settings: Settings | None = None) -> str:
    """Return the Snowflake URN for `shop_prod.raw.<table>`."""

    config = settings or get_settings()
    return make_dataset_urn(
        config.warehouse_platform,
        f"{config.namespace_prefix}raw.{table}",
        config.env,
    )


def dbt_urn(model: str, settings: Settings | None = None) -> str:
    """Return the dbt URN for `shop_prod.analytics.<model>`."""

    config = settings or get_settings()
    return make_dataset_urn(
        config.dbt_platform,
        f"{config.namespace_prefix}analytics.{model}",
        config.env,
    )


def field_urn(dataset_urn: str, column: str) -> str:
    """Return a schema-field URN using DataHub's required encoder."""

    return make_schema_field_urn(dataset_urn, column)
