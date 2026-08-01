"""Shared deterministic repair pipeline used by the CLI, agent, and API."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from functools import wraps
from typing import TypeVar, cast

from repair_agent.codegen.generator import generate_patches
from repair_agent.config import Settings, get_settings
from repair_agent.datahub_io.client import DataHubIO
from repair_agent.drift.detect import detect_drift
from repair_agent.drift.snapshot import SchemaSnapshot
from repair_agent.impact.engine import analyze
from repair_agent.models import RepairRun, RunEvent
from repair_agent.validate.validator import validate_patches

LOGGER = logging.getLogger(__name__)
EventCallback = Callable[[RunEvent], None]
StageFn = TypeVar("StageFn", bound=Callable[..., None])


def stage(name: str) -> Callable[[StageFn], StageFn]:
    """Stamp ``run.failed_stage`` with the stage an exception actually escaped from.

    Attribution used to be inferred after the fact from run artifacts, which gave two
    different answers ("impact" vs "done") for the same impact-stage failure depending on
    what had been populated. The UI greys stages off this field, so a wrong value blames the
    wrong step. Recording it at the raise site makes it deterministic.
    """

    def decorate(function: StageFn) -> StageFn:
        @wraps(function)
        def wrapper(run: RepairRun, *args: object, **kwargs: object) -> None:
            try:
                return function(run, *args, **kwargs)
            except Exception:
                run.failed_stage = name
                raise

        return cast(StageFn, wrapper)

    return decorate


def emit_run_event(
    run: RepairRun,
    on_event: EventCallback | None,
    *,
    phase: str,
    title: str,
    detail: str = "",
    level: str = "info",
    data: dict[str, object] | None = None,
) -> RunEvent:
    """Append one ordered event and forward it to an optional live consumer."""

    event = RunEvent(
        seq=len(run.events) + 1,
        phase=phase,  # type: ignore[arg-type]
        level=level,  # type: ignore[arg-type]
        title=title,
        detail=detail,
        data=data or {},
    )
    run.events.append(event)
    if on_event is not None:
        on_event(event)
    return event


@stage("detect")
def detect_stage(
    run: RepairRun,
    drift_id: str,
    datahub_io: DataHubIO,
    settings: Settings,
    on_event: EventCallback | None = None,
) -> None:
    """Detect and select the requested active drift event."""

    emit_run_event(
        run,
        on_event,
        phase="detect",
        title="Checking the live DataHub catalog",
        detail="Verifying GMS, then comparing live schemas with the committed baseline snapshot.",
    )
    datahub_io.preflight()
    baseline = SchemaSnapshot.load()
    live = SchemaSnapshot.capture(datahub_io, settings.namespace_prefix, known_urns=baseline.dataset_urns())
    events = detect_drift(baseline, live)
    try:
        run.drift = next(event for event in events if event.id == drift_id)
    except StopIteration as exc:
        available = ", ".join(event.id for event in events) or "none"
        raise ValueError(
            f"Drift `{drift_id}` is not active. Active drift IDs: {available}. "
            "Apply a drift scenario from the Control Room first."
        ) from exc
    emit_run_event(
        run,
        on_event,
        phase="detect",
        title=f"Detected {run.drift.kind.value.lower()} drift",
        detail=run.drift.rationale,
        data={"drift_id": run.drift.id, "confidence": run.drift.confidence},
    )


@stage("impact")
def impact_stage(
    run: RepairRun,
    datahub_io: DataHubIO,
    settings: Settings,
    on_event: EventCallback | None = None,
) -> None:
    """Compute the exact three-bucket impact report."""

    if run.drift is None:
        raise RuntimeError("Impact analysis requires a detected drift. Run detect_stage first.")
    emit_run_event(
        run,
        on_event,
        phase="impact",
        title="Tracing the changed column",
        detail="Following DataHub column lineage and checking exact AST references in mapped code.",
    )
    run.impact = analyze(run.drift, datahub_io, settings)
    stats = run.impact.stats
    emit_run_event(
        run,
        on_event,
        phase="impact",
        title="Blast radius classified",
        detail=(
            f"{stats['requires_patch']} require patch, {stats['downstream_unaffected']} are downstream but "
            f"insulated, and {stats['skipped']} were correctly skipped with evidence."
        ),
        data={key: value for key, value in stats.items()},
    )


@stage("codegen")
def codegen_stage(
    run: RepairRun,
    settings: Settings,
    on_event: EventCallback | None = None,
) -> None:
    """Generate deterministic sqlglot/dbt/Airflow patches."""

    if run.impact is None:
        raise RuntimeError("Patch generation requires an impact report. Run impact_stage first.")
    emit_run_event(
        run,
        on_event,
        phase="codegen",
        title="Generating deterministic patches",
        detail="Only sqlglot AST transforms and round-trip-safe metadata editors may change code.",
    )
    run.patches = generate_patches(run.impact, settings)
    emit_run_event(
        run,
        on_event,
        phase="codegen",
        title=f"Generated {len(run.patches)} surgical file patches",
        detail="The language model did not author or modify any Patch.after content.",
        data={"files": [patch.file_path for patch in run.patches]},
    )


@stage("validate")
def validate_stage(
    run: RepairRun,
    datahub_io: DataHubIO,
    settings: Settings,
    on_event: EventCallback | None = None,
) -> None:
    """Resolve every generated reference and enforce the hard gate."""

    if run.drift is None:
        raise RuntimeError("Validation requires a detected drift. Run detect_stage first.")
    emit_run_event(
        run,
        on_event,
        phase="validate",
        title="Validating every generated reference",
        detail="Each SQL column must resolve against live DataHub schemaMetadata or a projected repaired output.",
    )
    validate_patches(run.patches, datahub_io, run.drift, settings=settings)
    references = [reference for patch in run.patches for reference in patch.references]
    resolved = sum(reference.status == "OK" for reference in references)
    valid = all(patch.valid for patch in run.patches)
    emit_run_event(
        run,
        on_event,
        phase="validate",
        level="info" if valid else "error",
        title="Validation passed — zero hallucinated columns" if valid else "Validation blocked the repair",
        detail=f"{resolved}/{len(references)} references resolved; the PR gate is {'open' if valid else 'closed'}.",
        data={"resolved": resolved, "total": len(references), "valid": valid},
    )
    if not valid:
        raise ValueError(
            "Generated patches failed live-catalog validation. Inspect the failing ReferenceCheck entries; "
            "no PR was opened."
        )


def run_pipeline(
    run_id: str,
    drift_id: str,
    *,
    datahub_io: DataHubIO | None = None,
    settings: Settings | None = None,
    on_event: EventCallback | None = None,
    run: RepairRun | None = None,
    raise_on_error: bool = False,
    finalize: bool = True,
) -> RepairRun:
    """Run detect → impact → generate → validate and return the populated aggregate."""

    active_settings = settings or get_settings()
    io = datahub_io or DataHubIO(active_settings)
    active_run = run or RepairRun(id=run_id)
    try:
        detect_stage(active_run, drift_id, io, active_settings, on_event)
        impact_stage(active_run, io, active_settings, on_event)
        codegen_stage(active_run, active_settings, on_event)
        validate_stage(active_run, io, active_settings, on_event)
        if finalize:
            active_run.status = "succeeded"
            active_run.finished_at = datetime.now(UTC)
    except Exception as exc:
        active_run.status = "failed"
        active_run.finished_at = datetime.now(UTC)
        emit_run_event(
            active_run,
            on_event,
            phase="done",
            level="error",
            title="Repair pipeline failed",
            detail=str(exc),
        )
        LOGGER.exception("Repair pipeline %s failed", run_id)
        if raise_on_error:
            raise
    return active_run
