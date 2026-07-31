"""AST-safe rewriting of module-level Airflow SQL string constants."""

from __future__ import annotations

import ast
import re
from collections.abc import Callable

from repair_agent.codegen import sql_ops

TRIPLE_QUOTE = re.compile(r"(?is)^([rub]*)('''|\"\"\")")


def extract_sql_constants(source: str, names: list[str]) -> dict[str, str]:
    """Return configured module-level string constants from a Python module."""

    tree = ast.parse(source)
    wanted = set(names)
    extracted: dict[str, str] = {}
    for statement in tree.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        value = statement.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id in wanted:
                extracted[target.id] = value.value
    missing = wanted - extracted.keys()
    if missing:
        raise ValueError(
            f"Airflow SQL constant(s) {sorted(missing)} were not found as module-level strings. Update code_map.yml."
        )
    return extracted


def rewrite_sql_constants(source: str, names: list[str], transform: Callable[[str], str]) -> str:
    """Rewrite selected triple-quoted constants and verify the module still parses."""

    tree = ast.parse(source)
    edits: list[sql_ops.TextEdit] = []
    wanted = set(names)
    found: set[str] = set()
    line_offsets = _line_offsets(source)
    for statement in tree.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        value = statement.value
        selected = [target.id for target in targets if isinstance(target, ast.Name) and target.id in wanted]
        if not selected or not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        segment = ast.get_source_segment(source, value)
        if segment is None:
            raise ValueError(f"Could not locate the source span for Airflow SQL constant {selected[0]}.")
        quote_match = TRIPLE_QUOTE.match(segment)
        if quote_match is None:
            raise ValueError(f"Airflow SQL constant {selected[0]} must use triple quotes so formatting can be preserved.")
        quote = quote_match.group(2)
        prefix = quote_match.group(1)
        rewritten = transform(value.value)
        replacement = f"{prefix}{quote}{rewritten}{quote}"
        start = line_offsets[value.lineno - 1] + value.col_offset
        end = line_offsets[value.end_lineno - 1] + value.end_col_offset
        edits.append(sql_ops.TextEdit(start, end, replacement))
        found.update(selected)
    missing = wanted - found
    if missing:
        raise ValueError(f"Airflow SQL constant(s) {sorted(missing)} were not found. Update code_map.yml.")
    result = sql_ops.apply_edits(source, edits)
    ast.parse(result)
    return result


def rename_column(source: str, names: list[str], old: str, new: str) -> str:
    """Rename exact SQL references inside configured Airflow constants."""

    return rewrite_sql_constants(source, names, lambda sql: sql_ops.rename_column(sql, old, new))


def retype_column(source: str, names: list[str], column: str, old_type: str, new_type: str) -> str:
    """Cast exact SQL references inside configured Airflow constants."""

    return rewrite_sql_constants(source, names, lambda sql: sql_ops.retype_column(sql, column, old_type, new_type))


def drop_column(source: str, names: list[str], column: str) -> str:
    """Deprecate SELECT entries inside configured Airflow constants."""

    return rewrite_sql_constants(source, names, lambda sql: sql_ops.drop_column(sql, column))


def _line_offsets(source: str) -> list[int]:
    offsets = [0]
    for index, character in enumerate(source):
        if character == "\n":
            offsets.append(index + 1)
    return offsets
