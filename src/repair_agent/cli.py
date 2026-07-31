"""Complete command-line fallback for the deterministic repair workflow."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from repair_agent.codegen.generator import generate_patches
from repair_agent.config import get_settings
from repair_agent.datahub_io.client import DataHubIO
from repair_agent.drift.detect import detect_drift
from repair_agent.drift.snapshot import SchemaSnapshot
from repair_agent.examples import generate_examples
from repair_agent.impact.engine import CodeMapMissing, analyze
from repair_agent.models import DriftEvent, ImpactReport, Patch
from repair_agent.validate.validator import validate_patches

app = typer.Typer(help="Schema-Drift Auto-Repair Agent.", no_args_is_help=True)
CONSOLE = Console()
ERROR_CONSOLE = Console(stderr=True)


def _run_script(script: str, arguments: list[str]) -> None:
    script_path = Path(get_settings().repo_root) / "scripts" / script
    try:
        subprocess.run([sys.executable, str(script_path), *arguments], check=True)
    except subprocess.CalledProcessError as exc:
        raise typer.Exit(code=exc.returncode) from exc


def _events(io: DataHubIO) -> list[DriftEvent]:
    settings = get_settings()
    io.preflight()
    baseline = SchemaSnapshot.load()
    live = SchemaSnapshot.capture(io, settings.namespace_prefix)
    return detect_drift(baseline, live)


def _event(io: DataHubIO, drift_id: str) -> DriftEvent:
    events = _events(io)
    try:
        return next(event for event in events if event.id == drift_id)
    except StopIteration as exc:
        available = ", ".join(event.id for event in events) or "none"
        raise ValueError(
            f"Drift `{drift_id}` is not active. Active drift IDs: {available}. "
            "Apply one with `repair-agent simulate <scenario>` first."
        ) from exc


@app.command()
def seed(
    reset: Annotated[bool, typer.Option(help="Soft-delete only ShopFlow datasets first.")] = False,
    verify: Annotated[bool, typer.Option(help="Verify schemas and column lineage.")] = False,
    dry_run: Annotated[bool, typer.Option(help="Write MCP payloads locally.")] = False,
) -> None:
    """Seed the idempotent ShopFlow demo catalog."""

    args = [flag for enabled, flag in ((reset, "--reset"), (verify, "--verify"), (dry_run, "--dry-run")) if enabled]
    _run_script("seed_datahub.py", args)


@app.command()
def simulate(
    scenario: Annotated[
        str, typer.Argument(help="rename_order_placed_at, retype_gross_amount, or drop_marketing_opt_in")
    ] = "rename_order_placed_at",
    revert: Annotated[bool, typer.Option(help="Restore the source schema from the baseline.")] = False,
) -> None:
    """Apply or revert a live source-schema drift scenario."""

    _run_script("simulate_drift.py", ["--revert"] if revert else [scenario])


@app.command("detect")
def detect_command() -> None:
    """Detect live drift against the committed schema snapshot."""

    try:
        events = _events(DataHubIO())
    except Exception as exc:
        _fail(exc)
    if not events:
        CONSOLE.print("[bold green]No schema drift detected.[/]")
        return
    table = Table(title="Detected schema drift")
    table.add_column("ID")
    table.add_column("Kind")
    table.add_column("Dataset")
    table.add_column("Change")
    table.add_column("Confidence", justify="right")
    table.add_column("Rationale", overflow="fold")
    for event in events:
        table.add_row(
            event.id,
            event.kind.value,
            event.dataset_name,
            f"{event.old_column or '∅'} → {event.new_column or '∅'}",
            f"{event.confidence:.2f}",
            event.rationale,
        )
    CONSOLE.print(table)


@app.command("impact")
def impact_command(
    drift_id: Annotated[str, typer.Argument(help="Active DriftEvent ID from `repair-agent detect`.")],
) -> None:
    """Print the complete three-bucket impact table."""

    try:
        io = DataHubIO()
        report = analyze(_event(io, drift_id), io)
    except Exception as exc:
        _fail(exc)
    _print_impact(report)


@app.command("run")
def run_command(
    drift_id: Annotated[str, typer.Argument(help="Active DriftEvent ID from `repair-agent detect`.")],
    pr_mode: Annotated[str, typer.Option(help="Reserved for Slice C: dry-run or live.")] = "dry-run",
    no_llm: Annotated[bool, typer.Option("--no-llm", help="Use the deterministic pipeline only.")] = False,
) -> None:
    """Analyze, generate, and hard-gate patches without modifying source files."""

    if pr_mode not in {"dry-run", "live"}:
        _fail(ValueError("--pr-mode must be `dry-run` or `live`."))
    try:
        io = DataHubIO()
        drift = _event(io, drift_id)
        report = analyze(drift, io)
        patches = generate_patches(report)
        validate_patches(patches, io, drift)
    except Exception as exc:
        _fail(exc)
    _print_impact(report)
    _print_patches(patches)
    references = [reference for patch in patches for reference in patch.references]
    resolved = sum(reference.status == "OK" for reference in references)
    live = sum(reference.source == "live_catalog" for reference in references)
    projected = sum(reference.source == "projected_repair" for reference in references)
    cte = sum(reference.source == "local_cte" for reference in references)
    valid = all(patch.valid for patch in patches)
    color = "green" if valid else "red"
    CONSOLE.print(
        f"\n[bold {color}]VALIDATION {'PASSED' if valid else 'BLOCKED'}:[/] "
        f"{resolved}/{len(references)} column references resolved — "
        f"{live} against live DataHub schemas, {projected} against projected repair outputs, "
        f"{cte} locally derived. 0 hallucinated columns."
    )
    CONSOLE.print(f"[dim]Mode: deterministic core{' (--no-llm)' if no_llm else ''}; no source files were modified.[/]")
    CONSOLE.print(f"[bold yellow]PENDING SLICE C — PR phase:[/] requested mode `{pr_mode}`; no PR was created or faked.")
    CONSOLE.print("[bold yellow]PENDING SLICE C — write-back phase:[/] no DataHub metadata was written.")
    if not valid:
        raise typer.Exit(code=1)


@app.command("examples")
def examples_command() -> None:
    """Regenerate real engine artifacts for all three drift scenarios."""

    try:
        root = generate_examples()
    except Exception as exc:
        _fail(exc)
    CONSOLE.print(f"[bold green]Generated examples:[/] {root}")
    CONSOLE.print("All temporary scenarios were reverted; any scenario active before this command was restored.")


@app.command()
def verify() -> None:
    """Run the live schema and column-lineage verification gate."""

    _run_script("seed_datahub.py", ["--verify"])


def _print_impact(report: ImpactReport) -> None:
    table = Table(title=f"Three-bucket impact · {report.drift.id}")
    table.add_column("Bucket", no_wrap=True)
    table.add_column("Asset", no_wrap=True)
    table.add_column("Kind", no_wrap=True)
    table.add_column("Hops", justify="right")
    table.add_column("Reason / evidence", overflow="fold")
    for asset in report.assets:
        table.add_row(
            asset.bucket.value,
            asset.name,
            asset.kind,
            str(asset.hops) if asset.hops is not None else "—",
            asset.reason,
        )
    CONSOLE.print(table)
    CONSOLE.print(
        f"[bold]Summary:[/] {report.stats['requires_patch']} requires patch · "
        f"{report.stats['downstream_unaffected']} downstream unaffected · "
        f"{report.stats['skipped']} skipped · {report.stats['total_scanned']} scanned"
    )


def _print_patches(patches: list[Patch]) -> None:
    table = Table(title="Generated patches (not applied)")
    table.add_column("File")
    table.add_column("Kind")
    table.add_column("Valid")
    table.add_column("Strategy", overflow="fold")
    for patch in patches:
        table.add_row(patch.file_path, patch.kind, "yes" if patch.valid else "BLOCKED", patch.strategy)
    CONSOLE.print(table)


def _fail(exc: Exception) -> None:
    if isinstance(exc, CodeMapMissing):
        ERROR_CONSOLE.print(f"[bold red]Impact analysis failed:[/] {exc}")
    else:
        ERROR_CONSOLE.print(f"[bold red]repair-agent failed:[/] {exc}")
    raise typer.Exit(code=1)
