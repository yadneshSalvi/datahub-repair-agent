"""Orchestrate deterministic code transforms into reviewable unified patches."""

from __future__ import annotations

import difflib
import logging
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from repair_agent.codegen import airflow_ops, dbt_yaml, sql_ops
from repair_agent.config import Settings, get_settings
from repair_agent.models import DriftKind, ImpactBucket, ImpactReport, Patch

LOGGER = logging.getLogger(__name__)


def generate_patches(impact: ImpactReport, settings: Settings | None = None) -> list[Patch]:
    """Generate surgical SQL, dbt YAML, and Airflow patches for impacted code."""

    active_settings = settings or get_settings()
    code_map = _load_code_map(active_settings.repo_root / "demo-warehouse" / "code_map.yml")
    patches: list[Patch] = []
    drift = impact.drift
    for asset in impact.assets:
        if asset.bucket is not ImpactBucket.REQUIRES_PATCH:
            continue
        if asset.kind == "dbt_model":
            mapping = code_map["datasets"].get(asset.urn)
            if mapping is None:
                raise KeyError(f"No code_map.yml dataset entry for patch-required asset {asset.urn}.")
            sql_path = active_settings.repo_root / mapping["sql"]
            before = sql_path.read_text(encoding="utf-8")
            after, strategy = _transform_sql(before, impact)
            if after != before:
                patches.append(_patch(asset.urn, mapping["sql"], before, after, "dbt_sql", strategy))

            schema_path = active_settings.repo_root / mapping["schema_yml"]
            schema_before = schema_path.read_text(encoding="utf-8")
            schema_after = schema_before
            schema_strategy = ""
            if drift.kind is DriftKind.RENAME and drift.old_column and drift.new_column:
                schema_after = dbt_yaml.rename_column(
                    schema_before,
                    mapping["model_name"],
                    drift.old_column,
                    drift.new_column,
                )
                schema_strategy = (
                    f"Renamed the `{mapping['model_name']}.{drift.old_column}` dbt metadata entry, carried its description "
                    "forward with provenance, and added a built-in test."
                )
            elif drift.kind is DriftKind.DROP and drift.old_column:
                for output_name in sql_ops.affected_output_columns(before, drift.old_column):
                    schema_after = dbt_yaml.drop_column(schema_after, mapping["model_name"], output_name)
                schema_strategy = (
                    f"Removed metadata and tests for outputs derived from dropped `{drift.old_column}` after preserving "
                    "the SQL as a commented deprecation record."
                )
            if schema_after != schema_before:
                patches.append(
                    _patch(
                        asset.urn,
                        mapping["schema_yml"],
                        schema_before,
                        schema_after,
                        "dbt_schema_yml",
                        schema_strategy,
                    )
                )
        elif asset.kind == "airflow_task":
            mapping = code_map["datajobs"].get(asset.urn)
            if mapping is None:
                raise KeyError(f"No code_map.yml datajob entry for patch-required asset {asset.urn}.")
            path = active_settings.repo_root / mapping["file"]
            before = path.read_text(encoding="utf-8")
            names = list(mapping.get("sql_constants", []))
            if drift.kind is DriftKind.RENAME and drift.old_column and drift.new_column:
                after = airflow_ops.rename_column(before, names, drift.old_column, drift.new_column)
                strategy = (
                    f"Renamed exact `{drift.old_column}` references inside {', '.join(names)} while preserving the "
                    "module's triple-quoted string style and indentation."
                )
            elif drift.kind is DriftKind.RETYPE and drift.old_column and drift.old_type and drift.new_type:
                after = airflow_ops.retype_column(before, names, drift.old_column, drift.old_type, drift.new_type)
                strategy = (
                    f"Wrapped `{drift.old_column}` references inside {', '.join(names)} with CAST(... AS {drift.old_type}) "
                    f"to preserve semantics after the upstream {drift.new_type} retype."
                )
            elif drift.kind is DriftKind.DROP and drift.old_column:
                after = airflow_ops.drop_column(before, names, drift.old_column)
                strategy = (
                    f"Deprecated `{drift.old_column}` SELECT entries inside {', '.join(names)} with provenance and a TODO."
                )
            else:
                continue
            if after != before:
                patches.append(_patch(asset.urn, mapping["file"], before, after, "airflow_python", strategy))
    LOGGER.info("Generated %d deterministic patches for %s", len(patches), drift.id)
    return patches


def _transform_sql(sql: str, impact: ImpactReport) -> tuple[str, str]:
    drift = impact.drift
    if drift.kind is DriftKind.RENAME and drift.old_column and drift.new_column:
        return (
            sql_ops.rename_column(sql, drift.old_column, drift.new_column),
            f"Renamed only exact AST column references from `{drift.old_column}` to `{drift.new_column}`; "
            "output aliases and unrelated formatting were preserved.",
        )
    if drift.kind is DriftKind.RETYPE and drift.old_column and drift.old_type and drift.new_type:
        return (
            sql_ops.retype_column(sql, drift.old_column, drift.old_type, drift.new_type),
            f"Wrapped exact `{drift.old_column}` references in CAST(... AS {drift.old_type}) to preserve "
            f"downstream semantics after the upstream {drift.new_type} retype.",
        )
    if drift.kind is DriftKind.DROP and drift.old_column:
        return (
            sql_ops.drop_column(sql, drift.old_column),
            f"Commented every SELECT entry derived from dropped `{drift.old_column}` with repair provenance "
            "and a data-team TODO; nothing was silently deleted.",
        )
    return sql, "No deterministic transform applies to this drift."


def _patch(
    asset_urn: str,
    file_path: str,
    before: str,
    after: str,
    kind: str,
    strategy: str,
) -> Patch:
    relative = Path(file_path).as_posix()
    unified = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{relative}",
            tofile=f"b/{relative}",
        )
    )
    return Patch(
        asset_urn=asset_urn,
        file_path=relative,
        before=before,
        after=after,
        unified_diff=unified,
        kind=kind,  # type: ignore[arg-type]
        references=[],
        valid=False,
        strategy=strategy,
    )


def _load_code_map(path: Path) -> dict[str, dict[str, dict[str, Any]]]:
    document = YAML(typ="safe").load(path)
    return {"datasets": document.get("datasets", {}), "datajobs": document.get("datajobs", {})}
