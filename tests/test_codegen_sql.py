"""Exact-reference and surgical source-edit guarantees."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import sqlglot

from repair_agent.codegen.airflow_ops import rename_column as rename_airflow_column
from repair_agent.codegen.jinja import mask, unmask
from repair_agent.codegen.sql_ops import find_column_references, rename_column

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_order_placed_at_utc_is_not_a_false_positive() -> None:
    sql = "select order_placed_at_utc, order_placed_at from shop_prod.raw.orders\n"
    matches = [reference for reference in find_column_references(sql) if reference.name == "order_placed_at"]
    assert len(matches) == 1
    repaired = rename_column(sql, "order_placed_at", "order_created_at")
    assert repaired == "select order_placed_at_utc, order_created_at from shop_prod.raw.orders\n"


def test_jinja_mask_unmask_is_byte_identical_for_every_demo_model() -> None:
    tags = re.compile(r"\{\{.*?\}\}", re.DOTALL)
    for path in sorted((REPO_ROOT / "demo-warehouse" / "models").glob("**/*.sql")):
        source = path.read_text(encoding="utf-8")
        masked, mapping = mask(source)
        assert unmask(masked, mapping) == source
        generated = sqlglot.parse_one(masked, dialect="snowflake").sql(dialect="snowflake", pretty=True)
        restored = unmask(generated, mapping)
        assert tags.findall(restored) == tags.findall(source), path
        sqlglot.parse_one(mask(restored)[0], dialect="snowflake")


def test_stg_orders_rename_changes_only_the_target_line() -> None:
    path = REPO_ROOT / "demo-warehouse" / "models" / "staging" / "stg_orders.sql"
    before = path.read_text(encoding="utf-8")
    after = rename_column(before, "order_placed_at", "order_created_at")
    changed = [(old, new) for old, new in zip(before.splitlines(), after.splitlines(), strict=True) if old != new]
    assert changed == [("    order_placed_at,", "    order_created_at,")]


def test_airflow_rewrite_preserves_python_and_triple_quotes() -> None:
    path = REPO_ROOT / "demo-warehouse" / "dags" / "shopflow_daily.py"
    before = path.read_text(encoding="utf-8")
    after = rename_airflow_column(before, ["RECENT_ORDERS_SQL"], "order_placed_at", "order_created_at")
    ast.parse(after)
    assert 'RECENT_ORDERS_SQL = """' in after
    assert "PRODUCT_CATALOG_SQL" in after
    assert after.count("order_created_at") == 2
