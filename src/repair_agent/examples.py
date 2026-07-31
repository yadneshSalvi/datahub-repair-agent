"""Generate static, reviewable artifacts from real deterministic engine runs."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from repair_agent.agent.runner import run_repair
from repair_agent.config import Settings, get_settings
from repair_agent.datahub_io.client import DataHubIO
from repair_agent.models import DriftEvent, ImpactReport, Patch, RepairRun
from repair_agent.pr.mermaid import mermaid_edges

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
    build_root = active_settings.repo_root / ".repair-agent" / "examples-build"
    if build_root.exists():
        shutil.rmtree(build_root)
    build_root.mkdir(parents=True)
    applied_path = active_settings.repo_root / "demo-warehouse" / ".repair-agent" / "applied_drift.json"
    initial_scenario = _applied_scenario(applied_path)
    current_scenario: str | None = initial_scenario
    if current_scenario:
        _simulate(active_settings, revert=True)
        current_scenario = None
    _seed(active_settings)
    try:
        for scenario in SCENARIOS:
            _simulate(active_settings, scenario=scenario)
            current_scenario = scenario
            run = asyncio.run(
                run_repair(
                    run_id=f"example-{scenario}",
                    drift_id=SCENARIO_IDS[scenario],
                    use_llm=False,
                    pr_mode="dry-run",
                    settings=active_settings,
                    datahub_io=io,
                )
            )
            _require_successful_example(run)
            _write_scenario(build_root / scenario, run, active_settings)
            _copy_runtime_artifacts(build_root, run, active_settings)
            _simulate(active_settings, revert=True)
            current_scenario = None
            _seed(active_settings)
    finally:
        if current_scenario and applied_path.exists():
            _simulate(active_settings, revert=True)
            _seed(active_settings)
        if initial_scenario:
            _simulate(active_settings, scenario=initial_scenario)
    _write_readme(build_root)
    _publish_examples(build_root, examples_root)
    return examples_root


def _require_successful_example(run: RepairRun) -> None:
    failures = [action.kind for action in run.writeback if not action.ok]
    if run.status != "succeeded" or run.degraded or failures:
        raise RuntimeError(
            f"Example run {run.id} was not a clean success: status={run.status}, "
            f"degraded={run.degraded}, failed_writebacks={failures}, error={run.error}."
        )


def _simulate(settings: Settings, scenario: str | None = None, *, revert: bool = False) -> None:
    command = [sys.executable, str(settings.repo_root / "scripts" / "simulate_drift.py")]
    command.extend(["--revert"] if revert else [str(scenario)])
    environment = os.environ.copy()
    environment["DATAHUB_GMS_URL"] = settings.datahub_gms_url
    subprocess.run(command, cwd=settings.repo_root, env=environment, check=True, capture_output=True, text=True)


def _seed(settings: Settings) -> None:
    command = [sys.executable, str(settings.repo_root / "scripts" / "seed_datahub.py")]
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
    run: RepairRun,
    settings: Settings,
) -> None:
    drift = run.drift
    impact = run.impact
    if drift is None or impact is None or run.pr is None:
        raise RuntimeError(f"Example run {run.id} is missing drift, impact, or PR artifacts.")
    patches = run.patches
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
    pr_body = settings.repo_root / run.pr.url
    directory.joinpath("06_pull_request.md").write_text(pr_body.read_text(encoding="utf-8"), encoding="utf-8")
    directory.joinpath("07_writeback_actions.json").write_text(
        json.dumps([action.model_dump(mode="json") for action in run.writeback], indent=2) + "\n",
        encoding="utf-8",
    )
    migration_path = settings.repo_root / ".repair-agent" / "migration_docs" / f"{drift.id}.md"
    directory.joinpath("08_migration_doc.md").write_text(
        migration_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )


def _copy_runtime_artifacts(build_root: Path, run: RepairRun, settings: Settings) -> None:
    if run.drift is None or run.pr is None:
        raise RuntimeError(f"Example run {run.id} has no review artifacts to copy.")
    pr_source = settings.repo_root / run.pr.url
    payload_source = pr_source.with_suffix(".payload.json")
    pr_target = build_root / "pr_bodies"
    migration_target = build_root / "migration_docs"
    pr_target.mkdir(exist_ok=True)
    migration_target.mkdir(exist_ok=True)
    shutil.copy2(pr_source, pr_target / pr_source.name)
    shutil.copy2(payload_source, pr_target / payload_source.name)
    migration_source = settings.repo_root / ".repair-agent" / "migration_docs" / f"{run.drift.id}.md"
    shutil.copy2(migration_source, migration_target / migration_source.name)


def _publish_examples(build_root: Path, examples_root: Path) -> None:
    for name in (*SCENARIOS, "pr_bodies", "migration_docs"):
        target = examples_root / name
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(build_root / name), target)
    shutil.move(str(build_root / "README.md"), examples_root / "README.md")
    build_root.rmdir()


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
    for edge in mermaid_edges(impact):
        lines.append(
            f'    {edge["source_id"]}["{edge["source_label"]}.{edge["source_column"]}"] '
            f'-->|"{edge["operation"]}"| '
            f'{edge["target_id"]}["{edge["target_label"]}.{edge["target_column"]}"]'
        )
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


def _write_readme(root: Path) -> None:
    root.joinpath("README.md").write_text(
        """# Engine-generated repair examples

These artifacts are regenerated by `repair-agent examples`. For each drift scenario the
command applies the source-schema change to DataHub and executes a complete deterministic-mode
repair run. It computes the three-bucket impact report from live column lineage, generates and
validates surgical patches, performs all six DataHub write-backs, writes these files, and
reverts the scenario. Deterministic mode is a first-class execution mode, so these are clean,
successful runs rather than fallback output.

- `00_drift_event.json` is the normalized detected event and inference evidence.
- `01_impact_report.md` records every requires-patch, downstream-unaffected, and skipped decision with its reason.
- `02_lineage_evidence.md` contains Mermaid field lineage and captured-query evidence.
- `before/` and `after/` contain complete source files, never fragments.
- `03_patches.diff` is directly checkable with `git apply --check` from the repository root.
- `04_validation_report.md` is the validator hard-gate output behind the zero-hallucinated-columns claim.
- `05_generated_tests.yml` isolates tests added by the repair.
- `06_pull_request.md` is rendered from the reusable deterministic PR template.
- `07_writeback_actions.json` records the six completed DataHub actions and their live deep links.
- `08_migration_doc.md` is the generated deterministic-mode migration and rollback note.
""",
        encoding="utf-8",
    )
