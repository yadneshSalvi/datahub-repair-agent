#!/usr/bin/env python3
"""Idempotently seed the complete ShopFlow demo catalog into DataHub."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from datahub.emitter.mce_builder import (
    make_data_flow_urn,
    make_data_job_urn,
    make_data_platform_urn,
    make_dataset_urn,
    make_schema_field_urn,
    make_tag_urn,
    make_user_urn,
)
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.metadata.schema_classes import (
    AuditStampClass,
    BooleanTypeClass,
    DataFlowInfoClass,
    DataJobInfoClass,
    DataJobInputOutputClass,
    DatasetLineageTypeClass,
    DatasetPropertiesClass,
    DateTypeClass,
    EditableSchemaFieldInfoClass,
    EditableSchemaMetadataClass,
    FineGrainedLineageClass,
    FineGrainedLineageDownstreamTypeClass,
    FineGrainedLineageUpstreamTypeClass,
    GlobalTagsClass,
    NumberTypeClass,
    OtherSchemaClass,
    SchemaFieldClass,
    SchemaFieldDataTypeClass,
    SchemaMetadataClass,
    StatusClass,
    StringTypeClass,
    SubTypesClass,
    TagAssociationClass,
    TagPropertiesClass,
    TimeTypeClass,
    UpstreamClass,
    UpstreamLineageClass,
)
from rich.console import Console
from rich.table import Table

from repair_agent.config import Settings, get_settings
from repair_agent.datahub_io.client import DataHubIO
from repair_agent.datahub_io.writeback import DataHubWriteback

CONSOLE = Console()
ERROR_CONSOLE = Console(stderr=True)


@dataclass(frozen=True)
class ColumnDefinition:
    """Seed-time definition of one dataset field."""

    name: str
    logical_type: str
    native_type: str
    description: str
    nullable: bool = True


@dataclass(frozen=True)
class DatasetDefinition:
    """Seed-time definition of one raw table or dbt model."""

    key: str
    platform: str
    name: str
    subtype: str
    description: str
    columns: tuple[ColumnDefinition, ...]


def column(
    name: str,
    logical_type: str,
    native_type: str,
    description: str,
    *,
    nullable: bool = True,
) -> ColumnDefinition:
    """Build a concise immutable column definition."""

    return ColumnDefinition(name, logical_type, native_type, description, nullable)


DATASET_DEFINITIONS: dict[str, DatasetDefinition] = {
    "raw.orders": DatasetDefinition(
        key="raw.orders",
        platform="snowflake",
        name="shop_prod.raw.orders",
        subtype="Table",
        description="Raw orders landed from the ShopFlow operational database.",
        columns=(
            column("order_id", "number", "NUMBER(38,0)", "Stable order primary key.", nullable=False),
            column("customer_id", "number", "NUMBER(38,0)", "Customer who placed the order.", nullable=False),
            column("order_placed_at", "time", "TIMESTAMP_NTZ", "Timestamp at which the order was placed.", nullable=False),
            column("order_status", "string", "VARCHAR(32)", "Current lifecycle status of the order.", nullable=False),
            column("gross_amount", "number", "NUMBER(12,2)", "Gross order value before discounts.", nullable=False),
            column("discount_amount", "number", "NUMBER(12,2)", "Discount applied to the order."),
            column("currency_code", "string", "VARCHAR(3)", "ISO currency code for the order value.", nullable=False),
        ),
    ),
    "raw.customers": DatasetDefinition(
        key="raw.customers",
        platform="snowflake",
        name="shop_prod.raw.customers",
        subtype="Table",
        description="Raw ShopFlow customer accounts and marketing preferences.",
        columns=(
            column("customer_id", "number", "NUMBER(38,0)", "Stable customer primary key.", nullable=False),
            column("email", "string", "VARCHAR(255)", "Customer email address classified as PII.", nullable=False),
            column("full_name", "string", "VARCHAR(255)", "Customer full name classified as PII.", nullable=False),
            column("signup_date", "date", "DATE", "Date the customer registered.", nullable=False),
            column("country_code", "string", "VARCHAR(2)", "Two-letter customer country code.", nullable=False),
            column("marketing_opt_in", "boolean", "BOOLEAN", "Whether marketing contact is permitted.", nullable=False),
        ),
    ),
    "raw.order_items": DatasetDefinition(
        key="raw.order_items",
        platform="snowflake",
        name="shop_prod.raw.order_items",
        subtype="Table",
        description="Raw line items belonging to ShopFlow orders.",
        columns=(
            column("order_item_id", "number", "NUMBER(38,0)", "Stable order-line primary key.", nullable=False),
            column("order_id", "number", "NUMBER(38,0)", "Parent order identifier.", nullable=False),
            column("product_id", "number", "NUMBER(38,0)", "Purchased product identifier.", nullable=False),
            column("quantity", "number", "NUMBER(10,0)", "Number of product units purchased.", nullable=False),
            column("unit_price", "number", "NUMBER(12,2)", "Price per product unit at purchase time.", nullable=False),
        ),
    ),
    "raw.products": DatasetDefinition(
        key="raw.products",
        platform="snowflake",
        name="shop_prod.raw.products",
        subtype="Table",
        description="Raw ShopFlow product catalog.",
        columns=(
            column("product_id", "number", "NUMBER(38,0)", "Stable product primary key.", nullable=False),
            column("sku", "string", "VARCHAR(64)", "Merchant stock-keeping unit.", nullable=False),
            column("product_name", "string", "VARCHAR(255)", "Customer-facing product name.", nullable=False),
            column("category", "string", "VARCHAR(64)", "Merchandising category.", nullable=False),
            column("list_price", "number", "NUMBER(12,2)", "Current catalog list price.", nullable=False),
        ),
    ),
    "raw.web_events": DatasetDefinition(
        key="raw.web_events",
        platform="snowflake",
        name="shop_prod.raw.web_events",
        subtype="Table",
        description="Raw ShopFlow storefront interaction events.",
        columns=(
            column("event_id", "string", "VARCHAR(64)", "Stable event identifier.", nullable=False),
            column("session_id", "string", "VARCHAR(64)", "Browser session identifier.", nullable=False),
            column("customer_id", "number", "NUMBER(38,0)", "Known customer identifier when authenticated."),
            column("event_type", "string", "VARCHAR(32)", "Storefront interaction category.", nullable=False),
            column("event_at", "time", "TIMESTAMP_NTZ", "Timestamp at which the event occurred.", nullable=False),
            column("page_url", "string", "VARCHAR(1024)", "Storefront URL associated with the event.", nullable=False),
        ),
    ),
    "stg_orders": DatasetDefinition(
        key="stg_orders",
        platform="dbt",
        name="shop_prod.analytics.stg_orders",
        subtype="Model",
        description="Clean, non-cancelled orders with a computed net amount.",
        columns=(
            column("order_id", "number", "NUMBER(38,0)", "Stable order primary key.", nullable=False),
            column("customer_id", "number", "NUMBER(38,0)", "Customer who placed the order.", nullable=False),
            column("order_placed_at", "time", "TIMESTAMP_NTZ", "Timestamp at which the order was placed.", nullable=False),
            column("order_status", "string", "VARCHAR(32)", "Current lifecycle status of the order.", nullable=False),
            column("gross_amount", "number", "NUMBER(12,2)", "Gross order value before discounts.", nullable=False),
            column("net_amount", "number", "NUMBER(12,2)", "Gross value less any discount.", nullable=False),
        ),
    ),
    "stg_customers": DatasetDefinition(
        key="stg_customers",
        platform="dbt",
        name="shop_prod.analytics.stg_customers",
        subtype="Model",
        description="Typed customer accounts and marketing preferences.",
        columns=(
            column("customer_id", "number", "NUMBER(38,0)", "Stable customer primary key.", nullable=False),
            column("email", "string", "VARCHAR(255)", "Customer email address classified as PII.", nullable=False),
            column("full_name", "string", "VARCHAR(255)", "Customer full name classified as PII.", nullable=False),
            column("signup_date", "date", "DATE", "Date the customer registered.", nullable=False),
            column("country_code", "string", "VARCHAR(2)", "Two-letter customer country code.", nullable=False),
            column("marketing_opt_in", "boolean", "BOOLEAN", "Whether marketing contact is permitted.", nullable=False),
        ),
    ),
    "stg_order_items": DatasetDefinition(
        key="stg_order_items",
        platform="dbt",
        name="shop_prod.analytics.stg_order_items",
        subtype="Model",
        description="Order lines enriched with their extended line total.",
        columns=(
            column("order_item_id", "number", "NUMBER(38,0)", "Stable order-line primary key.", nullable=False),
            column("order_id", "number", "NUMBER(38,0)", "Parent order identifier.", nullable=False),
            column("product_id", "number", "NUMBER(38,0)", "Purchased product identifier.", nullable=False),
            column("quantity", "number", "NUMBER(10,0)", "Number of product units purchased.", nullable=False),
            column("unit_price", "number", "NUMBER(12,2)", "Price per product unit at purchase time.", nullable=False),
            column("line_total", "number", "NUMBER(22,2)", "Quantity multiplied by unit price.", nullable=False),
        ),
    ),
    "stg_products": DatasetDefinition(
        key="stg_products",
        platform="dbt",
        name="shop_prod.analytics.stg_products",
        subtype="Model",
        description="Typed product catalog records.",
        columns=(
            column("product_id", "number", "NUMBER(38,0)", "Stable product primary key.", nullable=False),
            column("sku", "string", "VARCHAR(64)", "Merchant stock-keeping unit.", nullable=False),
            column("product_name", "string", "VARCHAR(255)", "Customer-facing product name.", nullable=False),
            column("category", "string", "VARCHAR(64)", "Merchandising category.", nullable=False),
            column("list_price", "number", "NUMBER(12,2)", "Current catalog list price.", nullable=False),
        ),
    ),
    "stg_web_events": DatasetDefinition(
        key="stg_web_events",
        platform="dbt",
        name="shop_prod.analytics.stg_web_events",
        subtype="Model",
        description="Storefront interaction events used by analytics.",
        columns=(
            column("event_id", "string", "VARCHAR(64)", "Stable event identifier.", nullable=False),
            column("session_id", "string", "VARCHAR(64)", "Browser session identifier.", nullable=False),
            column("customer_id", "number", "NUMBER(38,0)", "Known customer identifier when authenticated."),
            column("event_type", "string", "VARCHAR(32)", "Storefront interaction category.", nullable=False),
            column("event_at", "time", "TIMESTAMP_NTZ", "Timestamp at which the event occurred.", nullable=False),
        ),
    ),
    "fct_orders": DatasetDefinition(
        key="fct_orders",
        platform="dbt",
        name="shop_prod.analytics.fct_orders",
        subtype="Model",
        description="Order-grain fact table with item counts and net revenue.",
        columns=(
            column("order_id", "number", "NUMBER(38,0)", "Stable order primary key.", nullable=False),
            column("customer_id", "number", "NUMBER(38,0)", "Customer who placed the order.", nullable=False),
            column("order_date", "date", "DATE", "Calendar date on which the order was placed.", nullable=False),
            column("order_status", "string", "VARCHAR(32)", "Current lifecycle status of the order.", nullable=False),
            column("item_count", "number", "NUMBER(38,0)", "Number of line items in the order.", nullable=False),
            column("net_revenue", "number", "NUMBER(12,2)", "Order revenue after discounts.", nullable=False),
        ),
    ),
    "dim_customers": DatasetDefinition(
        key="dim_customers",
        platform="dbt",
        name="shop_prod.analytics.dim_customers",
        subtype="Model",
        description="Customer dimension with a normalized marketability flag.",
        columns=(
            column("customer_id", "number", "NUMBER(38,0)", "Stable customer primary key.", nullable=False),
            column("email", "string", "VARCHAR(255)", "Customer email address classified as PII.", nullable=False),
            column("full_name", "string", "VARCHAR(255)", "Customer full name classified as PII.", nullable=False),
            column("signup_date", "date", "DATE", "Date the customer registered.", nullable=False),
            column("country_code", "string", "VARCHAR(2)", "Two-letter customer country code.", nullable=False),
            column("is_marketable", "boolean", "BOOLEAN", "Whether marketing contact is permitted.", nullable=False),
        ),
    ),
    "dim_products": DatasetDefinition(
        key="dim_products",
        platform="dbt",
        name="shop_prod.analytics.dim_products",
        subtype="Model",
        description="Product dimension used by merchandising marts.",
        columns=(
            column("product_id", "number", "NUMBER(38,0)", "Stable product primary key.", nullable=False),
            column("sku", "string", "VARCHAR(64)", "Merchant stock-keeping unit.", nullable=False),
            column("product_name", "string", "VARCHAR(255)", "Customer-facing product name.", nullable=False),
            column("category", "string", "VARCHAR(64)", "Merchandising category.", nullable=False),
            column("list_price", "number", "NUMBER(12,2)", "Current catalog list price.", nullable=False),
        ),
    ),
    "mart_daily_revenue": DatasetDefinition(
        key="mart_daily_revenue",
        platform="dbt",
        name="shop_prod.analytics.mart_daily_revenue",
        subtype="Model",
        description="Daily order counts and net revenue for business reporting.",
        columns=(
            column("order_date", "date", "DATE", "Reporting calendar date.", nullable=False),
            column("order_count", "number", "NUMBER(38,0)", "Number of orders placed on the date.", nullable=False),
            column("gross_revenue", "number", "NUMBER(18,2)", "Sum of net order revenue.", nullable=False),
        ),
    ),
    "mart_customer_ltv": DatasetDefinition(
        key="mart_customer_ltv",
        platform="dbt",
        name="shop_prod.analytics.mart_customer_ltv",
        subtype="Model",
        description="Lifetime order and revenue measures by customer.",
        columns=(
            column("customer_id", "number", "NUMBER(38,0)", "Stable customer primary key.", nullable=False),
            column("country_code", "string", "VARCHAR(2)", "Two-letter customer country code.", nullable=False),
            column("lifetime_orders", "number", "NUMBER(38,0)", "Number of customer orders.", nullable=False),
            column("lifetime_revenue", "number", "NUMBER(18,2)", "Total customer net revenue.", nullable=False),
            column("first_order_date", "date", "DATE", "Date of the customer's earliest order."),
        ),
    ),
    "mart_product_performance": DatasetDefinition(
        key="mart_product_performance",
        platform="dbt",
        name="shop_prod.analytics.mart_product_performance",
        subtype="Model",
        description="Units and revenue by product for merchandising analysis.",
        columns=(
            column("product_id", "number", "NUMBER(38,0)", "Stable product primary key.", nullable=False),
            column("sku", "string", "VARCHAR(64)", "Merchant stock-keeping unit.", nullable=False),
            column("category", "string", "VARCHAR(64)", "Merchandising category.", nullable=False),
            column("units_sold", "number", "NUMBER(38,0)", "Total number of product units sold.", nullable=False),
            column("revenue", "number", "NUMBER(18,2)", "Total extended line revenue.", nullable=False),
        ),
    ),
}


MODEL_UPSTREAMS: dict[str, list[str]] = {
    "stg_orders": ["raw.orders"],
    "stg_customers": ["raw.customers"],
    "stg_order_items": ["raw.order_items"],
    "stg_products": ["raw.products"],
    "stg_web_events": ["raw.web_events"],
    "fct_orders": ["stg_orders", "stg_order_items"],
    "dim_customers": ["stg_customers"],
    "dim_products": ["stg_products"],
    "mart_daily_revenue": ["fct_orders"],
    "mart_customer_ltv": ["dim_customers", "fct_orders"],
    "mart_product_performance": ["stg_order_items", "dim_products"],
}


# Explicit, reviewable output-column lineage derived from the SQL in demo-warehouse/models.
# Each upstream is `(dataset key, fieldPath)`; no lineage inference occurs at seed time.
MODEL_LINEAGE: dict[str, dict[str, dict[str, Any]]] = {
    "stg_orders": {
        "order_id": {"upstreams": [("raw.orders", "order_id")], "operation": "IDENTITY"},
        "customer_id": {"upstreams": [("raw.orders", "customer_id")], "operation": "IDENTITY"},
        "order_placed_at": {"upstreams": [("raw.orders", "order_placed_at")], "operation": "IDENTITY"},
        "order_status": {"upstreams": [("raw.orders", "order_status")], "operation": "IDENTITY"},
        "gross_amount": {"upstreams": [("raw.orders", "gross_amount")], "operation": "IDENTITY"},
        "net_amount": {
            "upstreams": [("raw.orders", "gross_amount"), ("raw.orders", "discount_amount")],
            "operation": "ARITHMETIC",
        },
    },
    "stg_customers": {
        "customer_id": {"upstreams": [("raw.customers", "customer_id")], "operation": "IDENTITY"},
        "email": {"upstreams": [("raw.customers", "email")], "operation": "IDENTITY"},
        "full_name": {"upstreams": [("raw.customers", "full_name")], "operation": "IDENTITY"},
        "signup_date": {"upstreams": [("raw.customers", "signup_date")], "operation": "IDENTITY"},
        "country_code": {"upstreams": [("raw.customers", "country_code")], "operation": "IDENTITY"},
        "marketing_opt_in": {"upstreams": [("raw.customers", "marketing_opt_in")], "operation": "IDENTITY"},
    },
    "stg_order_items": {
        "order_item_id": {"upstreams": [("raw.order_items", "order_item_id")], "operation": "IDENTITY"},
        "order_id": {"upstreams": [("raw.order_items", "order_id")], "operation": "IDENTITY"},
        "product_id": {"upstreams": [("raw.order_items", "product_id")], "operation": "IDENTITY"},
        "quantity": {"upstreams": [("raw.order_items", "quantity")], "operation": "IDENTITY"},
        "unit_price": {"upstreams": [("raw.order_items", "unit_price")], "operation": "IDENTITY"},
        "line_total": {
            "upstreams": [("raw.order_items", "quantity"), ("raw.order_items", "unit_price")],
            "operation": "ARITHMETIC",
        },
    },
    "stg_products": {
        "product_id": {"upstreams": [("raw.products", "product_id")], "operation": "IDENTITY"},
        "sku": {"upstreams": [("raw.products", "sku")], "operation": "IDENTITY"},
        "product_name": {"upstreams": [("raw.products", "product_name")], "operation": "IDENTITY"},
        "category": {"upstreams": [("raw.products", "category")], "operation": "IDENTITY"},
        "list_price": {"upstreams": [("raw.products", "list_price")], "operation": "IDENTITY"},
    },
    "stg_web_events": {
        "event_id": {"upstreams": [("raw.web_events", "event_id")], "operation": "IDENTITY"},
        "session_id": {"upstreams": [("raw.web_events", "session_id")], "operation": "IDENTITY"},
        "customer_id": {"upstreams": [("raw.web_events", "customer_id")], "operation": "IDENTITY"},
        "event_type": {"upstreams": [("raw.web_events", "event_type")], "operation": "IDENTITY"},
        "event_at": {"upstreams": [("raw.web_events", "event_at")], "operation": "IDENTITY"},
    },
    "fct_orders": {
        "order_id": {"upstreams": [("stg_orders", "order_id")], "operation": "IDENTITY"},
        "customer_id": {"upstreams": [("stg_orders", "customer_id")], "operation": "IDENTITY"},
        "order_date": {"upstreams": [("stg_orders", "order_placed_at")], "operation": "CAST_DATE"},
        "order_status": {"upstreams": [("stg_orders", "order_status")], "operation": "IDENTITY"},
        "item_count": {"upstreams": [("stg_order_items", "order_id")], "operation": "COUNT"},
        "net_revenue": {"upstreams": [("stg_orders", "net_amount")], "operation": "IDENTITY"},
    },
    "dim_customers": {
        "customer_id": {"upstreams": [("stg_customers", "customer_id")], "operation": "IDENTITY"},
        "email": {"upstreams": [("stg_customers", "email")], "operation": "IDENTITY"},
        "full_name": {"upstreams": [("stg_customers", "full_name")], "operation": "IDENTITY"},
        "signup_date": {"upstreams": [("stg_customers", "signup_date")], "operation": "IDENTITY"},
        "country_code": {"upstreams": [("stg_customers", "country_code")], "operation": "IDENTITY"},
        "is_marketable": {"upstreams": [("stg_customers", "marketing_opt_in")], "operation": "IDENTITY"},
    },
    "dim_products": {
        "product_id": {"upstreams": [("stg_products", "product_id")], "operation": "IDENTITY"},
        "sku": {"upstreams": [("stg_products", "sku")], "operation": "IDENTITY"},
        "product_name": {"upstreams": [("stg_products", "product_name")], "operation": "IDENTITY"},
        "category": {"upstreams": [("stg_products", "category")], "operation": "IDENTITY"},
        "list_price": {"upstreams": [("stg_products", "list_price")], "operation": "IDENTITY"},
    },
    "mart_daily_revenue": {
        "order_date": {"upstreams": [("fct_orders", "order_date")], "operation": "IDENTITY"},
        "order_count": {"upstreams": [("fct_orders", "order_id")], "operation": "COUNT"},
        "gross_revenue": {"upstreams": [("fct_orders", "net_revenue")], "operation": "SUM"},
    },
    "mart_customer_ltv": {
        "customer_id": {"upstreams": [("dim_customers", "customer_id")], "operation": "IDENTITY"},
        "country_code": {"upstreams": [("dim_customers", "country_code")], "operation": "IDENTITY"},
        "lifetime_orders": {"upstreams": [("fct_orders", "order_id")], "operation": "COUNT"},
        "lifetime_revenue": {"upstreams": [("fct_orders", "net_revenue")], "operation": "SUM"},
        "first_order_date": {"upstreams": [("fct_orders", "order_date")], "operation": "MIN"},
    },
    "mart_product_performance": {
        "product_id": {"upstreams": [("dim_products", "product_id")], "operation": "IDENTITY"},
        "sku": {"upstreams": [("dim_products", "sku")], "operation": "IDENTITY"},
        "category": {"upstreams": [("dim_products", "category")], "operation": "IDENTITY"},
        "units_sold": {"upstreams": [("stg_order_items", "quantity")], "operation": "SUM"},
        "revenue": {"upstreams": [("stg_order_items", "line_total")], "operation": "SUM"},
    },
}


TYPE_CLASSES = {
    "boolean": BooleanTypeClass,
    "date": DateTypeClass,
    "number": NumberTypeClass,
    "string": StringTypeClass,
    "time": TimeTypeClass,
}


class VerificationError(RuntimeError):
    """Raised when the live catalog does not match the deterministic seed."""


def dataset_urn(definition: DatasetDefinition, settings: Settings) -> str:
    """Return a dataset URN from a seed definition."""

    platform = settings.warehouse_platform if definition.platform == "snowflake" else settings.dbt_platform
    return make_dataset_urn(platform, definition.name, settings.env)


def build_dataset_mcps(settings: Settings) -> list[Any]:
    """Build full-replacement schema, properties, subtype, and lineage MCPs."""

    stamp = AuditStampClass(time=int(time.time() * 1000), actor=make_user_urn("datahub-repair-agent"))
    mcps: list[Any] = []
    for key, definition in DATASET_DEFINITIONS.items():
        urn = dataset_urn(definition, settings)
        platform = settings.warehouse_platform if definition.platform == "snowflake" else settings.dbt_platform
        mcps.extend(
            [
                MetadataChangeProposalWrapper(entityUrn=urn, aspect=StatusClass(removed=False)),
                MetadataChangeProposalWrapper(
                    entityUrn=urn,
                    aspect=SchemaMetadataClass(
                        schemaName=definition.name,
                        platform=make_data_platform_urn(platform),
                        version=0,
                        hash="",
                        platformSchema=OtherSchemaClass(rawSchema=""),
                        fields=[
                            SchemaFieldClass(
                                fieldPath=field.name,
                                type=SchemaFieldDataTypeClass(type=TYPE_CLASSES[field.logical_type]()),
                                nativeDataType=field.native_type,
                                nullable=field.nullable,
                                description=field.description,
                            )
                            for field in definition.columns
                        ],
                        created=stamp,
                        lastModified=stamp,
                    ),
                ),
                MetadataChangeProposalWrapper(
                    entityUrn=urn,
                    aspect=DatasetPropertiesClass(
                        name=definition.name.rsplit(".", 1)[-1],
                        qualifiedName=definition.name,
                        description=definition.description,
                    ),
                ),
                MetadataChangeProposalWrapper(
                    entityUrn=urn,
                    aspect=SubTypesClass(typeNames=[definition.subtype]),
                ),
                MetadataChangeProposalWrapper(
                    entityUrn=urn,
                    aspect=_lineage_aspect(key, settings, stamp),
                ),
            ]
        )
    return mcps


def _lineage_aspect(
    dataset_key: str,
    settings: Settings,
    stamp: AuditStampClass,
) -> UpstreamLineageClass:
    downstream = DATASET_DEFINITIONS[dataset_key]
    downstream_urn = dataset_urn(downstream, settings)
    table_upstreams = [
        UpstreamClass(
            dataset=dataset_urn(DATASET_DEFINITIONS[upstream_key], settings),
            type=DatasetLineageTypeClass.TRANSFORMED,
            auditStamp=stamp,
        )
        for upstream_key in MODEL_UPSTREAMS.get(dataset_key, [])
    ]
    fine_grained = []
    for output_column, mapping in MODEL_LINEAGE.get(dataset_key, {}).items():
        upstream_fields = [
            make_schema_field_urn(
                dataset_urn(DATASET_DEFINITIONS[upstream_key], settings),
                upstream_column,
            )
            for upstream_key, upstream_column in mapping["upstreams"]
        ]
        fine_grained.append(
            FineGrainedLineageClass(
                upstreamType=FineGrainedLineageUpstreamTypeClass.FIELD_SET,
                downstreamType=FineGrainedLineageDownstreamTypeClass.FIELD,
                upstreams=upstream_fields,
                downstreams=[make_schema_field_urn(downstream_urn, output_column)],
                transformOperation=mapping["operation"],
                confidenceScore=1.0,
            )
        )
    return UpstreamLineageClass(
        upstreams=table_upstreams,
        fineGrainedLineages=fine_grained,
    )


def build_airflow_mcps(settings: Settings) -> list[Any]:
    """Build one Airflow flow and the three catalog jobs required by the demo."""

    flow_urn = make_data_flow_urn("airflow", "shopflow_daily", settings.env)
    raw_keys = [key for key in DATASET_DEFINITIONS if key.startswith("raw.")]
    staging_keys = [key for key in MODEL_UPSTREAMS if key.startswith("stg_")]
    mart_keys = [key for key in MODEL_UPSTREAMS if not key.startswith("stg_")]
    jobs = {
        "extract_recent_orders": (["raw.orders"], []),
        "run_dbt_staging": (raw_keys, staging_keys),
        "run_dbt_marts": (staging_keys, mart_keys),
    }
    mcps: list[Any] = [
        MetadataChangeProposalWrapper(
            entityUrn=flow_urn,
            aspect=DataFlowInfoClass(
                name="shopflow_daily",
                description="Daily ShopFlow extraction and dbt transformation DAG.",
                project="datahub-repair-agent",
                env=settings.env,
            ),
        )
    ]
    for job_id, (input_keys, output_keys) in jobs.items():
        job_urn = make_data_job_urn("airflow", "shopflow_daily", job_id, settings.env)
        mcps.extend(
            [
                MetadataChangeProposalWrapper(
                    entityUrn=job_urn,
                    aspect=DataJobInfoClass(
                        name=job_id,
                        type="SQL" if job_id == "extract_recent_orders" else "BASH",
                        description=f"ShopFlow Airflow task: {job_id}.",
                        flowUrn=flow_urn,
                        env=settings.env,
                    ),
                ),
                MetadataChangeProposalWrapper(
                    entityUrn=job_urn,
                    aspect=DataJobInputOutputClass(
                        inputDatasets=[dataset_urn(DATASET_DEFINITIONS[key], settings) for key in input_keys],
                        outputDatasets=[dataset_urn(DATASET_DEFINITIONS[key], settings) for key in output_keys],
                    ),
                ),
            ]
        )
    return mcps


def build_pii_tag_metadata(settings: Settings) -> list[Any]:
    """Build idempotent editable field metadata for customer PII columns."""

    customers_urn = dataset_urn(DATASET_DEFINITIONS["raw.customers"], settings)
    tag = GlobalTagsClass(tags=[TagAssociationClass(tag=make_tag_urn("pii"))])
    return [
        MetadataChangeProposalWrapper(
            entityUrn=customers_urn,
            aspect=EditableSchemaMetadataClass(
                editableSchemaFieldInfo=[
                    EditableSchemaFieldInfoClass(fieldPath="email", globalTags=tag),
                    EditableSchemaFieldInfoClass(fieldPath="full_name", globalTags=tag),
                ]
            ),
        )
    ]


def reset_namespace(io: DataHubIO, settings: Settings) -> list[str]:
    """Hard-delete only dataset names beginning with the configured namespace.

    Deletion is HARD rather than soft on purpose. A soft delete leaves the entity's rows in
    the graph index in a state that survives a subsequent re-emit: the dataset comes back,
    its ``upstreamLineage`` aspect reads back correctly over GraphQL, but its degree-1
    column-lineage edges never reappear in ``searchAcrossLineage``. The symptom is brutal to
    debug — hop-2 and hop-3 downstreams are still returned, so the graph merely looks
    *incomplete* rather than broken. A hard delete followed by the re-emit below rebuilds
    the index cleanly and was verified to restore the missing edges immediately.

    The blast radius is bounded twice over: candidates come from a namespace-filtered
    listing, and every URN is re-checked textually at the destructive call site.
    """

    known_urns = [dataset_urn(definition, settings) for definition in DATASET_DEFINITIONS.values()]
    incidents = DataHubWriteback(io, settings).clear_namespace_incidents(known_urns)
    CONSOLE.print(f"[yellow]Reset:[/] cleared {len(incidents)} incident(s) attached to ShopFlow datasets")
    candidates = dict.fromkeys(
        [*io.list_namespace_datasets(settings.namespace_prefix, skip_cache=True), *known_urns]
    )
    touched: list[str] = []
    for urn in candidates:
        # list_namespace_datasets parses the URN name and performs startswith; retain a
        # second textual guard at the destructive call site for defense in depth.
        if f",{settings.namespace_prefix}" not in urn:
            raise RuntimeError(f"Refusing to delete out-of-namespace entity: {urn}")
        if not io.graph.exists(urn):
            continue
        io.graph.delete_entity(urn=urn, hard=True)
        touched.append(urn)
    _write_reset_audit(settings, touched)
    return touched


def _write_reset_audit(settings: Settings, touched: list[str]) -> None:
    audit_path = settings.repo_root / "demo-warehouse" / ".repair-agent" / "reset_audit.json"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(
        json.dumps(
            {
                "operation": "hard_delete",
                "namespace_prefix": settings.namespace_prefix,
                "touched_urns": touched,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def write_snapshot(settings: Settings) -> Path:
    """Persist the immutable expected baseline used by the later drift detector."""

    snapshot = {
        dataset_urn(definition, settings): {
            field.name: {
                "name": field.name,
                "native_type": field.native_type,
                "data_type": field.logical_type,
                "description": field.description,
                "nullable": field.nullable,
            }
            for field in definition.columns
        }
        for definition in DATASET_DEFINITIONS.values()
    }
    snapshot_path = settings.repo_root / "demo-warehouse" / ".repair-agent" / "snapshot.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    return snapshot_path


def emit_seed(io: DataHubIO, settings: Settings, *, dry_run: bool) -> int:
    """Emit or serialize every deterministic seed proposal."""

    dataset_mcps = build_dataset_mcps(settings)
    airflow_mcps = build_airflow_mcps(settings)
    tag_metadata_mcps = build_pii_tag_metadata(settings)
    if dry_run:
        tag_urn = make_tag_urn("pii")
        tag_mcp = MetadataChangeProposalWrapper(
            entityUrn=tag_urn,
            aspect=TagPropertiesClass(
                name="pii",
                description="Personally identifiable information requiring careful handling.",
            ),
        )
        all_mcps = [*dataset_mcps, *airflow_mcps, tag_mcp, *tag_metadata_mcps]
        output_path = settings.repo_root / "demo-warehouse" / ".repair-agent" / "seed_mcps.json"
        output_path.write_text(
            json.dumps([proposal.to_obj() for proposal in all_mcps], indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        CONSOLE.print(f"[yellow]Dry run:[/] wrote {len(all_mcps)} MCPs to {output_path}")
        return len(all_mcps)

    for proposal in [*dataset_mcps, *airflow_mcps]:
        io.graph.emit_mcp(proposal)

    tag_action = DataHubWriteback(io, settings).ensure_tag_exists(
        "pii",
        "Personally identifiable information requiring careful handling.",
    )
    if not tag_action.ok:
        raise RuntimeError(tag_action.error or "Could not create the PII governance tag.")
    for proposal in tag_metadata_mcps:
        io.graph.emit_mcp(proposal)

    return len(dataset_mcps) + len(airflow_mcps) + len(tag_metadata_mcps) + 1


def verify_seed(io: DataHubIO, settings: Settings) -> None:
    """Assert and print every schema plus the target/control column impact sets."""

    table = Table(title="ShopFlow schemaMetadata fieldPaths")
    table.add_column("Dataset")
    table.add_column("Verified fieldPaths")
    for definition in DATASET_DEFINITIONS.values():
        urn = dataset_urn(definition, settings)
        actual = [field.name for field in io.get_schema(urn, skip_cache=True).columns]
        expected = [field.name for field in definition.columns]
        if actual != expected:
            raise VerificationError(
                f"Schema mismatch for {definition.name}: expected {expected}, got {actual}. "
                "Re-run the seed and inspect schemaMetadata fieldPath casing."
            )
        table.add_row(definition.name, ", ".join(actual))

    source_urn = dataset_urn(DATASET_DEFINITIONS["raw.orders"], settings)
    expected_target = {
        dataset_urn(DATASET_DEFINITIONS[key], settings)
        for key in ("stg_orders", "fct_orders", "mart_daily_revenue", "mart_customer_ltv")
    }
    expected_control = {dataset_urn(DATASET_DEFINITIONS[key], settings) for key in ("stg_orders", "fct_orders")}
    target_hits: set[str] = set()
    control_hits: set[str] = set()
    for attempt in range(1, 16):
        target_hits = {hit.urn for hit in io.column_impact(source_urn, "order_placed_at", max_hops=3)}
        control_hits = {hit.urn for hit in io.column_impact(source_urn, "order_status", max_hops=3)}
        if target_hits == expected_target and control_hits == expected_control:
            break
        if attempt < 15:
            time.sleep(2)

    if target_hits != expected_target:
        raise VerificationError(
            "Column impact mismatch for raw.orders.order_placed_at: "
            f"expected {sorted(expected_target)}, got {sorted(target_hits)}. "
            "Confirm both endpoint schemas and table-level upstreams coexist with each FGL edge."
        )
    if control_hits != expected_control:
        raise VerificationError(
            "Control impact mismatch for raw.orders.order_status: "
            f"expected {sorted(expected_control)}, got {sorted(control_hits)}."
        )
    if not control_hits < target_hits:
        raise VerificationError(
            "Control column order_status did not reach a strictly narrower dataset set than "
            "order_placed_at; the precision demonstration is invalid."
        )

    CONSOLE.print("\n[bold green]=== DATAHUB SEED VERIFICATION ===[/]")
    CONSOLE.print(table)
    CONSOLE.print(f"[bold]order_placed_at affected set ({len(target_hits)}):[/] {_display_names(target_hits)}")
    CONSOLE.print(f"[bold]CONTROL order_status set ({len(control_hits)}):[/] {_display_names(control_hits)}")
    CONSOLE.print(f"[bold green]STRICTLY NARROWER:[/] yes ({len(control_hits)} < {len(target_hits)})")
    CONSOLE.print("[bold green]VERIFICATION PASSED[/]")


def _display_names(urns: set[str]) -> str:
    names = sorted(urn.split(",")[-2].rsplit(".", 1)[-1] for urn in urns)
    return ", ".join(names)


def parse_args() -> argparse.Namespace:
    """Parse seed command-line flags."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Soft-delete only active shop_prod.* datasets before re-emitting them.",
    )
    parser.add_argument("--verify", action="store_true", help="Read back and assert the seed.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Serialize MCPs locally without writing to DataHub.",
    )
    return parser.parse_args()


