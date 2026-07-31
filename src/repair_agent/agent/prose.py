"""LLM-owned prose with deterministic, judge-ready Jinja fallbacks."""

from __future__ import annotations

import logging
from collections.abc import Callable

from agents import Agent, Runner
from jinja2 import Environment, StrictUndefined
from pydantic import BaseModel, Field

from repair_agent.config import Settings
from repair_agent.models import DriftEvent, ImpactReport, RepairRun

LOGGER = logging.getLogger(__name__)


class PRNarrative(BaseModel):
    """Structured prose used to title and frame a pull request."""

    title: str
    summary: str
    risk_note: str
    reviewer_checklist: list[str] = Field(default_factory=list)


class MigrationDoc(BaseModel):
    """Structured migration documentation attached to DataHub."""

    title: str
    markdown: str


class ColumnDoc(BaseModel):
    """Concise catalog documentation for repaired fields."""

    text: str


PR_FALLBACK = "Repair {{ dataset }}: {{ old or '∅' }} → {{ new or '∅' }}"
SUMMARY_FALLBACK = (
    "The upstream {{ kind|lower }} was traced through DataHub column lineage. The deterministic engine generated "
    "{{ patch_count }} surgical patch(es), while {{ unaffected }} downstream model(s) were proven insulated and "
    "{{ skipped }} asset(s) were skipped with explicit evidence."
)
RISK_FALLBACK = (
    "Risk is bounded by the validator hard gate: {{ resolved }}/{{ total }} generated references resolved and no "
    "unresolved column is allowed into the PR. Review the lineage-derived skip reasons and deploy dbt models before "
    "dependent Airflow jobs."
)
MIGRATION_FALLBACK = """# {{ title }}

## Change

{{ rationale }}

The repair changes `{{ old or '∅' }}` to `{{ new or '∅' }}` for `{{ dataset }}`.
Code was produced only by deterministic sqlglot/dbt/Airflow transforms; language-model
output is prose-only.

## Blast radius

- **{{ requires_patch }}** code-bearing asset(s) require a patch.
- **{{ unaffected }}** downstream asset(s) are insulated by existing aliases and need review only.
- **{{ skipped }}** asset(s) were correctly skipped because DataHub exposes no changed-column path.

## Validation and rollout

All {{ total }} generated SQL reference(s) were checked before review; {{ resolved }} resolved.
Apply the dbt changes before dependent Airflow code, run the declared dbt tests, and
monitor the DataHub incident until consumers are healthy.

## Rollback

Revert the PR commit and restore the upstream field contract. Then re-run the repair agent
so DataHub lineage and documentation match the restored schema.
"""
COLUMN_FALLBACK = (
    "{{ change }} by Schema-Drift Auto-Repair Agent in run {{ run_id }} — see {{ pr_url }}. "
    "Validated against live DataHub schema metadata before review."
)


async def generate_pr_narrative(
    run: RepairRun,
    settings: Settings,
    *,
    model: str,
    use_llm: bool,
    on_degradation: Callable[[str], None] | None = None,
) -> PRNarrative:
    """Generate PR prose without exposing Patch.after as an editable output."""

    fallback = fallback_pr_narrative(run)
    if not use_llm:
        return fallback
    agent = Agent(
        name="RepairPRNarrativeWriter",
        model=model,
        instructions=(
            "Write concise reviewer-facing prose for a schema-drift repair. Use only facts in the input. "
            "Never invent a column, asset, validation result, or code change. You produce prose only and cannot "
            "alter patches."
        ),
        output_type=PRNarrative,
    )
    try:
        result = await Runner.run(agent, _prose_context(run), max_turns=4)
        return result.final_output
    except Exception as exc:
        _degrade(on_degradation, f"PR prose generation failed; used the deterministic Jinja narrative: {exc}")
        return fallback


async def generate_migration_doc(
    run: RepairRun,
    settings: Settings,
    *,
    model: str,
    use_llm: bool,
    on_degradation: Callable[[str], None] | None = None,
) -> MigrationDoc:
    """Generate migration prose, or a complete deterministic operational note."""

    del settings
    fallback = fallback_migration_doc(run)
    if not use_llm:
        return fallback
    agent = Agent(
        name="RepairMigrationDocWriter",
        model=model,
        instructions=(
            "Write an operational migration document from the supplied repair facts. Include rollout, validation, "
            "monitoring, and rollback. Never propose code or invent columns; deterministic patches are immutable."
        ),
        output_type=MigrationDoc,
    )
    try:
        result = await Runner.run(agent, _prose_context(run), max_turns=4)
        return result.final_output
    except Exception as exc:
        _degrade(on_degradation, f"Migration prose generation failed; used the deterministic Jinja document: {exc}")
        return fallback


