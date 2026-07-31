"""Resolve every generated SQL column reference against DataHub schema metadata."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import sqlglot
from datahub.emitter.mce_builder import make_dataset_urn
from datahub.metadata.urns import DatasetUrn
from ruamel.yaml import YAML
from sqlglot import expressions as exp
from sqlglot.optimizer.scope import Scope, traverse_scope

from repair_agent.codegen.airflow_ops import extract_sql_constants
from repair_agent.codegen.jinja import mask
from repair_agent.codegen.sql_ops import output_columns
from repair_agent.config import Settings, get_settings
from repair_agent.datahub_io.client import DataHubIO
from repair_agent.models import DriftEvent, DriftKind, Patch, ReferenceCheck

LOGGER = logging.getLogger(__name__)
SOURCE_CALL = re.compile(r"\{\{\s*source\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}")
REF_CALL = re.compile(r"\{\{\s*ref\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}")
SchemaCache = dict[str, set[str] | None]


def validate_patch(
    patch: Patch,
    datahub_io: DataHubIO,
    drift: DriftEvent | None = None,
    *,
    schema_cache: SchemaCache | None = None,
    settings: Settings | None = None,
    projected_urns: set[str] | None = None,
) -> list[ReferenceCheck]:
    """Validate one patch and mutate ``patch.references`` / ``patch.valid`` as the hard gate."""

    active_settings = settings or get_settings()
    cache = schema_cache if schema_cache is not None else {}
    if patch.kind in {"dbt_schema_yml", "dbt_test"}:
        patch.references = []
        patch.valid = True
        return []

    sql_units: list[tuple[str, str]]
    if patch.kind == "airflow_python":
        code_map = _load_code_map(active_settings.repo_root / "demo-warehouse" / "code_map.yml")
        mapping = code_map["datajobs"].get(patch.asset_urn)
        if mapping is None:
            check = ReferenceCheck(
                table=patch.file_path,
                column="<sql constant>",
                line=None,
                status="UNKNOWN_TABLE",
                detail="Airflow patch has no code_map.yml datajob entry; add its SQL constant mapping before validation.",
            )
            patch.references = [check]
            patch.valid = False
            return [check]
        try:
            constants = extract_sql_constants(patch.after, list(mapping.get("sql_constants", [])))
        except (SyntaxError, ValueError) as exc:
            check = _parse_failure(patch.file_path, exc)
            patch.references = [check]
            patch.valid = False
            return [check]
        sql_units = list(constants.items())
    else:
        sql_units = [(patch.file_path, patch.after)]

    checks: list[ReferenceCheck] = []
    for unit_name, sql in sql_units:
        try:
            checks.extend(
                _validate_sql(sql, datahub_io, drift, cache, active_settings, projected_urns or set())
            )
        except sqlglot.errors.ParseError as exc:
            checks.append(_parse_failure(unit_name, exc))
    patch.references = checks
    patch.valid = all(check.status == "OK" for check in checks)
    return checks


def validate_patches(
    patches: list[Patch],
    datahub_io: DataHubIO,
    drift: DriftEvent | None = None,
    *,
    settings: Settings | None = None,
) -> list[Patch]:
    """Validate a repair set with one per-run schema cache and projected upstream outputs."""

    active_settings = settings or get_settings()
    cache: SchemaCache = {}
    projected_urns: set[str] = set()
    # A downstream patch may reference an upstream output renamed by another patch in the
    # same repair. Seed the cache with those deterministic projected schemas; every other
    # lookup still comes directly from the live catalog.
    for patch in patches:
        if patch.kind == "dbt_sql":
            projected = output_columns(patch.after)
            if projected:
                cache[patch.asset_urn] = {name.casefold() for name in projected}
                projected_urns.add(patch.asset_urn)
    for patch in patches:
        validate_patch(
            patch,
            datahub_io,
            drift,
            schema_cache=cache,
            settings=active_settings,
            projected_urns=projected_urns,
        )
    return patches


def _validate_sql(
    sql: str,
    datahub_io: DataHubIO,
    drift: DriftEvent | None,
    cache: SchemaCache,
    settings: Settings,
    projected_urns: set[str],
) -> list[ReferenceCheck]:
    masked_sql, jinja_mapping = mask(sql)
    tree = sqlglot.parse_one(masked_sql, dialect="snowflake")
    token_urns = _jinja_urns(jinja_mapping, settings)
    checks: list[ReferenceCheck] = []
    for scope in traverse_scope(tree):
        for column in scope.columns:
            if column.is_star:
                continue
            line = column.this.meta.get("line") if isinstance(column.this, exp.Identifier) else None
            local_source = _local_cte_source(column, scope)
            if local_source is not None:
                checks.append(
                    ReferenceCheck(
                        table=f"CTE {local_source}",
                        column=column.name,
                        line=line,
                        status="OK",
                        detail=(
                            f"Resolved `{local_source}.{column.name}` as a locally derived CTE output; its input "
                            "references are validated separately."
                        ),
                        source="local_cte",
                    )
                )
                continue
            candidate_urns = _column_sources(column, scope, token_urns, settings)
            table_label = column.table or _scope_label(scope)
            if not candidate_urns:
                checks.append(
                    ReferenceCheck(
                        table=table_label,
                        column=column.name,
                        line=line,
                        status="UNKNOWN_TABLE",
                        detail=(
                            f"Could not resolve table or CTE source `{table_label}` through code_map.yml or a "
                            "fully-qualified name."
                        ),
                    )
                )
                continue

            schemas = {urn: _schema_columns(urn, datahub_io, cache) for urn in candidate_urns}
            containing = [
                urn for urn, columns in schemas.items() if columns is not None and column.name.casefold() in columns
            ]
            if len(candidate_urns) > 1 and len(containing) == 1:
                resolved_urn = containing[0]
            elif len(candidate_urns) == 1:
                resolved_urn = candidate_urns[0]
            elif containing:
                resolved_urn = containing[0]
            else:
                resolved_urn = candidate_urns[0]

            schema = schemas[resolved_urn]
            resolved_name = _dataset_name(resolved_urn)
            if schema is None:
                checks.append(
                    ReferenceCheck(
                        table=resolved_name,
                        column=column.name,
                        line=line,
                        status="UNKNOWN_TABLE",
                        detail=(
                            f"DataHub has no live schemaMetadata for `{resolved_name}`; seed or map that dataset "
                            "before repair."
                        ),
                    )
                )
            elif (
                drift is not None
                and drift.kind in {DriftKind.RENAME, DriftKind.DROP}
                and drift.old_column is not None
                and resolved_urn == drift.dataset_urn
                and column.name.casefold() == drift.old_column.casefold()
            ):
                checks.append(
                    ReferenceCheck(
                        table=resolved_name,
                        column=column.name,
                        line=line,
                        status="STALE_OLD_NAME",
                        detail=(
                            f"`{resolved_name}.{column.name}` is the stale pre-drift name and cannot pass the repair gate."
                        ),
                    )
                )
            elif column.name.casefold() not in schema:
                checks.append(
                    ReferenceCheck(
                        table=resolved_name,
                        column=column.name,
                        line=line,
                        status="UNKNOWN_COLUMN",
                        detail=f"`{column.name}` is absent from the live/projected schema for `{resolved_name}`.",
                    )
                )
            else:
                projected = resolved_urn in projected_urns
                origin = "projected repaired" if projected else "live DataHub"
                checks.append(
                    ReferenceCheck(
                        table=resolved_name,
                        column=column.name,
                        line=line,
                        status="OK",
                        detail=f"Resolved `{resolved_name}.{column.name}` against the {origin} schema.",
                        source="projected_repair" if projected else "live_catalog",
                    )
                )
    return checks


def _column_sources(
    column: exp.Column,
    scope: Scope,
    token_urns: dict[str, str],
    settings: Settings,
) -> list[str]:
    if column.table:
        selected = scope.selected_sources.get(column.table)
        if selected is None:
            return []
        return _source_urns(selected[1], token_urns, settings)
    urns: list[str] = []
    for _, source in scope.selected_sources.values():
        urns.extend(_source_urns(source, token_urns, settings))
    return list(dict.fromkeys(urns))


def _local_cte_source(column: exp.Column, scope: Scope) -> str | None:
    candidates: list[tuple[str, Scope]] = []
    if column.table:
        selected = scope.selected_sources.get(column.table)
        if selected is not None and isinstance(selected[1], Scope):
            candidates.append((column.table, selected[1]))
    else:
        candidates.extend(
            (alias, source)
            for alias, (_, source) in scope.selected_sources.items()
            if isinstance(source, Scope)
        )
    for alias, source in candidates:
        outputs = {
            expression.alias_or_name.casefold()
            for expression in source.expression.expressions
            if expression.alias_or_name and not expression.is_star
        }
        if column.name.casefold() in outputs:
            return alias
    return None


def _source_urns(source: exp.Expression | Scope, token_urns: dict[str, str], settings: Settings) -> list[str]:
    if isinstance(source, Scope):
        urns: list[str] = []
        for _, nested in source.selected_sources.values():
            urns.extend(_source_urns(nested, token_urns, settings))
        return list(dict.fromkeys(urns))
    if isinstance(source, exp.Table):
        if source.name in token_urns:
            return [token_urns[source.name]]
        parts = [part.name for part in source.parts]
        if len(parts) >= 3:
            qualified = ".".join(parts[-3:])
            return [make_dataset_urn(settings.warehouse_platform, qualified, settings.env)]
    return []


def _jinja_urns(mapping: dict[str, str], settings: Settings) -> dict[str, str]:
    code_map = _load_code_map(settings.repo_root / "demo-warehouse" / "code_map.yml")
    model_urns = {entry.get("model_name"): urn for urn, entry in code_map["datasets"].items()}
    resolved: dict[str, str] = {}
    for token, original in mapping.items():
        source = SOURCE_CALL.fullmatch(original)
        if source:
            source_name, table = source.groups()
            schema = "raw" if source_name == "shop_raw" else source_name
            resolved[token] = make_dataset_urn(
                settings.warehouse_platform,
                f"shop_prod.{schema}.{table}",
                settings.env,
            )
            continue
        ref = REF_CALL.fullmatch(original)
        if ref and ref.group(1) in model_urns:
            resolved[token] = model_urns[ref.group(1)]
    return resolved


def _schema_columns(urn: str, datahub_io: DataHubIO, cache: SchemaCache) -> set[str] | None:
    if urn in cache:
        return cache[urn]
    schema = datahub_io.get_schema(urn, skip_cache=True)
    columns = {column.name.casefold() for column in schema.columns}
    cache[urn] = columns or None
    return cache[urn]


def _scope_label(scope: Scope) -> str:
    names = sorted(scope.selected_sources)
    return ", ".join(names) if names else "<unresolved>"


def _dataset_name(urn: str) -> str:
    try:
        return DatasetUrn.from_string(urn).name
    except ValueError:
        return urn


def _parse_failure(name: str, exc: Exception) -> ReferenceCheck:
    return ReferenceCheck(
        table=name,
        column="<parse>",
        line=None,
        status="UNKNOWN_TABLE",
        detail=f"Generated SQL does not parse: {exc}. Fix the deterministic transform before opening a PR.",
    )


def _load_code_map(path: Path) -> dict[str, dict[str, dict[str, Any]]]:
    document = YAML(typ="safe").load(path)
    return {"datasets": document.get("datasets", {}), "datajobs": document.get("datajobs", {})}
