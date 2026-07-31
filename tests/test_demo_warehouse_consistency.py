"""Guards against divergence between demo SQL, dbt YAML, and seeded DataHub metadata."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import sqlglot
from ruamel.yaml import YAML
from sqlglot import expressions as exp

from scripts.seed_datahub import DATASET_DEFINITIONS, MODEL_LINEAGE

REPO_ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE_ROOT = REPO_ROOT / "demo-warehouse"
YAML = YAML(typ="safe")
SOURCE_PATTERN = re.compile(r"\{\{\s*source\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}")
REF_PATTERN = re.compile(r"\{\{\s*ref\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}")


def _mask_jinja(sql: str) -> str:
    masked = SOURCE_PATTERN.sub(lambda match: f"{match.group(1)}.{match.group(2)}", sql)
    return REF_PATTERN.sub(lambda match: match.group(1), masked)


def _sql_output_columns(path: Path) -> list[str]:
    parsed = sqlglot.parse_one(_mask_jinja(path.read_text(encoding="utf-8")), dialect="snowflake")
    if not isinstance(parsed, exp.Select):
        raise AssertionError(f"Expected an outer SELECT in {path}, got {type(parsed).__name__}")
    columns = [expression.alias_or_name for expression in parsed.expressions]
    if any(not name for name in columns):
        raise AssertionError(f"Every output expression must have a resolvable name in {path}")
    return columns


def _schema_models() -> dict[str, dict[str, Any]]:
    models: dict[str, dict[str, Any]] = {}
    for path in (
        WAREHOUSE_ROOT / "models" / "staging" / "schema.yml",
        WAREHOUSE_ROOT / "models" / "marts" / "schema.yml",
    ):
        document = YAML.load(path)
        for model in document["models"]:
            if model["name"] in models:
                raise AssertionError(f"Duplicate dbt model metadata for {model['name']}")
            models[model["name"]] = model
    return models


def test_model_columns_match_sql_schema_yml_and_seed_lineage() -> None:
    schema_models = _schema_models()
    sql_paths = {path.stem: path for path in (WAREHOUSE_ROOT / "models").glob("**/*.sql")}
    assert set(sql_paths) == set(schema_models) == set(MODEL_LINEAGE)

    for model_name, sql_path in sorted(sql_paths.items()):
        sql_columns = _sql_output_columns(sql_path)
        yaml_columns = [column["name"] for column in schema_models[model_name]["columns"]]
        lineage_columns = list(MODEL_LINEAGE[model_name])
        assert sql_columns == yaml_columns == lineage_columns, (
            f"{model_name} differs across SQL/YAML/seed: SQL={sql_columns}, YAML={yaml_columns}, seed={lineage_columns}"
        )


def test_every_model_and_column_has_description_and_tests() -> None:
    for model_name, model in _schema_models().items():
        assert model.get("description"), f"{model_name} needs a model description"
        for column in model["columns"]:
            assert column.get("description"), f"{model_name}.{column['name']} needs a description"
        assert any(column.get("tests") for column in model["columns"]), f"{model_name} needs at least one declared dbt test"


def test_lineage_upstreams_reference_declared_fields() -> None:
    for model_name, outputs in MODEL_LINEAGE.items():
        expected_outputs = [column.name for column in DATASET_DEFINITIONS[model_name].columns]
        assert list(outputs) == expected_outputs
        for output_name, mapping in outputs.items():
            for upstream_key, upstream_column in mapping["upstreams"]:
                declared = {column.name for column in DATASET_DEFINITIONS[upstream_key].columns}
                assert upstream_column in declared, (
                    f"{model_name}.{output_name} references missing seed field {upstream_key}.{upstream_column}"
                )


def test_code_map_urns_point_to_existing_files() -> None:
    code_map = YAML.load(WAREHOUSE_ROOT / "code_map.yml")
    assert set(code_map) == {"datasets", "datajobs"}
    for urn, mapping in code_map["datasets"].items():
        assert urn.startswith("urn:li:dataset:"), urn
        for key in ("sql", "schema_yml"):
            path = REPO_ROOT / mapping[key]
            assert path.is_file(), f"{urn} maps {key} to missing file {path}"
    for urn, mapping in code_map["datajobs"].items():
        assert urn.startswith("urn:li:dataJob:"), urn
        path = REPO_ROOT / mapping["file"]
        assert path.is_file(), f"{urn} maps to missing file {path}"