async def generate_column_doc(
    run: RepairRun,
    settings: Settings,
    *,
    model: str,
    use_llm: bool,
    pr_url: str,
    on_degradation: Callable[[str], None] | None = None,
) -> ColumnDoc:
    """Generate one factual catalog description for the repaired lineage path."""

    del settings
    fallback = fallback_column_doc(run, pr_url)
    if not use_llm:
        return fallback
    agent = Agent(
        name="RepairColumnDocWriter",
        model=model,
        instructions=(
            "Write one concise DataHub column description from the supplied repair facts. Mention provenance and PR. "
            "Do not invent a column, semantic meaning, owner, or code change."
        ),
        output_type=ColumnDoc,
    )
    try:
        result = await Runner.run(agent, f"{_prose_context(run)}\nPR URL: {pr_url}", max_turns=4)
        return result.final_output
    except Exception as exc:
        _degrade(on_degradation, f"Column prose generation failed; used deterministic Jinja documentation: {exc}")
        return fallback


def fallback_pr_narrative(run: RepairRun) -> PRNarrative:
    """Render a high-quality deterministic PR narrative."""

    drift, impact = _required(run)
    references = [reference for patch in run.patches for reference in patch.references]
    values = {
        "dataset": drift.dataset_name,
        "old": drift.old_column,
        "new": drift.new_column,
        "kind": drift.kind.value,
        "patch_count": len(run.patches),
        "unaffected": impact.stats.get("downstream_unaffected", 0),
        "skipped": impact.stats.get("skipped", 0),
        "resolved": sum(reference.status == "OK" for reference in references),
        "total": len(references),
    }
    return PRNarrative(
        title=_render(PR_FALLBACK, values),
        summary=_render(SUMMARY_FALLBACK, values),
        risk_note=_render(RISK_FALLBACK, values),
        reviewer_checklist=[
            "Confirm the upstream rename and rollout order with the source owner.",
            "Review every downstream-unaffected and correctly-skipped reason against the lineage graph.",
            "Run the dbt tests and dependent Airflow task in staging before production deployment.",
            "Verify the DataHub incident, field documentation, tags, and corrected column lineage after merge.",
        ],
    )


def fallback_migration_doc(run: RepairRun) -> MigrationDoc:
    """Render a deterministic migration guide with rollout and rollback guidance."""

    drift, impact = _required(run)
    references = [reference for patch in run.patches for reference in patch.references]
    title = f"Migration: {drift.dataset_name}.{drift.old_column or drift.new_column}"
    markdown = _render(
        MIGRATION_FALLBACK,
        {
            "title": title,
            "rationale": drift.rationale,
            "dataset": drift.dataset_name,
            "old": drift.old_column,
            "new": drift.new_column,
            "requires_patch": impact.stats.get("requires_patch", 0),
            "unaffected": impact.stats.get("downstream_unaffected", 0),
            "skipped": impact.stats.get("skipped", 0),
            "resolved": sum(reference.status == "OK" for reference in references),
            "total": len(references),
        },
    )
    return MigrationDoc(title=title, markdown=markdown.rstrip() + "\n")


def fallback_column_doc(run: RepairRun, pr_url: str) -> ColumnDoc:
    """Render deterministic column provenance documentation."""

    drift, _ = _required(run)
    if drift.kind.value == "RENAME":
        change = f"Renamed from `{drift.old_column}` to `{drift.new_column}`"
    elif drift.kind.value == "RETYPE":
        change = f"Retyped from `{drift.old_type}` to `{drift.new_type}`"
    else:
        change = f"Deprecated after upstream `{drift.old_column}` was dropped"
    return ColumnDoc(text=_render(COLUMN_FALLBACK, {"change": change, "run_id": run.id, "pr_url": pr_url}))


def _required(run: RepairRun) -> tuple[DriftEvent, ImpactReport]:
    if run.drift is None or run.impact is None:
        raise RuntimeError("Prose generation requires detected drift and impact results.")
    return run.drift, run.impact


def _prose_context(run: RepairRun) -> str:
    drift, impact = _required(run)
    assets = "\n".join(f"- {asset.bucket.value}: {asset.name} — {asset.reason}" for asset in impact.assets)
    patches = "\n".join(f"- {patch.file_path}: {patch.strategy}" for patch in run.patches)
    references = [reference for patch in run.patches for reference in patch.references]
    return (
        f"Run: {run.id}\nDrift: {drift.kind.value} {drift.dataset_name}.{drift.old_column} -> "
        f"{drift.new_column}\nRationale: {drift.rationale}\nImpact:\n{assets}\nPatches:\n{patches}\n"
        f"Validation: {sum(reference.status == 'OK' for reference in references)}/{len(references)} resolved."
    )


def _render(template: str, values: dict[str, object]) -> str:
    environment = Environment(undefined=StrictUndefined, autoescape=False)
    return environment.from_string(template).render(**values).strip()


def _degrade(callback: Callable[[str], None] | None, reason: str) -> None:
    LOGGER.warning(reason)
    if callback is not None:
        callback(reason)
