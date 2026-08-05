"""Regression coverage for the independent artifact-integrity QA findings."""

from __future__ import annotations

import re
from pathlib import Path

from repair_agent.agent.runner import _degradation_reason
from repair_agent.config import Settings
from repair_agent.datahub_io.links import datahub_entity_url
from repair_agent.datahub_io.mcp import build_datahub_mcp_server
from repair_agent.drift.detect import declare_drift
from repair_agent.models import ImpactReport, LineageEdge, LineageGraph, LineageNode
from repair_agent.pr.mermaid import mermaid_edges
from tests.support import dataset_urn


def test_datahub_links_use_entity_specific_frontend_routes() -> None:
    base = "http://localhost:9002"
    assert "/dataset/" in datahub_entity_url(base, dataset_urn("raw.orders"))
    assert "/tasks/" in datahub_entity_url(
        base,
        "urn:li:dataJob:(urn:li:dataFlow:(airflow,shopflow_daily,PROD),extract_recent_orders)",
    )
    assert "/pipelines/" in datahub_entity_url(base, "urn:li:dataFlow:(airflow,shopflow_daily,PROD)")
    assert "/dataProcessInstance/" in datahub_entity_url(
        base,
        "urn:li:dataProcessInstance:(example-run,datahub-repair-agent,prod)",
    )


def test_mermaid_node_identity_includes_the_column() -> None:
    source = dataset_urn("raw.orders")
    staging = dataset_urn("stg_orders")
    report = ImpactReport(
        drift=declare_drift(
            kind="RETYPE",
            dataset_urn=source,
            old_column="gross_amount",
            old_type="NUMBER(12,2)",
            new_type="VARCHAR(20)",
        ),
        graph=LineageGraph(
            nodes=[
                LineageNode(urn=source, name="shop_prod.raw.orders"),
                LineageNode(urn=staging, name="stg_orders"),
            ],
            edges=[
                LineageEdge(
                    source_urn=source,
                    target_urn=staging,
                    source_columns=["gross_amount"],
                    target_columns=["gross_amount"],
                ),
                LineageEdge(
                    source_urn=source,
                    target_urn=staging,
                    source_columns=["gross_amount"],
                    target_columns=["net_amount"],
                    transform_operation="ARITHMETIC",
                ),
            ],
        ),
    )

    rendered = mermaid_edges(report)
    assert rendered[0]["source_id"] == rendered[1]["source_id"]
    assert rendered[0]["target_id"] != rendered[1]["target_id"]
    assert all(re.fullmatch(r"n\d+", edge[key]) for edge in rendered for key in ("source_id", "target_id"))


def test_mcp_uv_tool_dir_defaults_to_durable_user_cache(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("UV_TOOL_DIR", raising=False)
    monkeypatch.setenv("HOME", "/Users/demo")

    server = build_datahub_mcp_server(Settings(_env_file=None))

    assert server.params.env["UV_TOOL_DIR"] == str(
        Path("/Users/demo/.cache/uv-repair-agent/tools")
    )

    monkeypatch.setenv("UV_TOOL_DIR", "/custom/uv-tools")
    overridden = build_datahub_mcp_server(Settings(_env_file=None))
    assert overridden.params.env["UV_TOOL_DIR"] == "/custom/uv-tools"


def test_mcp_startup_failure_names_uv_cache_recovery() -> None:
    errors = (
        "Connection closed",
        "Failed to install: idna",
        "No such file or directory",
        "uvx exited with non-zero status 1",
    )

    for error in errors:
        reason = _degradation_reason(RuntimeError(error))
        assert "DataHub MCP server could not be started" in reason
        assert "uv cache clean" in reason
        assert "$UV_CACHE_DIR" in reason
