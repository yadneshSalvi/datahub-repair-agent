"""Minimal Slice A command-line entry point."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer

from repair_agent.config import get_settings

app = typer.Typer(help="Schema-Drift Auto-Repair Agent utilities.", no_args_is_help=True)


def _run_script(script: str, arguments: list[str]) -> None:
    script_path = Path(get_settings().repo_root) / "scripts" / script
    try:
        subprocess.run([sys.executable, str(script_path), *arguments], check=True)
    except subprocess.CalledProcessError as exc:
        raise typer.Exit(code=exc.returncode) from exc


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


@app.command()
def verify() -> None:
    """Run the live schema and column-lineage verification gate."""

    _run_script("seed_datahub.py", ["--verify"])
