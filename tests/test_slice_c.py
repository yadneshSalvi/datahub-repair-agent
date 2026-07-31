"""Slice C agent, integration, and API acceptance tests."""

from __future__ import annotations

import asyncio
import importlib
import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

import repair_agent.agent.runner as runner_module
import repair_agent.datahub_io.writeback as writeback_module
from repair_agent.agent.runner import run_repair
from repair_agent.agent.tools import (
    analyze_impact,
    detect_drift,
    explain_drop_strategy,
    generate_patches,
    open_pull_request,
    validate_patches,
    write_back_to_datahub,
)
from repair_agent.api.app import create_app
from repair_agent.config import Settings
from repair_agent.datahub_io.writeback import DataHubWriteback
from repair_agent.drift.detect import declare_drift
from repair_agent.models import (
    FglEdge,
    FileChange,
    PRRequest,
    PullRequestResult,
    RepairRun,
    RunEvent,
    WritebackAction,
)
from repair_agent.pipeline import run_pipeline
from repair_agent.pr.dry_run import DryRunPRProvider
from tests.support import OfflineDataHubIO, dataset_urn

DRIFT_ID = "rename-orders-order_placed_at"
api_module = importlib.import_module("repair_agent.api.app")


def test_agent_tool_schemas_are_strict_and_build_without_user_error() -> None:
    tools = [
        detect_drift,
        analyze_impact,
        generate_patches,
        validate_patches,
        open_pull_request,
        write_back_to_datahub,
        explain_drop_strategy,
    ]
    assert all(tool.strict_json_schema for tool in tools)
    assert [set(tool.params_json_schema["properties"]) for tool in tools] == [
        {"drift_id"},
        {"drift_id"},
        {"drift_id"},
        {"drift_id"},
        {"drift_id"},
        {"drift_id"},
        {"request"},
    ]


