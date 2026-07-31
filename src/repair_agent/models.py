"""Shared, JSON-serializable domain models for the repair workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DriftKind(StrEnum):
    """Supported source-schema changes."""

    RENAME = "RENAME"
    RETYPE = "RETYPE"
    DROP = "DROP"
    ADD = "ADD"


class ColumnSpec(BaseModel):
    """Catalog representation of one schema field."""

    name: str
    native_type: str
    data_type: str
    description: str | None = None
    nullable: bool = True


class DatasetSchema(BaseModel):
    """Ordered schema returned for one DataHub dataset."""

    dataset_urn: str
    columns: list[ColumnSpec] = Field(default_factory=list)


class DriftEvent(BaseModel):
    """One normalized difference between a baseline and a live schema."""

    id: str
    kind: DriftKind
    dataset_urn: str
    dataset_name: str
    old_column: str | None = None
    new_column: str | None = None
    old_type: str | None = None
    new_type: str | None = None
    confidence: float
    rationale: str
    detected_at: datetime = Field(default_factory=_utc_now)


class ImpactBucket(StrEnum):
    """Precision-oriented impact classification."""

    REQUIRES_PATCH = "REQUIRES_PATCH"
    DOWNSTREAM_UNAFFECTED = "DOWNSTREAM_UNAFFECTED"
    SKIPPED = "SKIPPED"


class LineageHop(BaseModel):
    """One column-to-column hop used as impact and PR evidence."""

    upstream_urn: str
    upstream_column: str | None = None
    downstream_urn: str
    downstream_column: str | None = None
    transform_operation: str | None = None
    hops: int | None = None


class LineageNode(BaseModel):
    """Renderable node in the impact graph."""

    urn: str
    name: str
    kind: str = "dataset"
    bucket: ImpactBucket | None = None
    columns: list[str] = Field(default_factory=list)
    hops: int | None = None
    datahub_url: str | None = None


class LineageEdge(BaseModel):
    """Renderable directed edge in the impact graph."""

    source_urn: str
    target_urn: str
    source_columns: list[str] = Field(default_factory=list)
    target_columns: list[str] = Field(default_factory=list)
    transform_operation: str | None = None


class LineageGraph(BaseModel):
    """Nodes and edges consumed by the impact UI."""

    nodes: list[LineageNode] = Field(default_factory=list)
    edges: list[LineageEdge] = Field(default_factory=list)


class ColumnImpactHit(BaseModel):
    """Normalized result from DataHub's column-lineage search."""

    urn: str
    name: str | None = None
    entity_type: str
    hops: int
    direction: str
    platform: str | None = None
    matched_columns: list[str] = Field(default_factory=list)


class FglEdge(BaseModel):
    """Fine-grained lineage edge read through GraphQL."""

    upstream_urn: str
    upstream_path: str | None = None
    downstream_urn: str
    downstream_path: str | None = None
    transform_operation: str | None = None
    query: str | None = None


class ImpactedAsset(BaseModel):
    """One scanned code or catalog asset and its impact decision."""

    urn: str
    name: str
    kind: str
    bucket: ImpactBucket
    hops: int | None = None
    matched_columns: list[str] = Field(default_factory=list)
    code_path: str | None = None
    reason: str
    lineage_path: list[LineageHop] = Field(default_factory=list)
    captured_queries: list[str] = Field(default_factory=list)


class ImpactReport(BaseModel):
    """Complete, evidence-backed blast-radius result for one drift."""

    drift: DriftEvent
    assets: list[ImpactedAsset] = Field(default_factory=list)
    graph: LineageGraph = Field(default_factory=LineageGraph)
    stats: dict[str, int] = Field(default_factory=dict)


class ReferenceCheck(BaseModel):
    """Validator verdict for one table/column reference."""

    table: str
    column: str
    line: int | None = None
    status: Literal["OK", "UNKNOWN_COLUMN", "UNKNOWN_TABLE", "STALE_OLD_NAME"]
    detail: str
    #: Where the resolution evidence came from. ``live_catalog`` means the column was
    #: checked against schemaMetadata read from DataHub. ``projected_repair`` means it was
    #: checked against the post-repair schema of a model patched earlier in the same run —
    #: necessary because DataHub still holds that model's pre-repair schema until write-back.
    source: Literal["live_catalog", "projected_repair", "local_cte", "unresolved"] = "unresolved"


class Patch(BaseModel):
    """One generated and validated source-code change."""

    asset_urn: str
    file_path: str
    before: str
    after: str
    unified_diff: str
    kind: Literal["dbt_sql", "dbt_schema_yml", "airflow_python", "dbt_test"]
    references: list[ReferenceCheck] = Field(default_factory=list)
    valid: bool
    strategy: str


class FileChange(BaseModel):
    """File payload handed to a pull-request provider."""

    path: str
    content: str
    previous_content: str | None = None


class PRRequest(BaseModel):
    """Provider-neutral pull-request request."""

    branch: str
    base: str = "main"
    title: str
    body_markdown: str
    files: list[FileChange] = Field(default_factory=list)
    commit_message: str


class PullRequestResult(BaseModel):
    """Result returned by live and dry-run PR providers."""

    mode: Literal["live", "dry-run"]
    url: str
    branch: str
    title: str | None = None
    number: int | None = None
    files: list[str] = Field(default_factory=list)
    ok: bool = True
    error: str | None = None


class WritebackAction(BaseModel):
    """Best-effort DataHub write-back result rendered by the UI."""

    kind: str
    target_urn: str
    detail: str
    datahub_url: str
    ok: bool = True
    error: str | None = None


class RunEvent(BaseModel):
    """One streaming progress event for a repair run."""

    seq: int
    ts: datetime = Field(default_factory=_utc_now)
    phase: Literal["detect", "impact", "codegen", "validate", "pr", "writeback", "done"]
    level: Literal["debug", "info", "warning", "error"] = "info"
    title: str
    detail: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class RepairRun(BaseModel):
    """Aggregate state for one end-to-end repair attempt."""

    id: str
    status: Literal["running", "succeeded", "failed"] = "running"
    #: Human-readable reason the run failed. Set whenever ``status == "failed"`` so a
    #: failure can never render as a quiet, plausible-looking success.
    error: str | None = None
    #: Which phase failed (``detect``/``impact``/``codegen``/``validate``/``pr``/``writeback``).
    failed_stage: str | None = None
    #: Phases that actually produced their output, so a UI can tick only real progress
    #: instead of assuming every step succeeded.
    completed_stages: list[str] = Field(default_factory=list)
    mode: Literal["agent", "deterministic"] = "agent"
    degraded: bool = False
    degradations: list[str] = Field(default_factory=list)
    drift: DriftEvent | None = None
    impact: ImpactReport | None = None
    patches: list[Patch] = Field(default_factory=list)
    pr: PullRequestResult | None = None
    writeback: list[WritebackAction] = Field(default_factory=list)
    events: list[RunEvent] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=_utc_now)
    finished_at: datetime | None = None
