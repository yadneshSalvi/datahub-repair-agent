"""Deterministic PR body rendering for offline and degraded operation."""

from __future__ import annotations

import re
from datetime import datetime

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from repair_agent.models import ImpactBucket, ImpactReport, Patch


def render_pr_body(
    impact: ImpactReport,
    patches: list[Patch],
    *,
    run_id: str,
    datahub_instance: str,
    timestamp: datetime,
) -> str:
    """Render the required PR sections from engine output only."""

    environment = Environment(
        loader=PackageLoader("repair_agent.pr", "templates"),
        autoescape=select_autoescape(default=False),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = environment.get_template("pr_body.md.j2")
    references = [reference for patch in patches for reference in patch.references]
    unaffected = [asset for asset in impact.assets if asset.bucket is ImpactBucket.DOWNSTREAM_UNAFFECTED]
    skipped = [asset for asset in impact.assets if asset.bucket is ImpactBucket.SKIPPED]
    captured = [
        {"asset": asset.name, "queries": asset.captured_queries} for asset in impact.assets if asset.captured_queries
    ]
    links = [
        {"name": node.name, "url": node.datahub_url}
        for node in impact.graph.nodes
        if node.datahub_url and (node.urn == impact.drift.dataset_urn or node.bucket is ImpactBucket.REQUIRES_PATCH)
    ]
    mermaid_edges = [
        {
            "source_id": _mermaid_id(edge.source_urn),
            "source_label": _node_label(impact, edge.source_urn),
            "target_id": _mermaid_id(edge.target_urn),
            "target_label": _node_label(impact, edge.target_urn),
            "operation": edge.transform_operation or "LINEAGE",
            "source_column": ", ".join(edge.source_columns),
            "target_column": ", ".join(edge.target_columns),
        }
        for edge in impact.graph.edges
    ]
    return (
        template.render(
            drift=impact.drift,
            patches=patches,
            references=references,
            resolved=sum(reference.status == "OK" for reference in references),
            total_references=len(references),
            unaffected=unaffected,
            skipped=skipped,
            captured=captured,
            links=links,
            mermaid_edges=mermaid_edges,
            run_id=run_id,
            datahub_instance=datahub_instance,
            timestamp=timestamp.isoformat(),
        ).rstrip()
        + "\n"
    )


def _mermaid_id(value: str) -> str:
    return "n_" + re.sub(r"[^a-zA-Z0-9_]", "_", value)


def _node_label(impact: ImpactReport, urn: str) -> str:
    for node in impact.graph.nodes:
        if node.urn == urn:
            return node.name
    return urn