def test_degraded_path_produces_a_complete_run(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(_env_file=None, openai_api_key="")

    async def fake_pr(context):  # type: ignore[no-untyped-def]
        context.run.pr = PullRequestResult(
            mode="dry-run",
            url="file:///tmp/repair.md",
            branch=f"repair/{DRIFT_ID}",
            files=[patch.file_path for patch in context.run.patches],
        )
        return context.run.pr

    async def fake_writeback(context):  # type: ignore[no-untyped-def]
        context.run.writeback = [_action(name) for name in _writeback_names()]
        return context.run.writeback

    monkeypatch.setattr(runner_module, "open_pull_request_impl", fake_pr)
    monkeypatch.setattr(runner_module, "write_back_impl", fake_writeback)
    result = asyncio.run(
        run_repair(
            "degraded-test",
            DRIFT_ID,
            use_llm=True,
            settings=settings,
            datahub_io=OfflineDataHubIO(),  # type: ignore[arg-type]
        )
    )
    assert result.status == "succeeded"
    assert result.degraded is True
    assert result.drift is not None and result.impact is not None
    assert result.patches and all(patch.valid for patch in result.patches)
    assert result.pr is not None and len(result.writeback) == 6


def test_llm_and_no_llm_runs_have_byte_identical_patch_content(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(_env_file=None, openai_api_key="test-key")

    async def fake_model_path(context):  # type: ignore[no-untyped-def]
        await runner_module._deterministic_complete(context)

    async def fake_pr(context):  # type: ignore[no-untyped-def]
        context.run.pr = PullRequestResult(
            mode="dry-run", url="file:///tmp/repair.md", branch=f"repair/{DRIFT_ID}"
        )
        return context.run.pr

    async def fake_writeback(context):  # type: ignore[no-untyped-def]
        context.run.writeback = [_action(name) for name in _writeback_names()]
        return context.run.writeback

    monkeypatch.setattr(runner_module, "_run_with_model_fallback", fake_model_path)
    monkeypatch.setattr(runner_module, "open_pull_request_impl", fake_pr)
    monkeypatch.setattr(runner_module, "write_back_impl", fake_writeback)
    llm = asyncio.run(
        run_repair("llm-test", DRIFT_ID, use_llm=True, settings=settings, datahub_io=OfflineDataHubIO())  # type: ignore[arg-type]
    )
    no_llm = asyncio.run(
        run_repair("no-llm-test", DRIFT_ID, use_llm=False, settings=settings, datahub_io=OfflineDataHubIO())  # type: ignore[arg-type]
    )
    assert [(patch.file_path, patch.after) for patch in llm.patches] == [
        (patch.file_path, patch.after) for patch in no_llm.patches
    ]


def test_shared_pipeline_returns_a_complete_validated_run() -> None:
    result = run_pipeline(
        "pipeline-test",
        DRIFT_ID,
        datahub_io=OfflineDataHubIO(),  # type: ignore[arg-type]
        settings=Settings(_env_file=None),
    )
    assert result.status == "succeeded"
    assert result.finished_at is not None
    assert all(patch.valid for patch in result.patches)


def test_dry_run_provider_writes_complete_payload(tmp_path: Path) -> None:
    request = PRRequest(
        branch=f"repair/{DRIFT_ID}",
        base="main",
        title="Repair timestamp rename",
        body_markdown="# Complete review body\n",
        files=[FileChange(path="models/stg_orders.sql", content="select 1\n")],
        commit_message="Repair schema drift",
    )
    result = DryRunPRProvider(tmp_path).open_pr(request)
    payload = json.loads((tmp_path / f"{DRIFT_ID}.payload.json").read_text(encoding="utf-8"))
    assert result.ok and result.mode == "dry-run"
    assert (tmp_path / f"{DRIFT_ID}.md").read_text(encoding="utf-8") == request.body_markdown
    assert payload == {
        "branch": request.branch,
        "base": "main",
        "title": request.title,
        "commit_message": request.commit_message,
        "files": ["models/stg_orders.sql"],
    }


def test_writeback_methods_never_raise_when_datahub_is_unreachable(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    class FailingGraph:
        def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
            raise ConnectionError(f"DataHub unavailable during {name}")

    class FailingIO:
        graph = FailingGraph()

        def fine_grained_lineage(self, urn: str, *, skip_cache: bool = True):  # type: ignore[no-untyped-def]
            del urn, skip_cache
            raise ConnectionError("DataHub unavailable during lineage read")

    class FailingEmitter:
        def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise ConnectionError("DataHub unavailable during process emission")

    monkeypatch.setattr(writeback_module, "DataHubRestEmitter", FailingEmitter)
    settings = Settings(_env_file=None, repo_root=tmp_path)
    writer = DataHubWriteback(FailingIO(), settings)  # type: ignore[arg-type]
    drift = declare_drift(
        kind="RENAME",
        dataset_urn=dataset_urn("raw.orders"),
        old_column="order_placed_at",
        new_column="order_created_at",
    )
    now = datetime.now(UTC)
    actions = [
        writer.update_fine_grained_lineage(dataset_urn("stg_orders"), [FglEdge(
            upstream_urn=dataset_urn("raw.orders"),
            upstream_path="order_created_at",
            downstream_urn=dataset_urn("stg_orders"),
            downstream_path="order_created_at",
        )]),
        writer.document_column(dataset_urn("raw.orders"), "order_created_at", "Migrated."),
        writer.tag_assets(dataset_urn("raw.orders"), "order_placed_at", [dataset_urn("stg_orders")]),
        writer.raise_incident(drift, "file:///tmp/pr.md"),
        writer.attach_migration_doc(dataset_urn("raw.orders"), "file:///tmp/pr.md", "file:///tmp/doc.md"),
        writer.record_run(
            "failed-writeback-test",
            dataset_urn("raw.orders"),
            [dataset_urn("stg_orders")],
            succeeded=False,
            started_at=now,
            finished_at=now,
        ),
    ]
    assert all(isinstance(action, WritebackAction) for action in actions)
    assert all(not action.ok and action.error for action in actions)


def test_fastapi_run_and_sse_stream_complete(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    async def fake_run_repair(
        run_id: str,
        drift_id: str,
        *,
        use_llm: bool,
        pr_mode: str,
        settings: Settings,
        on_event,
        run: RepairRun,
    ) -> RepairRun:
        del drift_id, use_llm, pr_mode, settings
        event = RunEvent(seq=1, phase="detect", title="Offline detection complete")
        run.events.append(event)
        on_event(event)
        run.status = "succeeded"
        run.finished_at = datetime.now(UTC)
        done = RunEvent(seq=2, phase="done", title="Offline run complete")
        run.events.append(done)
        on_event(done)
        return run

    monkeypatch.setattr(api_module, "run_repair", fake_run_repair)
    settings = Settings(
        _env_file=None,
        repo_root=tmp_path,
        datahub_gms_url="http://127.0.0.1:1",
        openai_api_key="",
    )
    application = create_app(settings)
    with TestClient(application) as client:
        assert client.get("/api/health").status_code == 200
        assert len(client.get("/api/scenarios").json()) == 3
        started = client.post(
            "/api/runs",
            json={"drift_id": DRIFT_ID, "pr_mode": "dry-run", "use_llm": False},
        )
        run_id = started.json()["run_id"]
        with client.stream("GET", f"/api/runs/{run_id}/events") as response:
            stream = "".join(response.iter_text())
        assert "data:" in stream
        assert "event: done" in stream
        payload = client.get(f"/api/runs/{run_id}").json()
        assert payload["status"] == "succeeded"
        assert Path(tmp_path, ".repair-agent", "runs", f"{run_id}.json").is_file()
    with TestClient(create_app(settings)) as restarted:
        restored = restarted.get(f"/api/runs/{run_id}")
        assert restored.status_code == 200
        assert restored.json()["status"] == "succeeded"


def _writeback_names() -> list[str]:
    return [
        "update_fine_grained_lineage",
        "document_column",
        "tag_assets",
        "raise_incident",
        "attach_migration_doc",
        "record_run",
    ]


def _action(name: str) -> WritebackAction:
    return WritebackAction(
        kind=name,
        target_urn=dataset_urn("raw.orders"),
        detail="Offline success",
        datahub_url="http://localhost:9002/dataset/test",
    )
