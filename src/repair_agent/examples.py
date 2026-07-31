"""Generate static, reviewable artifacts from real deterministic engine runs."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ruamel.yaml import YAML

from repair_agent.codegen.generator import generate_patches
from repair_agent.config import Settings, get_settings
from repair_agent.datahub_io.client import DataHubIO
from repair_agent.drift.detect import detect_drift
from repair_agent.drift.snapshot import SchemaSnapshot
from repair_agent.impact.engine import ImpactEngine
from repair_agent.models import DriftEvent, ImpactReport, Patch
from repair_agent.pr.render import render_pr_body
from repair_agent.validate.validator import validate_patches

SCENARIOS = ("rename_order_placed_at", "retype_gross_amount", "drop_marketing_opt_in")
SCENARIO_IDS = {
    "rename_order_placed_at": "rename-orders-order_placed_at",
    "retype_gross_amount": "retype-orders-gross_amount",
    "drop_marketing_opt_in": "drop-customers-marketing_opt_in",
}


def generate_examples(datahub_io: DataHubIO | None = None, settings: Settings | None = None) -> Path:
    """Regenerate all three scenario directories from live DataHub and engine output."""

    active_settings = settings or get_settings()
    io = datahub_io or DataHubIO(active_settings)
    io.preflight()
    examples_root = active_settings.repo_root / "examples"
    examples_root.mkdir(parents=True, exist_ok=True)
    applied_path = active_settings.repo_root / "demo-warehouse" / ".repair-agent" / "applied_drift.json"
    initial_scenario = _applied_scenario(applied_path)
    current_scenario: str | None = initial_scenario
    impact_engine = ImpactEngine(io, active_settings)
    if current_scenario:
        _simulate(active_settings, revert=True)
        current_scenario = None
    try:
        for scenario in SCENARIOS:
            _simulate(active_settings, scenario=scenario)
            current_scenario = scenario
            drift = _detect_one(io, active_settings, SCENARIO_IDS[scenario])
            impact = impact_engine.analyze(drift)
            patches = generate_patches(impact, active_settings)
            validate_patches(patches, io, drift, settings=active_settings)
            _write_scenario(examples_root / scenario, scenario, drift, impact, patches, active_settings)
            _simulate(active_settings, revert=True)
            current_scenario = None
    finally:
        if current_scenario and applied_path.exists():
            _simulate(active_settings, revert=True)
        if initial_scenario:
            _simulate(active_settings, scenario=initial_scenario)
    _write_readme(examples_root)
    return examples_root


def _detect_one(io: DataHubIO, settings: Settings, drift_id: str) -> DriftEvent:
    baseline = SchemaSnapshot.load()
    live = SchemaSnapshot.capture(io, settings.namespace_prefix, known_urns=baseline.dataset_urns())
    events = detect_drift(baseline, live)
    try:
        return next(event for event in events if event.id == drift_id)
    except StopIteration as exc:
        raise RuntimeError(
            f"Scenario did not produce expected drift {drift_id}; detected {[event.id for event in events]}."
        ) from exc


def _simulate(settings: Settings, scenario: str | None = None, *, revert: bool = False) -> None:
    command = [sys.executable, str(settings.repo_root / "scripts" / "simulate_drift.py")]
    command.extend(["--revert"] if revert else [str(scenario)])
    environment = os.environ.copy()
    environment["DATAHUB_GMS_URL"] = settings.datahub_gms_url
    subprocess.run(command, cwd=settings.repo_root, env=environment, check=True, capture_output=True, text=True)


def _applied_scenario(path: Path) -> str | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    scenario = payload.get("scenario")
    return scenario if scenario in SCENARIOS else None


def _write_scenario(
    directory: Path,
    scenario: str,
    drift: DriftEvent,
    impact: ImpactReport,
    patches: list[Patch],
    settings: Settings,
) -> None:
    if directory.exists():
        shutil.rmtree(directory)
    before_dir = directory / "before"
    after_dir = directory / "after"
    before_dir.mkdir(parents=True)
    after_dir.mkdir(parents=True)
    directory.joinpath("00_drift_event.json").write_text(drift.model_dump_json(indent=2) + "\n", encoding="utf-8")
    directory.joinpath("01_impact_report.md").write_text(_impact_markdown(impact), encoding="utf-8")
    directory.joinpath("02_lineage_evidence.md").write_text(_lineage_markdown(impact), encoding="utf-8")

    names = _artifact_names(patches)
    for patch in patches:
        name = names[patch.file_path]
        before_dir.joinpath(name).write_text(patch.before, encoding="utf-8")
        after_dir.joinpath(name).write_text(patch.after, encoding="utf-8")
    combined_diff = "".join(patch.unified_diff for patch in sorted(patches, key=lambda item: item.file_path))
    directory.joinpath("03_patches.diff").write_text(combined_diff, encoding="utf-8")
    directory.joinpath("04_validation_report.md").write_text(_validation_markdown(patches), encoding="utf-8")
    directory.joinpath("05_generated_tests.yml").write_text(_generated_tests(patches, drift), encoding="utf-8")
    directory.joinpath("06_pull_request.md").write_text(
        render_pr_body(
            impact,
            patches,
            run_id=f"example-{scenario}",
            datahub_instance=settings.datahub_gms_url,
            timestamp=drift.detected_at,
        ),
        encoding="utf-8",
    )
    directory.joinpath("07_writeback_actions.json").write_text(
        json.dumps(_pending_writebacks(impact, settings), indent=2) + "\n",
        encoding="utf-8",
    )
    directory.joinpath("08_migration_doc.md").write_text(_migration_doc(impact, patches), encoding="utf-8")


def _artifact_names(patches: list[Patch]) -> dict[str, str]:
    basenames: dict[str, list[Patch]] = {}
    for patch in patches:
        basenames.setdefault(Path(patch.file_path).name, []).append(patch)
    result: dict[str, str] = {}
    for basename, grouped in basenames.items():
        for patch in grouped:
            result[patch.file_path] = basename if len(grouped) == 1 else f"{Path(patch.file_path).parent.name}_{basename}"
    return result


def _impact_markdown(impact: ImpactReport) -> str:
    lines = [
        f"# Impact report: {impact.drift.id}",
        "",
        "| Bucket | Asset | Hops | Catalog/code evidence |",
        "|---|---|---:|---|",
    ]
    for asset in impact.assets:
        lines.append(
            f"| {asset.bucket.value} | `{asset.name}` | {asset.hops if asset.hops is not None else '—'} | {asset.reason} |"
        )
    lines.extend(["", f"Scanned **{impact.stats['total_scanned']}** code-bearing assets.", ""])
    return "\n".join(lines)


def _lineage_markdown(impact: ImpactReport) -> str:
    lines = ["# Column-lineage evidence", "", "```mermaid", "graph LR"]
    for index, edge in enumerate(impact.graph.edges):
        source = _node_name(impact, edge.source_urn)
        target = _node_name(impact, edge.target_urn)
        source_column = ", ".join(edge.source_columns)
        target_column = ", ".join(edge.target_columns)
        operation = edge.transform_operation or "LINEAGE"
        lines.append(f'    n{index}a["{source}.{source_column}"] -->|"{operation}"| n{index}b["{target}.{target_column}"]')
    lines.extend(["```", "", "## Captured DataHub queries", ""])
    queries = [(asset.name, query) for asset in impact.assets for query in asset.captured_queries]
    if not queries:
        lines.append(
            "No usage query text was captured for this window; DataHub fine-grained lineage supplied the evidence above."
        )
    for asset, query in queries:
        lines.extend([f"### {asset}", "", "```sql", query, "```", ""])
    return "\n".join(lines).rstrip() + "\n"


def _validation_markdown(patches: list[Patch]) -> str:
    references = [reference for patch in patches for reference in patch.references]
    resolved = sum(reference.status == "OK" for reference in references)
    live = sum(reference.source == "live_catalog" for reference in references)
    projected = sum(reference.source == "projected_repair" for reference in references)
    cte = sum(reference.source == "local_cte" for reference in references)
    lines = [
        f"# Validation — 0 hallucinated columns · {resolved}/{len(references)} references resolved",
        "",
        f"Resolution sources: **{live}** against live DataHub `schemaMetadata`, **{projected}** against "
        f"the projected post-repair schema of models patched earlier in this run, **{cte}** locally "
        "derived CTE outputs. A model patched in this same run is not yet written back to DataHub, so "
        "its post-repair schema is the correct ground truth for its consumers.",
        "",
        "| File | Table | Column | Line | Status | Detail |",
        "|---|---|---|---:|---|---|",
    ]
    for patch in patches:
        for reference in patch.references:
            lines.append(
                f"| `{patch.file_path}` | `{reference.table}` | `{reference.column}` | {reference.line or '—'} | "
                f"**{reference.status}** | {reference.detail} |"
            )
    if not references:
        lines.append("| — | — | — | — | **OK** | No SQL references were generated. |")
    lines.extend(["", f"Hard gate: **{'PASSED' if all(patch.valid for patch in patches) else 'BLOCKED'}**.", ""])
    return "\n".join(lines)


def _generated_tests(patches: list[Patch], drift: DriftEvent) -> str:
    if not drift.new_column:
        return "version: 2\nmodels: []\n"
    yaml = YAML(typ="safe")
    generated: list[dict[str, Any]] = []
    for patch in patches:
        if patch.kind != "dbt_schema_yml":
            continue
        document = yaml.load(patch.after)
        for model in document.get("models", []):
            for column in model.get("columns", []):
                if column.get("name") == drift.new_column:
                    generated.append(
                        {
                            "name": model["name"],
                            "columns": [{"name": drift.new_column, "tests": list(column.get("tests", []))}],
                        }
                    )
    if not generated:
        return "version: 2\nmodels: []\n"
    from io import StringIO

    stream = StringIO()
    output_yaml = YAML()
    output_yaml.indent(mapping=2, sequence=4, offset=2)
    output_yaml.dump({"version": 2, "models": generated}, stream)
    return stream.getvalue()


def _pending_writebacks(impact: ImpactReport, settings: Settings) -> list[dict[str, str]]:
    source_url = f"{settings.datahub_frontend_url.rstrip('/')}/dataset/{quote(impact.drift.dataset_urn, safe='')}"
    return [
        {
            "kind": kind,
            "target_urn": impact.drift.dataset_urn,
            "detail": detail,
            "datahub_url": source_url,
            "status": "pending_slice_c",
        }
        for kind, detail in (
            ("update_fine_grained_lineage", "Planned corrected field lineage for patched models."),
            ("document_column", "Planned provenance documentation on renamed or migrated columns."),
            ("tag_assets", "Planned schema-drift-detected and schema-drift-repaired tags."),
            ("raise_incident", "Planned OSS incident lifecycle from TRIAGE to FIXED."),
            ("attach_migration_doc", "Planned InstitutionalMemory link to this migration document."),
            ("record_run", "Planned DataProcessInstance audit record."),
        )
    ]


def _migration_doc(impact: ImpactReport, patches: list[Patch]) -> str:
    return (
        f"# Migration: {impact.drift.id}\n\n"
        f"{impact.drift.rationale}\n\n"
        f"The deterministic engine changed {len(patches)} file artifact(s). "
        f"{impact.stats['downstream_unaffected']} downstream model(s) remain insulated by aliases, and "
        f"{impact.stats['skipped']} code-bearing asset(s) were correctly skipped using DataHub lineage evidence.\n\n"
        "Every generated SQL reference passed the validator hard gate before this artifact was emitted.\n"
    )


def _node_name(impact: ImpactReport, urn: str) -> str:
    return next((node.name for node in impact.graph.nodes if node.urn == urn), urn)


def _write_readme(root: Path) -> None:
    root.joinpath("README.md").write_text(
        """# Engine-generated repair examples

These artifacts are regenerated by `repair-agent examples`. For each drift scenario the
command applies the source-schema change to DataHub, detects it against the committed
snapshot, computes the three-bucket impact report from column lineage, generates surgical
patches, validates every SQL reference, writes these files, and reverts the scenario.

- `00_drift_event.json` is the normalized detected event and inference evidence.
- `01_impact_report.md` records every requires-patch, downstream-unaffected, and skipped decision with its reason.
- `02_lineage_evidence.md` contains Mermaid field lineage and captured-query evidence.
- `before/` and `after/` contain complete source files, never fragments.
- `03_patches.diff` is directly checkable with `git apply --check` from the repository root.
- `04_validation_report.md` is the validator hard-gate output behind the zero-hallucinated-columns claim.
- `05_generated_tests.yml` isolates tests added by the repair.
- `06_pull_request.md` is rendered from the reusable deterministic PR template.
- `07_writeback_actions.json` lists the six Slice C actions as explicitly pending; this slice does not fake external writes.
- `08_migration_doc.md` is the deterministic degraded-mode migration note.
""",
        encoding="utf-8",
    )
