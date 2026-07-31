"""Deterministic PR body rendering for offline and degraded operation."""

from __future__ import annotations

from datetime import datetime

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from repair_agent.models import ImpactBucket, ImpactReport, Patch
from repair_agent.pr.mermaid import mermaid_edges


def render_pr_body(
    impact: ImpactReport,
    patches: list[Patch],
    *,
    run_id: str,
    datahub_instance: str,
    timestamp: datetime,
    narrative_summary: str | None = None,
    risk_note: str | None = None,
    reviewer_checklist: list[str] | None = None,
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
            mermaid_edges=mermaid_edges(impact),
            run_id=run_id,
            datahub_instance=datahub_instance,
            timestamp=timestamp.isoformat(),
            narrative_summary=narrative_summary,
            risk_note=risk_note,
            reviewer_checklist=reviewer_checklist or [],
        ).rstrip()
        + "\n"
    )
