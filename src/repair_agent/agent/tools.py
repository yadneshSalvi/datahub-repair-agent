"""Strict-schema OpenAI Agents SDK tools over the deterministic repair engine."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from agents import RunContextWrapper, function_tool
from pydantic import BaseModel, Field

from repair_agent.agent.prose import generate_column_doc, generate_migration_doc, generate_pr_narrative
from repair_agent.config import Settings
from repair_agent.datahub_io.client import DataHubIO
from repair_agent.datahub_io.links import datahub_entity_url
from repair_agent.datahub_io.writeback import DataHubWriteback
from repair_agent.models import (
    FglEdge,
    FileChange,
    ImpactBucket,
    ImpactedAsset,
    Patch,
    PRRequest,
    PullRequestResult,
    ReferenceCheck,
    RepairRun,
    RunEvent,
    WritebackAction,
)
from repair_agent.pipeline import codegen_stage, detect_stage, emit_run_event, impact_stage, validate_stage
from repair_agent.pr.dry_run import DryRunPRProvider
from repair_agent.pr.gh_cli import GhCliPRProvider
from repair_agent.pr.render import render_pr_body

LOGGER = logging.getLogger(__name__)


@dataclass
class RunContext:
    """Mutable run state shared by every function tool."""

    run: RepairRun
    drift_id: str
    datahub_io: DataHubIO
    settings: Settings
    on_event: Callable[[RunEvent], None] | None = None
    pr_mode: str = "dry-run"
    use_llm: bool = True
    model_name: str = "gpt-5.6-sol"

    def emit(
        self,
        *,
        phase: str,
        title: str,
        detail: str = "",
        level: str = "info",
        data: dict[str, object] | None = None,
    ) -> RunEvent:
        """Record one ordered event and forward it to SSE."""

        return emit_run_event(
            self.run,
            self.on_event,
            phase=phase,
            title=title,
            detail=detail,
            level=level,
            data=data,
        )

    def degrade(self, reason: str) -> None:
        """Mark a readable, de-duplicated degradation on the run."""

        self.run.degraded = True
        if reason not in self.run.degradations:
            self.run.degradations.append(reason)
        self.emit(phase="detect", level="warning", title="Graceful degradation", detail=reason)


class DriftToolResult(BaseModel):
    """Strict drift summary returned to the orchestrating model."""

    drift_id: str
    kind: str
    dataset_urn: str
    dataset_name: str
    old_column: str | None = None
    new_column: str | None = None
    rationale: str


class ImpactToolResult(BaseModel):
    """Strict three-bucket impact result without free-form mapping fields."""

    requires_patch: list[ImpactedAsset] = Field(default_factory=list)
    downstream_unaffected: list[ImpactedAsset] = Field(default_factory=list)
    skipped: list[ImpactedAsset] = Field(default_factory=list)


class PatchToolResult(BaseModel):
    """Generated immutable patch set."""

    patches: list[Patch] = Field(default_factory=list)


class ValidationToolResult(BaseModel):
    """Hard-gate summary and every per-reference verdict."""

    valid: bool
    resolved: int
    total: int
    references: list[ReferenceCheck] = Field(default_factory=list)


class WritebackToolResult(BaseModel):
    """The six best-effort DataHub write-back actions."""

    actions: list[WritebackAction] = Field(default_factory=list)


class DropStrategyInput(BaseModel):
    """Facts available for the DROP judgment call."""

    drift_id: str
    column: str
    affected_asset: str
    consumer_context: str


class DropStrategy(BaseModel):
    """Required non-destructive DROP treatment."""

    decision: str
    rationale: str
    required_steps: list[str] = Field(default_factory=list)


@function_tool(timeout=120)
async def detect_drift(ctx: RunContextWrapper[RunContext], drift_id: str) -> DriftToolResult:
    """Detect the requested active drift against the live DataHub catalog.

    Args:
        drift_id: Exact active drift identifier supplied in the repair mission.
    """

    _require_drift_id(ctx.context, drift_id)
    if ctx.context.run.drift is None:
        await asyncio.to_thread(
            detect_stage,
            ctx.context.run,
            drift_id,
            ctx.context.datahub_io,
            ctx.context.settings,
            ctx.context.on_event,
        )
    drift = ctx.context.run.drift
    if drift is None:  # pragma: no cover - guarded by detect_stage
        raise RuntimeError("Detection completed without a DriftEvent; inspect the baseline and live catalog.")
    return DriftToolResult(
        drift_id=drift.id,
        kind=drift.kind.value,
        dataset_urn=drift.dataset_urn,
        dataset_name=drift.dataset_name,
        old_column=drift.old_column,
        new_column=drift.new_column,
        rationale=drift.rationale,
    )


@function_tool(timeout=120)
async def analyze_impact(ctx: RunContextWrapper[RunContext], drift_id: str) -> ImpactToolResult:
    """Compute DataHub-lineage-first impact in all three required buckets.

    Args:
        drift_id: Exact active drift identifier supplied in the repair mission.
    """

    _require_drift_id(ctx.context, drift_id)
    await _ensure_impact(ctx.context)
    impact = ctx.context.run.impact
    if impact is None:  # pragma: no cover - guarded by impact_stage
        raise RuntimeError("Impact analysis completed without an ImpactReport.")
    return ImpactToolResult(
        requires_patch=[asset for asset in impact.assets if asset.bucket is ImpactBucket.REQUIRES_PATCH],
        downstream_unaffected=[
            asset for asset in impact.assets if asset.bucket is ImpactBucket.DOWNSTREAM_UNAFFECTED
        ],
        skipped=[asset for asset in impact.assets if asset.bucket is ImpactBucket.SKIPPED],
    )


@function_tool(timeout=120)
async def generate_patches(ctx: RunContextWrapper[RunContext], drift_id: str) -> PatchToolResult:
    """Generate code only through deterministic AST and structured metadata transforms.

    Args:
        drift_id: Exact active drift identifier supplied in the repair mission.
    """

    _require_drift_id(ctx.context, drift_id)
    await _ensure_impact(ctx.context)
    if not ctx.context.run.patches:
        await asyncio.to_thread(codegen_stage, ctx.context.run, ctx.context.settings, ctx.context.on_event)
    return PatchToolResult(patches=ctx.context.run.patches)


@function_tool(timeout=120)
async def validate_patches(ctx: RunContextWrapper[RunContext], drift_id: str) -> ValidationToolResult:
    """Hard-gate every generated SQL reference against catalog-backed schemas.

    Args:
        drift_id: Exact active drift identifier supplied in the repair mission.
    """

    _require_drift_id(ctx.context, drift_id)
    await _ensure_patches(ctx.context)
    if any(not patch.valid for patch in ctx.context.run.patches):
        await asyncio.to_thread(
            validate_stage,
            ctx.context.run,
            ctx.context.datahub_io,
            ctx.context.settings,
            ctx.context.on_event,
        )
    references = [reference for patch in ctx.context.run.patches for reference in patch.references]
    return ValidationToolResult(
        valid=all(patch.valid for patch in ctx.context.run.patches),
        resolved=sum(reference.status == "OK" for reference in references),
        total=len(references),
        references=references,
    )


@function_tool(timeout=180)
async def open_pull_request(ctx: RunContextWrapper[RunContext], drift_id: str) -> PullRequestResult:
    """Open the validated repair in the configured live or dry-run review provider.

    Args:
        drift_id: Exact active drift identifier supplied in the repair mission.
    """

    _require_drift_id(ctx.context, drift_id)
    return await open_pull_request_impl(ctx.context)


@function_tool(timeout=240)
async def write_back_to_datahub(ctx: RunContextWrapper[RunContext], drift_id: str) -> WritebackToolResult:
    """Write six best-effort governance and audit results back to DataHub.

    Args:
        drift_id: Exact active drift identifier supplied in the repair mission.
    """

    _require_drift_id(ctx.context, drift_id)
    return WritebackToolResult(actions=await write_back_impl(ctx.context))


@function_tool(timeout=30)
async def explain_drop_strategy(
    ctx: RunContextWrapper[RunContext],
    request: DropStrategyInput,
) -> DropStrategy:
    """Explain the mandatory deprecation path for a dropped upstream column.

    Args:
        request: Catalog- and code-backed DROP facts; never inferred column names.
    """

    _require_drift_id(ctx.context, request.drift_id)
    return DropStrategy(
        decision="DEPRECATE_WITH_REVIEW",
        rationale=(
            f"`{request.column}` is absent upstream and is consumed by {request.affected_asset}. "
            "A silent delete would hide a contract break, so the repair preserves a commented provenance record "
            f"and explicit data-team review. Evidence: {request.consumer_context}"
        ),
        required_steps=[
            "Comment out the affected SELECT projection with repair provenance.",
            "Add a TODO for the data team and remove the corresponding dbt metadata/tests.",
            "Raise a DataHub incident and require reviewer confirmation before deployment.",
        ],
    )


async def open_pull_request_impl(context: RunContext) -> PullRequestResult:
    """Implementation shared by the tool and deterministic completion path."""

    if context.run.pr is not None:
        return context.run.pr
    await _ensure_validated(context)
    drift = context.run.drift
    impact = context.run.impact
    if drift is None or impact is None:  # pragma: no cover - enforced above
        raise RuntimeError("PR creation requires drift and impact state.")
    mode = "dry-run" if context.pr_mode != "live" else "live"
    if not context.run.patches and impact.stats.get("requires_patch", 0) == 0:
        # Nothing to patch is a SUCCESS, not a blocked validation. Reusing the blocked state
        # here made a green run show a red provider error on the Pull Request tab.
        result = PullRequestResult(
            mode=mode,
            url="",
            branch=f"repair/{drift.id}",
            title="No changes required — no PR opened",
            files=[],
            ok=True,
            state="no_changes_required",
        )
        context.run.pr = result
        return result
    if not context.run.patches or not all(patch.valid for patch in context.run.patches):
        result = PullRequestResult(
            mode=mode,
            url="",
            branch=f"repair/{drift.id}",
            title="Validation blocked schema-drift repair",
            files=[patch.file_path for patch in context.run.patches],
            ok=False,
            error="Validation did not pass; fix the failing ReferenceCheck entries before opening a PR.",
            state="blocked",
        )
        context.run.pr = result
        return result

    context.emit(
        phase="pr",
        title="Preparing the review package",
        detail="Rendering lineage evidence, patch strategies, validation verdicts, and skip reasons.",
    )
    narrative = await generate_pr_narrative(
        context.run,
        context.settings,
        model=context.model_name,
        use_llm=context.use_llm and not context.run.degraded,
        on_degradation=context.degrade,
    )
    body = render_pr_body(
        impact,
        context.run.patches,
        run_id=context.run.id,
        datahub_instance=context.settings.datahub_gms_url,
        timestamp=datetime.now(UTC),
        narrative_summary=narrative.summary,
        risk_note=narrative.risk_note,
        reviewer_checklist=narrative.reviewer_checklist,
    )
    request = PRRequest(
        branch=f"repair/{drift.id}",
        base="main",
        title=narrative.title,
        body_markdown=body,
        files=[
            FileChange(path=patch.file_path, content=patch.after, previous_content=patch.before)
            for patch in context.run.patches
        ],
        commit_message=f"Repair schema drift {drift.id}",
    )
    dry_run = DryRunPRProvider(
        context.settings.repo_root / ".repair-agent" / "pr_bodies",
        repo_root=context.settings.repo_root,
    )
    provider = (
        GhCliPRProvider(
            context.settings.repo_root,
            fallback=dry_run,
            on_degradation=context.degrade,
        )
        if context.pr_mode == "live"
        else dry_run
    )
    context.run.pr = await asyncio.to_thread(provider.open_pr, request)
    context.emit(
        phase="pr",
        level="info" if context.run.pr.ok else "error",
        title="Review package ready" if context.run.pr.ok else "PR provider failed",
        detail=(
            f"{context.run.pr.mode} review: {context.run.pr.url}"
            if context.run.pr.ok
            else context.run.pr.error or "The PR provider returned an unknown error."
        ),
        data={"mode": context.run.pr.mode, "url": context.run.pr.url},
    )
    return context.run.pr


async def write_back_impl(context: RunContext) -> list[WritebackAction]:
    """Execute and aggregate exactly six write-back categories."""

    if context.run.writeback:
        return context.run.writeback
    if context.run.pr is None:
        await open_pull_request_impl(context)
    drift = context.run.drift
    impact = context.run.impact
    pr = context.run.pr
    if drift is None or impact is None or pr is None:
        raise RuntimeError("DataHub write-back requires drift, impact, and PR results.")

    context.emit(
        phase="writeback",
        title="Writing repair evidence back to DataHub",
        detail="Applying corrected lineage, documentation, tags, an OSS incident, institutional memory, and a run record.",
    )
    migration = await generate_migration_doc(
        context.run,
        context.settings,
        model=context.model_name,
        use_llm=context.use_llm and not context.run.degraded,
        on_degradation=context.degrade,
    )
    column_doc = await generate_column_doc(
        context.run,
        context.settings,
        model=context.model_name,
        use_llm=context.use_llm and not context.run.degraded,
        pr_url=pr.url,
        on_degradation=context.degrade,
    )
    migration_path = context.settings.repo_root / ".repair-agent" / "migration_docs" / f"{drift.id}.md"
    migration_path.parent.mkdir(parents=True, exist_ok=True)
    migration_path.write_text(migration.markdown, encoding="utf-8")

    writeback = DataHubWriteback(context.datahub_io, context.settings)
    patched_urns = sorted(
        {
            patch.asset_urn
            for patch in context.run.patches
            if patch.asset_urn.startswith("urn:li:dataset:")
        }
    )

    lineage_results: list[WritebackAction] = []
    corrected_by_urn: dict[str, list[FglEdge]] = {}
    for urn in patched_urns:
        try:
            current = context.datahub_io.fine_grained_lineage(urn, skip_cache=True)
            corrected = [_corrected_edge(edge, drift.old_column, drift.new_column, drift.kind.value) for edge in current]
            corrected = [edge for edge in corrected if edge is not None]
        except Exception as exc:
            LOGGER.warning("Could not prepare corrected lineage for %s: %s", urn, exc)
            corrected_by_urn[urn] = []
            lineage_results.append(
                WritebackAction(
                    kind="update_fine_grained_lineage",
                    target_urn=urn,
                    detail="Could not read current lineage, so no destructive reconciliation was attempted.",
                    datahub_url=datahub_entity_url(context.settings.datahub_frontend_url, urn, suffix="Lineage"),
                    ok=False,
                    error=str(exc),
                )
            )
            continue
        corrected_by_urn[urn] = corrected
        lineage_results.append(await asyncio.to_thread(writeback.update_fine_grained_lineage, urn, corrected))
    lineage_action = _aggregate_action(
        "update_fine_grained_lineage",
        drift.dataset_urn,
        lineage_results,
        datahub_entity_url(context.settings.datahub_frontend_url, drift.dataset_urn, suffix="Lineage"),
        f"Updated corrected field lineage for {len(patched_urns)} patched dataset(s).",
    )

    documentation_results = [
        await asyncio.to_thread(
            writeback.document_column,
            drift.dataset_urn,
            drift.new_column or drift.old_column or "schema",
            column_doc.text,
        )
    ]
    for urn in patched_urns:
        target_column = _documentation_column(
            corrected_by_urn.get(urn, []),
            drift.old_column,
            drift.new_column,
        )
        if target_column:
            documentation_results.append(
                await asyncio.to_thread(writeback.document_column, urn, target_column, column_doc.text)
            )
    document_action = _aggregate_action(
        "document_column",
        drift.dataset_urn,
        documentation_results,
        datahub_entity_url(context.settings.datahub_frontend_url, drift.dataset_urn),
        f"Documented the repaired path on {len(documentation_results)} dataset field(s).",
    )

    tag_action = await asyncio.to_thread(
        writeback.tag_assets,
        drift.dataset_urn,
        drift.new_column or drift.old_column or "schema",
        patched_urns,
    )
    incident_action = await asyncio.to_thread(writeback.raise_incident, drift, pr.url if pr.ok else None)
    memory_action = await asyncio.to_thread(
        writeback.attach_migration_doc,
        drift.dataset_urn,
        pr.url,
        migration_path.relative_to(context.settings.repo_root).as_posix(),
    )
    finished_at = datetime.now(UTC)
    record_action = await asyncio.to_thread(
        writeback.record_run,
        context.run.id,
        drift.dataset_urn,
        patched_urns,
        succeeded=all(patch.valid for patch in context.run.patches) and pr.ok,
        started_at=context.run.started_at,
        finished_at=finished_at,
    )
    context.run.writeback = [
        lineage_action,
        document_action,
        tag_action,
        incident_action,
        memory_action,
        record_action,
    ]
    for action in context.run.writeback:
        context.emit(
            phase="writeback",
            level="info" if action.ok else "warning",
            title=f"DataHub write-back: {action.kind}",
            detail=action.detail if action.ok else f"{action.detail} {action.error}",
            data={"ok": action.ok, "datahub_url": action.datahub_url},
        )
    return context.run.writeback


async def _ensure_impact(context: RunContext) -> None:
    if context.run.drift is None:
        await asyncio.to_thread(
            detect_stage,
            context.run,
            context.drift_id,
            context.datahub_io,
            context.settings,
            context.on_event,
        )
    if context.run.impact is None:
        await asyncio.to_thread(
            impact_stage,
            context.run,
            context.datahub_io,
            context.settings,
            context.on_event,
        )


async def _ensure_patches(context: RunContext) -> None:
    await _ensure_impact(context)
    if not context.run.patches:
        await asyncio.to_thread(codegen_stage, context.run, context.settings, context.on_event)


async def _ensure_validated(context: RunContext) -> None:
    await _ensure_patches(context)
    if any(not patch.valid for patch in context.run.patches):
        await asyncio.to_thread(
            validate_stage,
            context.run,
            context.datahub_io,
            context.settings,
            context.on_event,
        )


def _require_drift_id(context: RunContext, drift_id: str) -> None:
    if drift_id != context.drift_id:
        raise ValueError(f"Tool received drift_id {drift_id!r}; this run is scoped to {context.drift_id!r}.")


def _corrected_edge(
    edge: FglEdge,
    old_column: str | None,
    new_column: str | None,
    kind: str,
) -> FglEdge | None:
    if kind == "DROP" and old_column and (edge.upstream_path == old_column or edge.downstream_path == old_column):
        return None
    if kind != "RENAME" or not old_column or not new_column:
        return edge
    return edge.model_copy(
        update={
            "upstream_path": new_column if edge.upstream_path == old_column else edge.upstream_path,
            "downstream_path": new_column if edge.downstream_path == old_column else edge.downstream_path,
        }
    )


def _aggregate_action(
    kind: str,
    target_urn: str,
    actions: list[WritebackAction],
    datahub_url: str,
    detail: str,
) -> WritebackAction:
    failures = [action for action in actions if not action.ok]
    if not actions:
        return WritebackAction(kind=kind, target_urn=target_urn, detail=detail, datahub_url=datahub_url)
    return WritebackAction(
        kind=kind,
        target_urn=target_urn,
        detail=detail if not failures else f"{detail} {len(failures)} target(s) failed.",
        datahub_url=datahub_url,
        ok=not failures,
        error="; ".join(action.error or action.detail for action in failures) or None,
    )


def _documentation_column(
    edges: list[FglEdge],
    old_column: str | None,
    new_column: str | None,
) -> str | None:
    changed_name = new_column or old_column
    if changed_name is None:
        return None
    path_outputs = sorted(
        {
            edge.downstream_path
            for edge in edges
            if edge.downstream_path and edge.upstream_path == changed_name
        }
    )
    if changed_name in path_outputs:
        return changed_name
    return path_outputs[0] if path_outputs else None