def main() -> int:
    """Run preflight, optional reset, seed, snapshot, and optional verification."""

    args = parse_args()
    settings = get_settings()
    io = DataHubIO(settings)
    try:
        config = io.preflight()
        CONSOLE.print(f"[green]DataHub preflight passed:[/] {settings.datahub_gms_url} ({config['datahub']['serverType']})")
        if args.reset and args.dry_run:
            CONSOLE.print("[yellow]Dry run:[/] reset was requested but no entities will be deleted.")
            _write_reset_audit(settings, [])
        elif args.reset:
            touched = reset_namespace(io, settings)
            applied_drift = settings.repo_root / "demo-warehouse" / ".repair-agent" / "applied_drift.json"
            if applied_drift.exists():
                applied_drift.unlink()
            CONSOLE.print(
                f"[yellow]Reset:[/] hard-deleted {len(touched)} dataset(s), all under {settings.namespace_prefix}"
            )

        emitted = emit_seed(io, settings, dry_run=args.dry_run)
        snapshot_path = write_snapshot(settings)
        CONSOLE.print(f"[green]Seed complete:[/] processed {emitted} MCPs idempotently.")
        CONSOLE.print(f"[green]Baseline snapshot:[/] {snapshot_path}")
        if args.verify:
            if args.dry_run:
                raise VerificationError("--verify cannot read back a --dry-run seed; run without --dry-run.")
            verify_seed(io, settings)
        return 0
    except Exception as exc:
        ERROR_CONSOLE.print(f"[bold red]Seed failed:[/] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
