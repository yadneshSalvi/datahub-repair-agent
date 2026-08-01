"""A failed repair run must be loudly, unmistakably failed.

The bug these tests lock down: a run whose lineage read came back empty classified every
asset as SKIPPED, produced zero patches, and still rendered as a plausible success — green
stage ticks and a "12 correctly skipped" headline. Reporting "nothing is affected" when the
truth is "we could not tell" is the most dangerous thing this tool can do.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from repair_agent.agent.runner import _completed_stages
from repair_agent.models import (
    DriftEvent,
    DriftKind,
    ImpactReport,
    LineageGraph,
    Patch,
    PullRequestResult,
    ReferenceCheck,
    RepairRun,
)


def _drift() -> DriftEvent:
    return DriftEvent(
        id="rename-orders-order_placed_at",
        kind=DriftKind.RENAME,
        dataset_urn="urn:li:dataset:(urn:li:dataPlatform:snowflake,shop_prod.raw.orders,PROD)",
        dataset_name="shop_prod.raw.orders",
        old_column="order_placed_at",
        new_column="order_created_at",
        old_type="TIMESTAMP_NTZ",
        new_type="TIMESTAMP_NTZ",
        confidence=0.95,
        rationale="test",
        detected_at=datetime.now(),
    )


def _patch(*, valid: bool) -> Patch:
    return Patch(
        asset_urn="urn:li:dataset:(urn:li:dataPlatform:dbt,shop_prod.analytics.stg_orders,PROD)",
        file_path="demo-warehouse/models/staging/stg_orders.sql",
        before="select 1",
        after="select 2",
        unified_diff="",
        kind="dbt_sql",
        references=[
            ReferenceCheck(
                table="shop_prod.raw.orders",
                column="order_created_at",
                status="OK" if valid else "UNKNOWN_COLUMN",
                detail="test",
                source="live_catalog",
            )
        ],
        valid=valid,
        strategy="test",
    )


def _empty_impact() -> ImpactReport:
    return ImpactReport(
        drift=_drift(),
        assets=[],
        graph=LineageGraph(nodes=[], edges=[]),
        stats={"requires_patch": 0, "downstream_unaffected": 0, "skipped": 12, "total_scanned": 12},
    )


class TestCompletedStages:
    """Stage ticks come from real artifacts, never from how far the run got."""

    def test_impact_never_produced_ticks_only_detect(self) -> None:
        """No impact report means the blast radius was never established."""

        run = RepairRun(id="r", status="failed", drift=_drift(), impact=None)
        stages = _completed_stages(run)
        assert stages == ["detect"]
        # This is the exact regression: the failed QA run showed green checks on all three.
        for never in ("codegen", "validate", "pr", "writeback"):
            assert never not in stages

    def test_work_required_but_no_patches_does_not_tick_codegen(self) -> None:
        """Impact says 3 files need patching but none were produced — codegen really failed."""

        impact = _empty_impact()
        impact.stats["requires_patch"] = 3
        run = RepairRun(id="r", status="failed", drift=_drift(), impact=impact)
        stages = _completed_stages(run)
        assert stages == ["detect", "impact"]
        for never in ("codegen", "validate", "pr"):
            assert never not in stages

    def test_nothing_to_repair_ticks_through_pr(self) -> None:
        """Zero patches with zero required is a real, complete answer, not a half-run."""

        run = RepairRun(id="r", status="succeeded", drift=_drift(), impact=_empty_impact())
        stages = _completed_stages(run)
        assert stages == ["detect", "impact", "codegen", "validate", "pr"]

    def test_invalid_patch_ticks_codegen_but_not_validate(self) -> None:
        run = RepairRun(id="r", status="failed", drift=_drift(), impact=_empty_impact(), patches=[_patch(valid=False)])
        stages = _completed_stages(run)
        assert "codegen" in stages
        assert "validate" not in stages

    def test_failed_pr_does_not_tick_pr(self) -> None:
        run = RepairRun(
            id="r",
            status="failed",
            drift=_drift(),
            impact=_empty_impact(),
            patches=[_patch(valid=True)],
            pr=PullRequestResult(mode="live", url="", branch="b", title="t", ok=False, error="boom"),
        )
        stages = _completed_stages(run)
        assert "validate" in stages
        assert "pr" not in stages


class TestLineageUnavailable:
    """An unreadable blast radius must raise, not quietly return "nothing affected"."""

    def test_empty_column_lineage_with_declared_downstreams_raises(self) -> None:
        from repair_agent.impact.engine import ImpactEngine, LineageUnavailable

        engine = ImpactEngine.__new__(ImpactEngine)
        engine.LINEAGE_SETTLE_ATTEMPTS = 1
        engine.LINEAGE_SETTLE_SECONDS = 0.0
        downstream = "urn:li:dataset:(urn:li:dataPlatform:dbt,shop_prod.analytics.stg_orders,PROD)"
        engine._aspect_declared_downstreams = lambda drift, column=None: {downstream}  # type: ignore[method-assign]
        engine.datahub_io = type(
            "IO", (), {"column_impact": lambda *a, **k: [], "table_downstreams": lambda *a, **k: []}
        )()

        with pytest.raises(LineageUnavailable) as excinfo:
            engine._lineage_with_index_settling(_drift())
        message = str(excinfo.value)
        assert "stg_orders" in message
        assert "Refusing" in message

    def test_unseeded_catalog_raises_rather_than_reporting_no_impact(self) -> None:
        from repair_agent.impact.engine import ImpactEngine, LineageUnavailable

        engine = ImpactEngine.__new__(ImpactEngine)
        engine.LINEAGE_SETTLE_ATTEMPTS = 1
        engine.LINEAGE_SETTLE_SECONDS = 0.0
        engine._aspect_declared_downstreams = lambda drift, column=None: set()  # type: ignore[method-assign]
        engine._aspect_declares_any_edge_from = lambda urn: False  # type: ignore[method-assign]
        engine.datahub_io = type(
            "IO", (), {"column_impact": lambda *a, **k: [], "table_downstreams": lambda *a, **k: []}
        )()

        with pytest.raises(LineageUnavailable) as excinfo:
            engine._lineage_with_index_settling(_drift())
        assert "unseeded" in str(excinfo.value)

    def test_repaired_away_column_returns_empty_instead_of_refusing(self) -> None:
        """The documented re-run must succeed with less to do, not hard-fail.

        Regression: after a successful repair the downstream models correctly carry healthy
        edges for the NEW column and none for the old one. The guard read that as
        "downstreams exist but the column has no lineage" and refused — but aspects and index
        were AGREEING. Refusal is only correct when they disagree.
        """

        from repair_agent.impact.engine import ImpactEngine

        engine = ImpactEngine.__new__(ImpactEngine)
        engine.LINEAGE_SETTLE_ATTEMPTS = 1
        engine.LINEAGE_SETTLE_SECONDS = 0.0
        successor_consumers = {"urn:li:dataset:(urn:li:dataPlatform:dbt,shop_prod.analytics.stg_orders,PROD)"}

        def declared(drift: DriftEvent, column: str | None = None) -> set[str]:
            # Nothing consumes the old name any more; the new name is consumed normally.
            return successor_consumers if column == drift.new_column else set()

        engine._aspect_declared_downstreams = declared  # type: ignore[method-assign]
        engine._aspect_declares_any_edge_from = lambda urn: True  # type: ignore[method-assign]
        engine.datahub_io = type(
            "IO",
            (),
            {
                "column_impact": lambda *a, **k: [],
                # Table-level downstreams still exist — this is exactly the shape that used
                # to trip the old "those answers cannot both be true" branch.
                "table_downstreams": lambda *a, **k: [object()],
            },
        )()

        column_hits, table_hits = engine._lineage_with_index_settling(_drift())
        assert column_hits == []
        assert len(table_hits) == 1

    def test_genuinely_unused_column_is_allowed_to_return_empty(self) -> None:
        """A column with no declared downstreams legitimately has no blast radius."""

        from repair_agent.impact.engine import ImpactEngine

        engine = ImpactEngine.__new__(ImpactEngine)
        engine.LINEAGE_SETTLE_ATTEMPTS = 1
        engine.LINEAGE_SETTLE_SECONDS = 0.0
        engine._aspect_declared_downstreams = lambda drift, column=None: set()  # type: ignore[method-assign]
        engine._aspect_declares_any_edge_from = lambda urn: True  # type: ignore[method-assign]
        engine.datahub_io = type(
            "IO", (), {"column_impact": lambda *a, **k: [], "table_downstreams": lambda *a, **k: []}
        )()

        column_hits, table_hits = engine._lineage_with_index_settling(_drift())
        assert column_hits == []
        assert table_hits == []
