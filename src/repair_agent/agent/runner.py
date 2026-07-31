"""OpenAI Agents SDK runner with MCP evidence and deterministic degradation."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from agents import Agent, Runner, set_default_openai_key, set_tracing_disabled

from repair_agent.agent.tools import (
    RunContext,
    analyze_impact,
    detect_drift,
    explain_drop_strategy,
    generate_patches,
    open_pull_request,
    open_pull_request_impl,
    validate_patches,
    write_back_impl,
    write_back_to_datahub,
)
from repair_agent.config import Settings, get_settings
from repair_agent.datahub_io.client import DataHubIO
from repair_agent.datahub_io.mcp import build_datahub_mcp_server
from repair_agent.models import RepairRun, RunEvent
from repair_agent.pipeline import codegen_stage, detect_stage, impact_stage, run_pipeline, validate_stage

set_tracing_disabled(True)
LOGGER = logging.getLogger(__name__)
MODEL_FALLBACKS = ("gpt-5.6-sol", "gpt-5.4", "gpt-5.4-mini")
DATAHUB_MCP_TOOLS = {
    "search",
    "get_entities",
    "list_schema_fields",
    "get_lineage",
    "get_dataset_queries",
    "get_lineage_paths_between",
}
TOOLS = [
    detect_drift,
    analyze_impact,
    generate_patches,
    validate_patches,
    open_pull_request,
    write_back_to_datahub,
    explain_drop_strategy,
]

SYSTEM_PROMPT = """You are SchemaDriftRepairAgent. Your mission is to repair one declared
upstream schema drift using DataHub evidence and deterministic code tools.

Evidence flow (follow in order):
1. Use DataHub MCP `search` to confirm the source entity.
2. Use `list_schema_fields` to inspect exact live field names.
3. Use `get_lineage` for the changed column and its downstream blast radius.
4. Use `get_dataset_queries` for captured usage evidence where available.
5. Use `get_lineage_paths_between` to confirm important source-to-consumer paths.
6. Call the local repair tools in order: detect_drift, analyze_impact, generate_patches,
   validate_patches, open_pull_request, write_back_to_datahub.

Classify every code-bearing asset into exactly one bucket:
- REQUIRES_PATCH: its code literally references the drifted column.
- DOWNSTREAM_UNAFFECTED: it is downstream in column lineage but insulated by an upstream alias.
- SKIPPED: it is not on the changed column path.

