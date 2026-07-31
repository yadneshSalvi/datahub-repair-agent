"""Byte-identical masking for dbt Jinja expressions embedded in SQL."""

from __future__ import annotations

import re

JINJA_EXPRESSION = re.compile(r"\{\{.*?\}\}", re.DOTALL)


def mask(sql: str) -> tuple[str, dict[str, str]]:
    """Replace every Jinja expression with a unique valid SQL identifier."""

    mapping: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        token = f"__JINJA_{len(mapping)}__"
        mapping[token] = match.group(0)
        return token

    return JINJA_EXPRESSION.sub(replace, sql), mapping


def unmask(sql: str, mapping: dict[str, str]) -> str:
    """Restore all masked Jinja expressions byte-for-byte."""

    restored = sql
    for token, original in mapping.items():
        restored = restored.replace(token, original)
    return restored
