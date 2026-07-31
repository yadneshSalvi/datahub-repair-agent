"""Round-trip-safe dbt schema YAML edits."""

from __future__ import annotations

from io import StringIO

from ruamel.yaml import YAML

PROVENANCE = "Renamed by schema-drift-repair from `{old}` to `{new}`."


def rename_column(schema_yml: str, model_name: str, old: str, new: str) -> str:
    """Rename one model column, preserve its description, and add a built-in test."""

    yaml, document = _load(schema_yml)
    column = _find_column(document, model_name, old)
    if column is None:
        return schema_yml
    column["name"] = new
    note = PROVENANCE.format(old=old, new=new)
    description = str(column.get("description") or "").rstrip()
    if note not in description:
        column["description"] = f"{description} {note}".strip()
    tests = column.setdefault("tests", [])
    if "not_null" not in tests:
        tests.append("not_null")
    elif "unique" not in tests:
        tests.append("unique")
    return _dump(yaml, document)


def drop_column(schema_yml: str, model_name: str, column_name: str) -> str:
    """Remove a deprecated output column and all of its tests from one model."""

    yaml, document = _load(schema_yml)
    model = _find_model(document, model_name)
    if model is None:
        return schema_yml
    columns = model.get("columns") or []
    retained = [column for column in columns if str(column.get("name", "")).casefold() != column_name.casefold()]
    if len(retained) == len(columns):
        return schema_yml
    model["columns"] = retained
    return _dump(yaml, document)


def _load(source: str):  # type: ignore[no-untyped-def]
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml, yaml.load(source)


def _dump(yaml: YAML, document: object) -> str:
    stream = StringIO()
    yaml.dump(document, stream)
    return stream.getvalue()


def _find_model(document: object, model_name: str):  # type: ignore[no-untyped-def]
    if not isinstance(document, dict):
        return None
    return next((model for model in document.get("models", []) if model.get("name") == model_name), None)


def _find_column(document: object, model_name: str, column_name: str):  # type: ignore[no-untyped-def]
    model = _find_model(document, model_name)
    if model is None:
        return None
    return next(
        (column for column in model.get("columns", []) if str(column.get("name", "")).casefold() == column_name.casefold()),
        None,
    )
