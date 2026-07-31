#!/usr/bin/env python3
"""Apply or revert one source-schema drift scenario in the live DataHub catalog."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from datahub.emitter.mce_builder import make_data_platform_urn, make_user_urn
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.metadata.schema_classes import (
    AuditStampClass,
    OtherSchemaClass,
    SchemaFieldClass,
    SchemaFieldDataTypeClass,
    SchemaMetadataClass,
)
from rich.console import Console
from seed_datahub import DATASET_DEFINITIONS, TYPE_CLASSES, dataset_urn

from repair_agent.config import Settings, get_settings
from repair_agent.datahub_io.client import DataHubIO

CONSOLE = Console()
ERROR_CONSOLE = Console(stderr=True)
SCENARIOS = (
    "rename_order_placed_at",
    "retype_gross_amount",
    "drop_marketing_opt_in",
)


def _state_paths(settings: Settings) -> tuple[Path, Path]:
    state_dir = settings.repo_root / "demo-warehouse" / ".repair-agent"
    return state_dir / "snapshot.json", state_dir / "applied_drift.json"


def _load_snapshot(settings: Settings) -> dict[str, dict[str, dict[str, Any]]]:
    snapshot_path, _ = _state_paths(settings)
    if not snapshot_path.exists():
        raise RuntimeError(f"Baseline snapshot is missing at {snapshot_path}. Run the idempotent seed first.")
    return json.loads(snapshot_path.read_text(encoding="utf-8"))


def _scenario_source(scenario: str) -> str:
    return "raw.customers" if scenario == "drop_marketing_opt_in" else "raw.orders"


def _apply_change(
    scenario: str,
    baseline_columns: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    columns = {name: dict(spec) for name, spec in baseline_columns.items()}
    if scenario == "rename_order_placed_at":
        renamed: dict[str, dict[str, Any]] = {}
        for name, spec in columns.items():
            if name == "order_placed_at":
                updated = dict(spec)
                updated["name"] = "order_created_at"
                updated["description"] = "Timestamp at which the order was created."
                renamed["order_created_at"] = updated
            else:
                renamed[name] = spec
        return renamed
    if scenario == "retype_gross_amount":
        columns["gross_amount"]["native_type"] = "VARCHAR(20)"
        columns["gross_amount"]["data_type"] = "string"
        return columns
    if scenario == "drop_marketing_opt_in":
        columns.pop("marketing_opt_in")
        return columns
    raise ValueError(f"Unknown scenario '{scenario}'. Choose one of: {', '.join(SCENARIOS)}")


def _emit_schema(
    io: DataHubIO,
    settings: Settings,
    definition_key: str,
    columns: dict[str, dict[str, Any]],
) -> str:
    definition = DATASET_DEFINITIONS[definition_key]
    urn = dataset_urn(definition, settings)
    platform = settings.warehouse_platform if definition.platform == "snowflake" else settings.dbt_platform
    now = int(datetime.now(UTC).timestamp() * 1000)
    stamp = AuditStampClass(time=now, actor=make_user_urn("datahub-repair-agent"))
    schema = SchemaMetadataClass(
        schemaName=definition.name,
        platform=make_data_platform_urn(platform),
        version=0,
        hash="",
        platformSchema=OtherSchemaClass(rawSchema=""),
        fields=[
            SchemaFieldClass(
                fieldPath=spec["name"],
                type=SchemaFieldDataTypeClass(type=TYPE_CLASSES[spec["data_type"]]()),
                nativeDataType=spec["native_type"],
                nullable=spec.get("nullable", True),
                description=spec.get("description"),
            )
            for spec in columns.values()
        ],
        created=stamp,
        lastModified=stamp,
    )
    io.graph.emit_mcp(MetadataChangeProposalWrapper(entityUrn=urn, aspect=schema))
    return urn


def apply_scenario(io: DataHubIO, settings: Settings, scenario: str) -> None:
    """Apply one declared drift without modifying the baseline snapshot."""

    snapshot = _load_snapshot(settings)
    source_key = _scenario_source(scenario)
    source_urn = dataset_urn(DATASET_DEFINITIONS[source_key], settings)
    if source_urn not in snapshot:
        raise RuntimeError(f"Baseline snapshot has no schema for {source_urn}; re-run the seed.")
    changed_columns = _apply_change(scenario, snapshot[source_urn])
    _emit_schema(io, settings, source_key, changed_columns)

    _, applied_path = _state_paths(settings)
    applied_path.write_text(
        json.dumps(
            {
                "scenario": scenario,
                "dataset_urn": source_urn,
                "applied_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    live_fields = [field.name for field in io.get_schema(source_urn, skip_cache=True).columns]
    CONSOLE.print(f"[bold yellow]Applied drift:[/] {scenario}")
    CONSOLE.print(f"[bold]Live dataset:[/] {source_urn}")
    CONSOLE.print(f"[bold]Live fieldPaths:[/] {', '.join(live_fields)}")
    CONSOLE.print("[green]Baseline snapshot was not modified.[/]")


def revert_scenario(io: DataHubIO, settings: Settings) -> None:
    """Restore the last drifted source schema from the immutable baseline snapshot."""

    snapshot = _load_snapshot(settings)
    _, applied_path = _state_paths(settings)
    if not applied_path.exists():
        raise RuntimeError(f"No applied drift record exists at {applied_path}. Apply a scenario before --revert.")
    applied = json.loads(applied_path.read_text(encoding="utf-8"))
    scenario = applied.get("scenario")
    if scenario not in SCENARIOS:
        raise RuntimeError(f"Applied drift record contains an unsupported scenario: {scenario!r}")
    source_key = _scenario_source(scenario)
    source_urn = dataset_urn(DATASET_DEFINITIONS[source_key], settings)
    baseline_columns = snapshot.get(source_urn)
    if baseline_columns is None:
        raise RuntimeError(f"Baseline snapshot has no schema for {source_urn}; re-run the seed.")

    _emit_schema(io, settings, source_key, baseline_columns)
    applied_path.unlink()
    live_fields = [field.name for field in io.get_schema(source_urn, skip_cache=True).columns]
    CONSOLE.print(f"[bold green]Reverted drift:[/] {scenario}")
    CONSOLE.print(f"[bold]Live dataset:[/] {source_urn}")
    CONSOLE.print(f"[bold]Restored fieldPaths:[/] {', '.join(live_fields)}")
    CONSOLE.print("[green]Baseline snapshot remains unchanged.[/]")


def parse_args() -> argparse.Namespace:
    """Parse the positional and compatibility flag forms of the scenario CLI."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", nargs="?", choices=SCENARIOS)
    parser.add_argument("--scenario", dest="scenario_flag", choices=SCENARIOS)
    parser.add_argument("--revert", action="store_true", help="Restore the last drifted schema.")
    return parser.parse_args()


def main() -> int:
    """Apply or revert a scenario after validating the configured GMS endpoint."""

    args = parse_args()
    settings = get_settings()
    io = DataHubIO(settings)
    try:
        io.preflight()
        if args.revert:
            if args.scenario or args.scenario_flag:
                raise ValueError("--revert does not accept a scenario; it uses applied_drift.json.")
            revert_scenario(io, settings)
            return 0
        scenario = args.scenario_flag or args.scenario
        if scenario is None:
            raise ValueError(f"Choose a scenario ({', '.join(SCENARIOS)}) or pass --revert.")
        if args.scenario and args.scenario_flag:
            raise ValueError("Pass the scenario either positionally or with --scenario, not both.")
        apply_scenario(io, settings, scenario)
        return 0
    except Exception as exc:
        ERROR_CONSOLE.print(f"[bold red]Drift simulation failed:[/] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
