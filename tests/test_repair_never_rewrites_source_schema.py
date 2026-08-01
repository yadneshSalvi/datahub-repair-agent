"""A repair must never rewrite the drifted dataset's own schema.

Motivating report: after a DROP repair, `raw.customers.marketing_opt_in` was observed back in
the catalog, the fine-grained edge through it restored, and the drift no longer detectable.
That would invert the DROP story entirely — the pitch is an explicit deprecation path, and a
catalog that quietly re-asserts the dropped column is worse than doing nothing.

Investigation showed the write-back layer does not emit `schemaMetadata` at all (the observation
came from a concurrently-running reset on the shared demo catalog, not from this code). These
tests pin that invariant so a future change cannot reintroduce it, and lock the no-op shape a
second DROP run must produce.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "repair_agent"

#: Aspects that describe the dataset's own structure. A repair writes ABOUT a dataset
#: (documentation, tags, lineage, incidents) but must never redefine WHAT it is.
STRUCTURAL_ASPECTS = {"SchemaMetadataClass", "DatasetPropertiesClass", "SubTypesClass"}


def _names_used(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }


class TestWritebackNeverTouchesSourceSchema:
    def test_writeback_module_does_not_reference_structural_aspects(self) -> None:
        """The whole point: repairing code must not redefine the upstream table."""

        used = _names_used(SRC / "datahub_io" / "writeback.py")
        offenders = sorted(STRUCTURAL_ASPECTS & used)
        assert not offenders, (
            f"write-back references {offenders}. Emitting a structural aspect from the repair "
            "path can restore a dropped column or overwrite a renamed one, silently undoing the "
            "drift the agent was asked to repair."
        )

    def test_no_runtime_module_emits_schema_metadata(self) -> None:
        """Only the seed and the drift simulator may define schemas; runtime code may not."""

        offenders = []
        for path in sorted(SRC.rglob("*.py")):
            if "SchemaMetadataClass" in _names_used(path):
                offenders.append(str(path.relative_to(SRC)))
        assert not offenders, (
            f"{offenders} emit SchemaMetadataClass at runtime. Schema definition belongs to "
            "scripts/seed_datahub.py and scripts/simulate_drift.py only."
        )


class TestSecondDropRunIsANoOp:
    """Run 2 of a DROP repair must be a clean no-op, not a refusal and not more patches."""

    def test_zero_patch_run_shape(self) -> None:
        from repair_agent.agent.runner import _completed_stages
        from repair_agent.models import (
            DriftEvent,
            DriftKind,
            ImpactReport,
            LineageGraph,
            PullRequestResult,
            RepairRun,
        )

        drift = DriftEvent(
            id="drop-customers-marketing_opt_in",
            kind=DriftKind.DROP,
            dataset_urn="urn:li:dataset:(urn:li:dataPlatform:snowflake,shop_prod.raw.customers,PROD)",
            dataset_name="shop_prod.raw.customers",
            old_column="marketing_opt_in",
            new_column=None,
            old_type="BOOLEAN",
            new_type=None,
            confidence=1.0,
            rationale="test",
        )
        # The live matrix produces exactly this on run 2: 0 / 0 / 12.
        impact = ImpactReport(
            drift=drift,
            assets=[],
            graph=LineageGraph(nodes=[], edges=[]),
            stats={"requires_patch": 0, "downstream_unaffected": 0, "skipped": 12, "total_scanned": 12},
        )
        run = RepairRun(
            id="rerun",
            status="succeeded",
            drift=drift,
            impact=impact,
            patches=[],
            pr=PullRequestResult(
                mode="dry-run",
                url="",
                branch="repair/drop-customers-marketing_opt_in",
                title="No changes required — no PR opened",
                ok=True,
                state="no_changes_required",
            ),
        )

        assert run.status == "succeeded"
        assert run.pr is not None and run.pr.state == "no_changes_required"
        assert run.pr.ok is True and run.pr.error is None
        assert _completed_stages(run) == ["detect", "impact", "codegen", "validate", "pr"]
