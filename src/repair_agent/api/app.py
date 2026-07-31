"""FastAPI backend and live SSE transport for repair runs."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from uuid import uuid4

from datahub.metadata.schema_classes import SubTypesClass
from datahub.metadata.urns import DatasetUrn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from repair_agent.agent.runner import run_repair
from repair_agent.config import Settings, get_settings
from repair_agent.datahub_io.client import DataHubIO
from repair_agent.drift.detect import detect_drift
from repair_agent.drift.snapshot import SchemaSnapshot
from repair_agent.models import RepairRun, RunEvent

LOGGER = logging.getLogger(__name__)
SCENARIOS = {
    "rename_order_placed_at": {
        "drift_id": "rename-orders-order_placed_at",
        "kind": "RENAME",
        "title": "Rename orders.order_placed_at",
        "description": "Rename the source timestamp to order_created_at and repair exact downstream references.",
    },
    "retype_gross_amount": {
        "drift_id": "retype-orders-gross_amount",
        "kind": "RETYPE",
        "title": "Retype orders.gross_amount",
        "description": "Change the source amount to VARCHAR and preserve downstream numeric semantics with casts.",
    },
    "drop_marketing_opt_in": {
        "drift_id": "drop-customers-marketing_opt_in",
        "kind": "DROP",
        "title": "Drop customers.marketing_opt_in",
        "description": "Remove the source field and produce an explicit deprecation path rather than a silent delete.",
    },
}


class StartRunRequest(BaseModel):
    """Request body for one asynchronous repair run."""

    drift_id: str
    pr_mode: Literal["dry-run", "live"] = "dry-run"
    use_llm: bool = True


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an isolated API application, useful for production and TestClient."""

    active_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        _load_persisted_runs(application, active_settings)
        yield

    application = FastAPI(title="Schema-Drift Auto-Repair Agent", version="0.1.0", lifespan=lifespan)
    application.state.runs = {}
    application.state.queues = {}
    application.state.tasks = {}
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3002", "http://127.0.0.1:3002"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.get("/api/health")
    async def health() -> dict[str, object]:
        degradations: list[str] = []
        reachable = True
        try:
            await asyncio.to_thread(DataHubIO(active_settings).preflight)
        except Exception as exc:
            reachable = False
            degradations.append(str(exc))
        if not active_settings.openai_api_key.strip():
            degradations.append("OPENAI_API_KEY is absent; runs will use deterministic fallback mode.")
        return {
            "ok": reachable,
            "datahub_reachable": reachable,
            "gms_url": active_settings.datahub_gms_url,
            "llm_available": bool(active_settings.openai_api_key.strip()),
            "degradations": degradations,
        }

    @application.get("/api/catalog")
    async def catalog() -> list[dict[str, object]]:
        io = DataHubIO(active_settings)

        def read() -> list[dict[str, object]]:
            datasets = []
            for urn in io.list_namespace_datasets(active_settings.namespace_prefix, skip_cache=True):
                schema = io.get_schema(urn, skip_cache=True)
                subtype = io.graph.get_aspect(urn, SubTypesClass)
                try:
                    name = DatasetUrn.from_string(urn).name
                except ValueError:
                    name = urn
                datasets.append(
                    {
                        "urn": urn,
                        "name": name,
                        "subtypes": list(subtype.typeNames) if subtype else [],
                        "schema": schema.model_dump(mode="json"),
                    }
                )
            return datasets

        try:
            return await asyncio.to_thread(read)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Could not read the ShopFlow catalog: {exc}") from exc

    @application.get("/api/catalog/{urn:path}/schema")
    async def catalog_schema(urn: str) -> dict[str, object]:
        try:
            schema = await asyncio.to_thread(DataHubIO(active_settings).get_schema, urn, skip_cache=True)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Could not read schema for {urn}: {exc}") from exc
        if not schema.columns:
            raise HTTPException(status_code=404, detail=f"No live schemaMetadata exists for {urn}.")
        return schema.model_dump(mode="json")

    @application.get("/api/scenarios")
    async def scenarios() -> list[dict[str, str]]:
        return [{"name": name, **details} for name, details in SCENARIOS.items()]

    @application.post("/api/scenarios/{name}/apply")
    async def apply_scenario(name: str, revert: bool = Query(default=False)) -> dict[str, object]:
        if name not in SCENARIOS:
            raise HTTPException(status_code=404, detail=f"Unknown scenario {name!r}; choose one of {sorted(SCENARIOS)}.")
        arguments = ["--revert"] if revert else [name]
        completed = await _run_script(active_settings, "simulate_drift.py", arguments)
        if completed.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"Drift simulation failed: {completed.stderr.strip() or completed.stdout.strip()}",
            )
        return {"ok": True, "scenario": name, "reverted": revert, "detail": completed.stdout.strip()}

    @application.get("/api/drift")
    async def drift_events() -> list[dict[str, object]]:
        io = DataHubIO(active_settings)

        def read() -> list[dict[str, object]]:
            io.preflight()
            baseline = SchemaSnapshot.load()
            live = SchemaSnapshot.capture(io, active_settings.namespace_prefix)
            return [event.model_dump(mode="json") for event in detect_drift(baseline, live)]

        try:
            return await asyncio.to_thread(read)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Could not detect live drift: {exc}") from exc

    @application.post("/api/runs", status_code=202)
    async def start_run(request_body: StartRunRequest) -> dict[str, str]:
        run_id = f"run-{uuid4().hex}"
        repair_run = RepairRun(id=run_id)
        queue: asyncio.Queue[RunEvent] = asyncio.Queue()
        application.state.runs[run_id] = repair_run
        application.state.queues[run_id] = queue
        loop = asyncio.get_running_loop()

        def emit(event: RunEvent) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, event)

        task = asyncio.create_task(
            _execute_run(
                application,
                active_settings,
                repair_run,
                request_body,
                emit,
            ),
            name=f"repair-agent-{run_id}",
        )
        application.state.tasks[run_id] = task
        return {"run_id": run_id}

    @application.get("/api/runs")
    async def list_runs() -> list[dict[str, object]]:
        runs = sorted(application.state.runs.values(), key=lambda item: item.started_at, reverse=True)
        return [run.model_dump(mode="json") for run in runs]

    @application.get("/api/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, object]:
        repair_run = _require_run(application, run_id)
        return repair_run.model_dump(mode="json")

    @application.get("/api/runs/{run_id}/graph")
    async def get_graph(run_id: str) -> dict[str, object]:
        repair_run = _require_run(application, run_id)
        if repair_run.impact is None:
            raise HTTPException(status_code=409, detail="Impact analysis has not completed for this run yet.")
        return repair_run.impact.graph.model_dump(mode="json")

    @application.get("/api/runs/{run_id}/events")
    async def stream_events(run_id: str, request: Request) -> StreamingResponse:
        repair_run = _require_run(application, run_id)
        queue = application.state.queues.setdefault(run_id, asyncio.Queue())

        async def frames() -> AsyncIterator[str]:
            last_seq = 0
            try:
                for event in list(repair_run.events):
                    last_seq = max(last_seq, event.seq)
                    yield f"data: {event.model_dump_json()}\n\n"
                while repair_run.status == "running":
                    if await request.is_disconnected():
                        return
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    if event.seq <= last_seq:
                        continue
                    last_seq = event.seq
                    yield f"data: {event.model_dump_json()}\n\n"
                for event in repair_run.events:
                    if event.seq > last_seq:
                        last_seq = event.seq
                        yield f"data: {event.model_dump_json()}\n\n"
                yield f"event: done\ndata: {json.dumps({'run_id': run_id, 'status': repair_run.status})}\n\n"
            except asyncio.CancelledError:
                LOGGER.info("SSE client disconnected from run %s", run_id)
                return

        return StreamingResponse(
            frames(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @application.post("/api/reset")
    async def reset_demo() -> dict[str, object]:
        applied = active_settings.repo_root / "demo-warehouse" / ".repair-agent" / "applied_drift.json"
        outputs: list[str] = []
        if applied.exists():
            reverted = await _run_script(active_settings, "simulate_drift.py", ["--revert"])
            if reverted.returncode != 0:
                raise HTTPException(status_code=500, detail=f"Could not revert active drift: {reverted.stderr.strip()}")
            outputs.append(reverted.stdout.strip())
        seeded = await _run_script(active_settings, "seed_datahub.py", ["--verify"])
        if seeded.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Could not re-seed the demo catalog: {seeded.stderr.strip()}")
        outputs.append(seeded.stdout.strip())
        return {"ok": True, "detail": "\n".join(outputs)}

    return application


async def _execute_run(
    application: FastAPI,
    settings: Settings,
    repair_run: RepairRun,
    request: StartRunRequest,
    emit: Callable[[RunEvent], None],
) -> None:
    try:
        await run_repair(
            repair_run.id,
            request.drift_id,
            use_llm=request.use_llm,
            pr_mode=request.pr_mode,
            settings=settings,
            on_event=emit,
            run=repair_run,
        )
    finally:
        _persist_run(repair_run, settings)
        application.state.tasks.pop(repair_run.id, None)


async def _run_script(settings: Settings, script: str, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["DATAHUB_GMS_URL"] = settings.datahub_gms_url
    environment["DATAHUB_FRONTEND_URL"] = settings.datahub_frontend_url
    if settings.datahub_gms_token:
        environment["DATAHUB_GMS_TOKEN"] = settings.datahub_gms_token
    command = [sys.executable, str(settings.repo_root / "scripts" / script), *arguments]
    return await asyncio.to_thread(
        subprocess.run,
        command,
        cwd=settings.repo_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _require_run(application: FastAPI, run_id: str) -> RepairRun:
    repair_run = application.state.runs.get(run_id)
    if repair_run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id!r} was not found.")
    return repair_run


def _run_dir(settings: Settings) -> Path:
    return settings.repo_root / ".repair-agent" / "runs"


def _persist_run(repair_run: RepairRun, settings: Settings) -> None:
    if repair_run.finished_at is None:
        return
    directory = _run_dir(settings)
    directory.mkdir(parents=True, exist_ok=True)
    directory.joinpath(f"{repair_run.id}.json").write_text(
        repair_run.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


def _load_persisted_runs(application: FastAPI, settings: Settings) -> None:
    directory = _run_dir(settings)
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.json")):
        try:
            repair_run = RepairRun.model_validate_json(path.read_text(encoding="utf-8"))
            application.state.runs.setdefault(repair_run.id, repair_run)
            application.state.queues.setdefault(repair_run.id, asyncio.Queue())
        except Exception as exc:
            LOGGER.warning("Ignoring unreadable persisted run %s: %s", path, exc)


app = create_app()