Never invent or normalize a column name. Column names, schemas, lineage, captured queries,
and paths must come from MCP or deterministic tool output. The language model is forbidden
from writing or altering Patch.after code; it owns prose and judgment only. The validator is
a hard gate. Explain why every skipped model was skipped, using the exact lineage/code
evidence supplied by tools. For DROP, call explain_drop_strategy and preserve a deprecation
path; never silently delete a field. Complete the full flow through write-back before finishing.
"""


async def run_repair(
    run_id: str,
    drift_id: str,
    *,
    use_llm: bool,
    pr_mode: str | None = None,
    settings: Settings | None = None,
    datahub_io: DataHubIO | None = None,
    on_event: Callable[[RunEvent], None] | None = None,
    run: RepairRun | None = None,
) -> RepairRun:
    """Run the agent, degrading to the same fixed deterministic pipeline when needed."""

    active_settings = settings or get_settings()
    io = datahub_io or DataHubIO(active_settings)
    active_run = run or RepairRun(id=run_id)
    active_run.mode = "agent" if use_llm else "deterministic"
    context = RunContext(
        run=active_run,
        drift_id=drift_id,
        datahub_io=io,
        settings=active_settings,
        on_event=on_event,
        pr_mode=pr_mode or active_settings.pr_mode,
        use_llm=use_llm,
        model_name=active_settings.openai_model,
    )
    context.emit(
        phase="detect",
        title="Schema-drift repair started",
        detail=f"Run {run_id} is scoped to `{drift_id}` in {context.pr_mode} PR mode.",
    )
    try:
        if not use_llm:
            context.use_llm = False
            context.emit(
                phase="detect",
                title="Deterministic mode selected",
                detail="Using the first-class deterministic orchestration path with templated review prose.",
            )
            await _deterministic_complete(context)
        elif not active_settings.openai_api_key.strip():
            active_run.mode = "deterministic"
            context.degrade(
                "OPENAI_API_KEY is missing or empty; add it to .env to enable agent reasoning. "
                "The deterministic repair, dry-run PR, and DataHub write-back still ran."
            )
            context.use_llm = False
            await _deterministic_complete(context)
        else:
            set_default_openai_key(active_settings.openai_api_key, use_for_tracing=False)
            await _run_with_model_fallback(context)
            await _complete_missing_work(context)

        valid = bool(active_run.patches) and all(patch.valid for patch in active_run.patches)
        active_run.status = "succeeded" if valid and active_run.pr is not None and active_run.pr.ok else "failed"
        if active_run.status == "failed" and not active_run.error:
            # A run that reached the end without an exception can still be a failure — no
            # patches, an invalid patch, or a blocked PR. Name the reason explicitly so the
            # UI can never present it as a quiet success.
            if not active_run.patches:
                active_run.failed_stage = "codegen"
                active_run.error = (
                    "No patches were generated. A drift was active, so an empty repair set means "
                    "the impact analysis or codegen stage did not complete — not that the code is "
                    "already correct."
                )
            elif not valid:
                blocked = [patch.file_path for patch in active_run.patches if not patch.valid]
                active_run.failed_stage = "validate"
                active_run.error = (
                    f"{len(blocked)} patch(es) failed the column-reference validation gate and were "
                    f"blocked from the pull request: {', '.join(blocked)}."
                )
            else:
                active_run.failed_stage = "pr"
                pr_error = active_run.pr.error if active_run.pr else None
                active_run.error = pr_error or "The pull request could not be opened."
    except Exception as exc:
        active_run.status = "failed"
        active_run.failed_stage = active_run.failed_stage or _current_stage(active_run)
        active_run.error = str(exc)
        context.emit(
            phase="done",
            level="error",
            title="Repair run failed",
            detail=f"{exc}. Inspect the preceding event and retry after correcting the reported dependency.",
        )
        LOGGER.exception("Repair run %s failed", run_id)
    active_run.finished_at = datetime.now(UTC)
    active_run.completed_stages = _completed_stages(active_run)
    context.emit(
        phase="done",
        level="info" if active_run.status == "succeeded" else "error",
        title="Repair run complete" if active_run.status == "succeeded" else "Repair run FAILED",
        detail=(
            f"Status {active_run.status}; {len(active_run.patches)} patches, "
            f"{len(active_run.writeback)} DataHub write-back actions, mode={active_run.mode}, "
            f"degraded={active_run.degraded}."
            + (f" Failure ({active_run.failed_stage}): {active_run.error}" if active_run.error else "")
        ),
        data={
            "status": active_run.status,
            "mode": active_run.mode,
            "degraded": active_run.degraded,
            "error": active_run.error,
            "failed_stage": active_run.failed_stage,
        },
    )
    return active_run


def _current_stage(run: RepairRun) -> str:
    """The stage that was in flight when the run failed.

    Derived from artifacts rather than events: the last event is usually the terminal
    "done" frame, which names no real stage. The first stage that produced no output is
    the one that broke.
    """

    completed = set(_completed_stages(run))
    for stage in ("detect", "impact", "codegen", "validate", "pr", "writeback"):
        if stage not in completed:
            return stage
    return "done"


def _completed_stages(run: RepairRun) -> list[str]:
    """Stages that genuinely produced output, judged by artifacts rather than by events.

    The UI ticks these. Deriving them from real artifacts is what stops a failed run from
    showing green checkmarks next to work that never happened.
    """

    done: list[str] = []
    if run.drift is not None:
        done.append("detect")
    if run.impact is not None:
        done.append("impact")
    if run.patches:
        done.append("codegen")
    if run.patches and all(patch.valid for patch in run.patches):
        done.append("validate")
    if run.pr is not None and run.pr.ok:
        done.append("pr")
    if run.writeback and all(action.ok for action in run.writeback):
        done.append("writeback")
    return done


async def _run_with_model_fallback(context: RunContext) -> None:
    models = list(dict.fromkeys((context.settings.openai_model, *MODEL_FALLBACKS)))
    failures: list[str] = []
    for model in models:
        context.model_name = model
        context.emit(
            phase="impact",
            title=f"Starting OpenAI agent with {model}",
            detail="DataHub reads will be performed through the attached stdio MCP server.",
        )
        try:
            mcp_server = build_datahub_mcp_server(context.settings)
            async with mcp_server:
                agent = Agent[RunContext](
                    name="SchemaDriftRepairAgent",
                    model=model,
                    instructions=SYSTEM_PROMPT,
                    tools=TOOLS,
                    mcp_servers=[mcp_server],
                )
                result = Runner.run_streamed(
                    agent,
                    input=(
                        f"Repair drift `{context.drift_id}` completely. Use DataHub MCP evidence before the local "
                        "repair tools. Do not stop until PR and write-back tools have returned."
                    ),
                    context=context,
                    max_turns=24,
                )
                async for event in result.stream_events():
                    _map_stream_event(context, event)
            return
        except Exception as exc:
            failures.append(f"{model}: {exc}")
            if _is_model_not_found(exc):
                context.emit(
                    phase="impact",
                    level="warning",
                    title=f"Model {model} unavailable",
                    detail="Trying the next configured fallback model.",
                )
                continue
            reason = _degradation_reason(exc)
            context.run.mode = "deterministic"
            context.degrade(reason)
            context.use_llm = False
            await _deterministic_complete(context)
            return
    context.run.mode = "deterministic"
    context.degrade(
        "No model in the fallback chain was available (gpt-5.6-sol → gpt-5.4 → gpt-5.4-mini); "
        f"using deterministic orchestration. Last error: {failures[-1] if failures else 'unknown model error'}"
    )
    context.use_llm = False
    await _deterministic_complete(context)


async def _deterministic_complete(context: RunContext) -> None:
    if context.run.drift is None and context.run.impact is None and not context.run.patches:
        await asyncio.to_thread(
            run_pipeline,
            context.run.id,
            context.drift_id,
            datahub_io=context.datahub_io,
            settings=context.settings,
            on_event=context.on_event,
            run=context.run,
            raise_on_error=True,
            finalize=False,
        )
    else:
        await _complete_engine_work(context)
    await open_pull_request_impl(context)
    await write_back_impl(context)


async def _complete_missing_work(context: RunContext) -> None:
    missing = []
    if context.run.drift is None:
        missing.append("detect")
    if context.run.impact is None:
        missing.append("impact")
    if not context.run.patches:
        missing.append("codegen")
    if any(not patch.valid for patch in context.run.patches):
        missing.append("validate")
    if context.run.pr is None:
        missing.append("pr")
    if not context.run.writeback:
        missing.append("writeback")
    if missing:
        context.emit(
            phase="done",
            level="warning",
            title="Completing omitted agent steps deterministically",
            detail=f"The agent omitted {', '.join(missing)}; the shared contract is completing them now.",
        )
    await _complete_engine_work(context)
    await open_pull_request_impl(context)
    await write_back_impl(context)


async def _complete_engine_work(context: RunContext) -> None:
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
    if not context.run.patches:
        await asyncio.to_thread(codegen_stage, context.run, context.settings, context.on_event)
    if any(not patch.valid for patch in context.run.patches):
        await asyncio.to_thread(
            validate_stage,
            context.run,
            context.datahub_io,
            context.settings,
            context.on_event,
        )


def _map_stream_event(context: RunContext, event: Any) -> None:
    if getattr(event, "type", None) == "agent_updated_stream_event":
        agent = getattr(event, "new_agent", None)
        context.emit(
            phase="impact",
            level="debug",
            title="Agent active",
            detail=f"{getattr(agent, 'name', 'SchemaDriftRepairAgent')} is processing catalog evidence.",
        )
        return
    if getattr(event, "type", None) != "run_item_stream_event":
        return
    name = getattr(event, "name", "")
    item = getattr(event, "item", None)
    raw = getattr(item, "raw_item", None)
    if name == "tool_called":
        tool_name = getattr(raw, "name", None) or getattr(item, "title", None) or "unknown_tool"
        raw_type = getattr(raw, "type", None)
        is_mcp = raw_type == "mcp_call" or str(tool_name) in DATAHUB_MCP_TOOLS
        context.emit(
            phase="impact" if is_mcp else _tool_phase(str(tool_name)),
            title=(f"DataHub MCP tool call: {tool_name}" if is_mcp else f"Agent tool call: {tool_name}"),
            detail=(
                f"Reading catalog evidence through DataHub MCP `{tool_name}`."
                if is_mcp
                else f"Executing the shared `{tool_name}` repair stage."
            ),
            data={"tool": str(tool_name), "source": "datahub_mcp" if is_mcp else "repair_agent"},
        )
    elif name == "tool_output":
        tool_name = getattr(raw, "name", None) or "tool"
        context.emit(
            phase=_tool_phase(str(tool_name)),
            level="debug",
            title=f"Tool completed: {tool_name}",
            detail="Structured output returned to SchemaDriftRepairAgent.",
        )


def _tool_phase(name: str) -> str:
    if "detect" in name:
        return "detect"
    if "impact" in name or "lineage" in name or "schema" in name or "quer" in name or "search" in name:
        return "impact"
    if "generate" in name or "drop" in name:
        return "codegen"
    if "validate" in name:
        return "validate"
    if "pull" in name or "pr" in name:
        return "pr"
    if "write" in name or "incident" in name or "tag" in name:
        return "writeback"
    return "impact"


def _is_model_not_found(exc: Exception) -> bool:
    text = str(exc).casefold()
    code = str(getattr(exc, "code", "")).casefold()
    return "model_not_found" in text or "model not found" in text or code == "model_not_found"


def _degradation_reason(exc: Exception) -> str:
    text = str(exc)
    lowered = text.casefold()
    if "api key" in lowered or "authentication" in lowered or "401" in lowered:
        return f"OpenAI authentication failed; check OPENAI_API_KEY. Deterministic fallback used. Error: {text}"
    if "quota" in lowered or "rate limit" in lowered or "429" in lowered:
        return f"OpenAI quota/rate limit prevented agent reasoning; deterministic fallback used. Error: {text}"
    return f"OpenAI agent or DataHub MCP execution failed; deterministic fallback used. Error: {text}"
