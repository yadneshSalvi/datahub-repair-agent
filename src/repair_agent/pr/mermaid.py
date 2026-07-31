"""Shared field-level Mermaid rendering primitives."""

from __future__ import annotations

from itertools import product
from typing import TypedDict

from repair_agent.models import ImpactReport, LineageEdge


class MermaidEdge(TypedDict):
    """One rendered edge whose node identity is a dataset-and-column pair."""

    source_id: str
    source_label: str
    source_column: str
    target_id: str
    target_label: str
    target_column: str
    operation: str


def mermaid_edges(impact: ImpactReport) -> list[MermaidEdge]:
    """Build short, stable field-node ids shared by PR and evidence artifacts."""

    node_ids: dict[tuple[str, str], str] = {}
    rendered: list[MermaidEdge] = []
    for edge in impact.graph.edges:
        for source_column, target_column in _column_pairs(edge):
            source_key = (edge.source_urn, source_column)
            target_key = (edge.target_urn, target_column)
            node_ids.setdefault(source_key, f"n{len(node_ids)}")
            node_ids.setdefault(target_key, f"n{len(node_ids)}")
            rendered.append(
                {
                    "source_id": node_ids[source_key],
                    "source_label": _node_label(impact, edge.source_urn),
                    "source_column": source_column,
                    "target_id": node_ids[target_key],
                    "target_label": _node_label(impact, edge.target_urn),
                    "target_column": target_column,
                    "operation": edge.transform_operation or "LINEAGE",
                }
            )
    return rendered


def _column_pairs(edge: LineageEdge) -> list[tuple[str, str]]:
    sources = edge.source_columns or [""]
    targets = edge.target_columns or [""]
    if len(sources) == len(targets):
        return list(zip(sources, targets, strict=True))
    return list(product(sources, targets))


def _node_label(impact: ImpactReport, urn: str) -> str:
    return next((node.name for node in impact.graph.nodes if node.urn == urn), urn)
