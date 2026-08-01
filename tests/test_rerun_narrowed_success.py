"""Re-running a repair must ANSWER, not refuse.

Ruling being locked down: after a successful repair the downstream models correctly carry
healthy fine-grained lineage for the NEW column and none for the old one. The lineage index
and the aspect store then AGREE that the drifted column has no consumers left. Agreement is a
genuine answer — the run must succeed with a narrowed result ("less to do"), which is what the
README promises. Refusal is reserved for the case where aspects and index DISAGREE.

Covers all three drift types, at both layers: the engine (does it raise?) and the runner
(does a zero-patch run count as success?).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from repair_agent.agent.runner import _completed_stages
from repair_agent.impact.engine import ImpactEngine, LineageUnavailable
from repair_agent.models import (
    DriftEvent,
    DriftKind,
    ImpactReport,
    LineageGraph,
    RepairRun,
)

RAW_ORDERS = "urn:li:dataset:(urn:li:dataPlatform:snowflake,shop_prod.raw.orders,PROD)"
RAW_CUSTOMERS = "urn:li:dataset:(urn:li:dataPlatform:snowflake,shop_prod.raw.customers,PROD)"
STG_ORDERS = "urn:li:dataset:(urn:li:dataPlatform:dbt,shop_prod.analytics.stg_orders,PROD)"

# (id, kind, dataset, dataset_name, old_column, new_column)
DRIFT_CASES = [
    (
        "rename-orders-order_placed_at",
        DriftKind.RENAME,
        RAW_ORDERS,
        "shop_prod.raw.orders",
        "order_placed_at",
        "order_created_at",
    ),
    ("retype-orders-gross_amount", DriftKind.RETYPE, RAW_ORDERS, "shop_prod.raw.orders", "gross_amount", "gross_amount"),
    ("drop-customers-marketing_opt_in", DriftKind.DROP, RAW_CUSTOMERS, "shop_prod.raw.customers", "marketing_opt_in", None),
]
CASE_IDS = [case[1].value for case in DRIFT_CASES]


def _drift(case: tuple) -> DriftEvent:
    drift_id, kind, urn, name, old, new = case
    return DriftEvent(
        id=drift_id,
        kind=kind,
        dataset_urn=urn,
        dataset_name=name,
        old_column=old,
        new_column=new,
        old_type="TIMESTAMP_NTZ",
        new_type="TIMESTAMP_NTZ",
        confidence=0.95,
        rationale="test",
        detected_at=datetime.now(),
    )


def _engine(*, declared_for_old: set[str], declared_for_new: set[str], any_edge: bool) -> ImpactEngine:
    """An engine whose lineage SEARCH is empty, with a configurable aspect oracle."""

    engine = ImpactEngine.__new__(ImpactEngine)
    engine.LINEAGE_SETTLE_ATTEMPTS = 1
    engine.LINEAGE_SETTLE_SECONDS = 0.0

    def declared(drift: DriftEvent, column: str | None = None) -> set[str]:
        if column is not None and column != drift.old_column:
            return declared_for_new
        return declared_for_old

    engine._aspect_declared_downstreams = declared  # type: ignore[method-assign]
    engine._aspect_declares_any_edge_from = lambda urn: any_edge  # type: ignore[method-assign]
    engine.datahub_io = type(
        "IO",
        (),
        {
            "column_impact": lambda *a, **k: [],
            # Table-level downstreams still exist after a repair — the dataset is still
            # consumed, just not through the old column name.
            "table_downstreams": lambda *a, **k: [object(), object()],
        },
    )()
    return engine


@pytest.mark.parametrize("case", DRIFT_CASES, ids=CASE_IDS)
def test_second_run_answers_instead_of_refusing(case: tuple) -> None:
    """Aspects agree the old column has no consumers left -> answer, do not raise."""

    drift = _drift(case)
    engine = _engine(
        declared_for_old=set(),
        # For RENAME the successor now carries the edges; for DROP there is no successor.
        declared_for_new={STG_ORDERS} if drift.new_column and drift.new_column != drift.old_column else set(),
        any_edge=True,
    )

    column_hits, table_hits = engine._lineage_with_index_settling(drift)

    assert column_hits == [], "a repaired-away column has no remaining column-level consumers"
    assert len(table_hits) == 2, "the dataset itself is still consumed; only the column changed"


@pytest.mark.parametrize("case", DRIFT_CASES, ids=CASE_IDS)
def test_second_run_still_refuses_when_index_and_aspects_disagree(case: tuple) -> None:
    """The guard must keep firing on genuine index breakage, for every drift type."""

    drift = _drift(case)
    engine = _engine(declared_for_old={STG_ORDERS}, declared_for_new=set(), any_edge=True)

    with pytest.raises(LineageUnavailable) as excinfo:
        engine._lineage_with_index_settling(drift)
    assert "stg_orders" in str(excinfo.value)


@pytest.mark.parametrize("case", DRIFT_CASES, ids=CASE_IDS)
def test_zero_patch_rerun_is_a_success_not_a_failure(case: tuple) -> None:
    """A completed impact stage requiring nothing is a narrowed success, not a failed run."""

    drift = _drift(case)
    impact = ImpactReport(
        drift=drift,
        assets=[],
        graph=LineageGraph(nodes=[], edges=[]),
        stats={"requires_patch": 0, "downstream_unaffected": 0, "skipped": 12, "total_scanned": 12},
    )
    run = RepairRun(id="rerun", status="succeeded", drift=drift, impact=impact, patches=[])

    stages = _completed_stages(run)
    assert stages == ["detect", "impact", "codegen", "validate", "pr"], (
        "codegen and validation genuinely ran and had no work; they must not read as skipped"
    )
