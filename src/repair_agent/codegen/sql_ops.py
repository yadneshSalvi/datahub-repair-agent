"""Surgical SQL edits located with sqlglot and applied to original source text."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import sqlglot
from sqlglot import expressions as exp

from repair_agent.codegen.jinja import mask, unmask


@dataclass(frozen=True)
class ColumnRef:
    """One exact column identifier located in source text."""

    name: str
    table_alias: str | None
    line: int | None
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class TextEdit:
    """Half-open source span replacement."""

    start: int
    end: int
    replacement: str


def apply_edits(source: str, edits: list[TextEdit]) -> str:
    """Apply non-overlapping text edits right-to-left without reformatting source."""

    ordered = sorted(edits, key=lambda edit: (edit.start, edit.end))
    previous_end = -1
    for edit in ordered:
        if edit.start < 0 or edit.end < edit.start or edit.end > len(source):
            raise ValueError(f"Text edit span [{edit.start}, {edit.end}) is outside a {len(source)}-byte source string.")
        if edit.start < previous_end:
            raise ValueError("Text edits overlap; refuse to emit an ambiguous source patch.")
        previous_end = edit.end
    result = source
    for edit in reversed(ordered):
        result = result[: edit.start] + edit.replacement + result[edit.end :]
    return result


def find_column_references(
    sql: str,
    dialect: str = "snowflake",
    jinja_mapping: dict[str, str] | None = None,
) -> list[ColumnRef]:
    """Locate SQL column nodes exactly; substrings and output aliases are excluded."""

    masked_sql, _ = mask(sql) if jinja_mapping is None else (sql, jinja_mapping)
    tree = sqlglot.parse_one(masked_sql, dialect=dialect)
    references: list[ColumnRef] = []
    for column in tree.find_all(exp.Column):
        identifier = column.this
        start = identifier.meta.get("start")
        end = identifier.meta.get("end")
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        references.append(
            ColumnRef(
                name=column.name,
                table_alias=column.table or None,
                line=identifier.meta.get("line"),
                start=start,
                end=end + 1,
                text=masked_sql[start : end + 1],
            )
        )
    return sorted(references, key=lambda reference: (reference.start, reference.end))


def rename_column(
    sql: str,
    old: str,
    new: str,
    *,
    scope_table: str | None = None,
    dialect: str = "snowflake",
) -> str:
    """Rename exact AST column identifiers while preserving every unrelated byte."""

    masked_sql, mapping = mask(sql)
    references = find_column_references(masked_sql, dialect, mapping)
    edits = [
        TextEdit(reference.start, reference.end, _match_identifier_case(reference.text, new))
        for reference in references
        if reference.name.casefold() == old.casefold()
        and (scope_table is None or (reference.table_alias or "").casefold() == scope_table.casefold())
    ]
    return unmask(apply_edits(masked_sql, edits), mapping)


def retype_column(
    sql: str,
    column: str,
    old_type: str,
    new_type: str,
    cast_to: str | None = None,
    *,
    dialect: str = "snowflake",
) -> str:
    """Cast exact references back to the old semantic type after an upstream retype."""

    del new_type  # The strategy preserves old downstream semantics by design.
    target_type = cast_to or old_type
    masked_sql, mapping = mask(sql)
    tree = sqlglot.parse_one(masked_sql, dialect=dialect)
    edits: list[TextEdit] = []
    for reference in _column_nodes(tree, masked_sql):
        node, start, end = reference
        if node.name.casefold() != column.casefold():
            continue
        if (
            isinstance(node.parent, exp.Cast)
            and node.parent.args.get("to", exp.DataType()).sql().casefold() == target_type.casefold()
        ):
            continue
        original = masked_sql[start:end]
        replacement = f"CAST({original} AS {target_type})"
        if isinstance(node.parent, exp.Select):
            replacement += f" AS {node.name}"
        edits.append(TextEdit(start, end, replacement))
    return unmask(apply_edits(masked_sql, edits), mapping)


def drop_column(
    sql: str,
    column: str,
    *,
    mode: str = "deprecate",
    dialect: str = "snowflake",
) -> str:
    """Comment affected SELECT entries with provenance and a reviewer TODO."""

    if mode != "deprecate":
        raise ValueError("DROP supports only mode='deprecate'; silent deletion is forbidden by D22.")
    masked_sql, _ = mask(sql)
    tree = sqlglot.parse_one(masked_sql, dialect=dialect)
    affected: dict[tuple[int, int], tuple[exp.Select, exp.Expression]] = {}
    for node in tree.find_all(exp.Column):
        if node.name.casefold() != column.casefold():
            continue
        select, expression = _select_entry(node)
        if select is None or expression is None:
            continue
        lines = [
            part.meta.get("line") for part in expression.find_all(exp.Identifier) if isinstance(part.meta.get("line"), int)
        ]
        if not lines:
            continue
        affected[(min(lines), max(lines))] = (select, expression)
    if not affected:
        return sql

    source_lines = sql.splitlines(keepends=True)
    date_text = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    for (start_line, end_line), (select, expression) in sorted(affected.items(), reverse=True):
        start_index, end_index = start_line - 1, end_line - 1
        original_lines = source_lines[start_index : end_index + 1]
        indent = original_lines[0][: len(original_lines[0]) - len(original_lines[0].lstrip())]
        commented = []
        for index, original in enumerate(original_lines):
            content = original.rstrip("\r\n")
            newline = original[len(content) :]
            if index == 0:
                commented.append(
                    f"{indent}-- REMOVED BY schema-drift-repair ({date_text}): upstream column dropped. "
                    f"{content.lstrip()}{newline or chr(10)}"
                )
            else:
                commented.append(f"{indent}-- {content.lstrip()}{newline or chr(10)}")
        commented.append(f"{indent}-- TODO(data-team): confirm no consumer depends on this\n")
        source_lines[start_index : end_index + 1] = commented

        expressions = list(select.expressions)
        if expression is expressions[-1]:
            previous_index = start_index - 1
            while previous_index >= 0 and not source_lines[previous_index].strip():
                previous_index -= 1
            if previous_index >= 0:
                line = source_lines[previous_index]
                ending = "\n" if line.endswith("\n") else ""
                body = line[:-1] if ending else line
                if body.rstrip().endswith(","):
                    comma = body.rfind(",")
                    source_lines[previous_index] = body[:comma] + body[comma + 1 :] + ending

    result = "".join(source_lines)
    sqlglot.parse_one(mask(result)[0], dialect=dialect)
    return result


def affected_output_columns(sql: str, column: str, *, dialect: str = "snowflake") -> list[str]:
    """Return outer SELECT outputs whose expression consumes ``column``."""

    tree = sqlglot.parse_one(mask(sql)[0], dialect=dialect)
    outputs: list[str] = []
    for select in tree.find_all(exp.Select):
        for expression in select.expressions:
            if any(ref.name.casefold() == column.casefold() for ref in expression.find_all(exp.Column)):
                name = expression.alias_or_name
                if name and name not in outputs:
                    outputs.append(name)
    return outputs


def output_columns(sql: str, *, dialect: str = "snowflake") -> list[str]:
    """Return names projected by the outermost SELECT."""

    tree = sqlglot.parse_one(mask(sql)[0], dialect=dialect)
    select = tree if isinstance(tree, exp.Select) else tree.find(exp.Select)
    if select is None:
        return []
    return [
        expression.alias_or_name for expression in select.expressions if expression.alias_or_name and not expression.is_star
    ]


def _column_nodes(tree: exp.Expression, source: str) -> list[tuple[exp.Column, int, int]]:
    located: list[tuple[exp.Column, int, int]] = []
    for column in tree.find_all(exp.Column):
        identifiers = [part for part in column.parts if isinstance(part, exp.Identifier)]
        starts = [part.meta.get("start") for part in identifiers if isinstance(part.meta.get("start"), int)]
        ends = [part.meta.get("end") for part in identifiers if isinstance(part.meta.get("end"), int)]
        if not starts or not ends:
            continue
        start, end = min(starts), max(ends) + 1
        if 0 <= start < end <= len(source):
            located.append((column, start, end))
    return located


def _select_entry(node: exp.Expression) -> tuple[exp.Select | None, exp.Expression | None]:
    current = node
    while current.parent is not None:
        parent = current.parent
        if isinstance(parent, exp.Select) and current in parent.expressions:
            return parent, current
        current = parent
    return None, None


def _match_identifier_case(original: str, replacement: str) -> str:
    if original.isupper():
        return replacement.upper()
    if original.islower():
        return replacement.lower()
    return replacement
