"""Rename inference and explicit drift normalization tests."""

from __future__ import annotations

from repair_agent.drift.detect import declare_drift, detect_drift
from repair_agent.drift.snapshot import SchemaSnapshot
from repair_agent.models import ColumnSpec, DriftKind

URN = "urn:li:dataset:(urn:li:dataPlatform:snowflake,shop_prod.raw.orders,PROD)"


def _column(name: str, native_type: str = "TIMESTAMP_NTZ") -> ColumnSpec:
    return ColumnSpec(name=name, native_type=native_type, data_type="time")


def _snapshot(columns: list[ColumnSpec]) -> SchemaSnapshot:
    return SchemaSnapshot({URN: {column.name: column for column in columns}})


def test_clean_rename_uses_same_type_fast_path() -> None:
    events = detect_drift(
        _snapshot([_column("id", "NUMBER"), _column("order_placed_at")]),
        _snapshot([_column("id", "NUMBER"), _column("order_created_at")]),
    )
    assert len(events) == 1
    event = events[0]
    assert event.kind is DriftKind.RENAME
    assert event.confidence == 0.95
    assert "same ordinal position (2)" in event.rationale
    assert event.id == "rename-orders-order_placed_at"


def test_rename_plus_unrelated_add_pairs_greedily() -> None:
    events = detect_drift(
        _snapshot([_column("id", "NUMBER"), _column("placed_at")]),
        _snapshot([_column("id", "NUMBER"), _column("created_at"), _column("new_flag", "BOOLEAN")]),
    )
    assert [(event.kind, event.old_column, event.new_column) for event in events] == [
        (DriftKind.ADD, None, "new_flag"),
        (DriftKind.RENAME, "placed_at", "created_at"),
    ]
    assert next(event for event in events if event.kind is DriftKind.RENAME).confidence <= 0.9


def test_retype_is_detected_without_add_or_drop() -> None:
    events = detect_drift(
        _snapshot([_column("gross_amount", "NUMBER(12,2)")]), _snapshot([_column("gross_amount", "VARCHAR(20)")])
    )
    assert len(events) == 1
    assert events[0].kind is DriftKind.RETYPE
    assert events[0].old_type == "NUMBER(12,2)"
    assert events[0].new_type == "VARCHAR(20)"


def test_drop_with_no_candidate_stays_a_drop() -> None:
    events = detect_drift(_snapshot([_column("marketing_opt_in", "BOOLEAN")]), _snapshot([]))
    assert len(events) == 1
    assert events[0].kind is DriftKind.DROP
    assert "no added column met" in events[0].rationale


def test_ambiguous_two_removed_two_added_pairs_deterministically() -> None:
    events = detect_drift(
        _snapshot([_column("customer_email", "VARCHAR"), _column("billing_zip", "VARCHAR")]),
        _snapshot([_column("customer_mail", "VARCHAR"), _column("billing_postcode", "VARCHAR")]),
    )
    renames = {(event.old_column, event.new_column) for event in events if event.kind is DriftKind.RENAME}
    assert renames == {("customer_email", "customer_mail"), ("billing_zip", "billing_postcode")}
    assert all(event.confidence <= 0.9 for event in events)


def test_no_drift_returns_empty_list() -> None:
    snapshot = _snapshot([_column("id", "NUMBER"), _column("placed_at")])
    assert detect_drift(snapshot, snapshot) == []


def test_explicit_declaration_produces_the_same_domain_model() -> None:
    event = declare_drift(
        kind="DROP",
        dataset_urn=URN,
        old_column="legacy",
        old_type="VARCHAR",
    )
    assert event.kind is DriftKind.DROP
    assert event.id == "drop-orders-legacy"
    assert "explicit declaration" in event.rationale
