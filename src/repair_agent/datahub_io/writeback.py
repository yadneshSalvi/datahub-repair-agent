"""Best-effort DataHub governance write-back surface."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse

from datahub.api.entities.dataprocess.dataprocess_instance import DataProcessInstance, InstanceRunResult
from datahub.emitter.mce_builder import datahub_guid, make_schema_field_urn, make_tag_urn, make_user_urn
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DataHubRestEmitter
from datahub.metadata.schema_classes import (
    AuditStampClass,
    DatasetLineageTypeClass,
    EditableSchemaFieldInfoClass,
    EditableSchemaMetadataClass,
    FineGrainedLineageClass,
    FineGrainedLineageDownstreamTypeClass,
    FineGrainedLineageUpstreamTypeClass,
    GlobalTagsClass,
    IncidentInfoClass,
    IncidentSourceClass,
    IncidentSourceTypeClass,
    IncidentStageClass,
    IncidentStateClass,
    IncidentStatusClass,
    IncidentTypeClass,
    InstitutionalMemoryClass,
    InstitutionalMemoryMetadataClass,
    TagAssociationClass,
    TagPropertiesClass,
    UpstreamClass,
)
from datahub.metadata.urns import DatasetUrn, IncidentUrn
from datahub.specific.dataset import DatasetPatchBuilder

from repair_agent.config import Settings, get_settings
from repair_agent.datahub_io.client import DataHubIO
from repair_agent.datahub_io.links import datahub_entity_url
from repair_agent.models import DriftEvent, FglEdge, WritebackAction

_DATASET_INCIDENTS_QUERY = """
query RepairIncidents($urn: String!) {
  dataset(urn: $urn) {
    incidents(start: 0, count: 100) { incidents { urn title } }
  }
}
"""
_UPDATE_INCIDENT_STATUS = """
mutation UpdateRepairIncident($urn: String!, $input: IncidentStatusInput!) {
  updateIncidentStatus(urn: $urn, input: $input)
}
"""


class DataHubWriteback:
    """Governance write-backs that convert every exception into an action result."""

    def __init__(
        self,
        datahub_io: DataHubIO | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.datahub_io = datahub_io or DataHubIO(self.settings)
        self.graph = self.datahub_io.graph

    def ensure_tag_exists(self, name: str, description: str) -> WritebackAction:
        """Create a governance tag entity when it does not already exist."""

        tag_urn = make_tag_urn(name)
        try:
            if not self.graph.exists(tag_urn):
                self.graph.emit_mcp(
                    MetadataChangeProposalWrapper(
                        entityUrn=tag_urn,
                        aspect=TagPropertiesClass(name=name, description=description),
                    )
                )
            return self._action(
                kind="ensure_tag_exists",
                target_urn=tag_urn,
                detail=f"Governance tag '{name}' is available.",
            )
        except Exception as exc:  # DataHub errors vary by transport and server version.
            return self._action(
                kind="ensure_tag_exists",
                target_urn=tag_urn,
                detail=f"Could not ensure governance tag '{name}'.",
                error=exc,
            )

    def document_column(
        self,
        dataset_urn: str,
        column: str,
        description: str,
    ) -> WritebackAction:
        """Set a column description while preserving all existing editable field metadata."""

        try:
            existing = self.graph.get_aspect(dataset_urn, EditableSchemaMetadataClass)
            field_info = deepcopy(existing.editableSchemaFieldInfo) if existing else []
            target = next((field for field in field_info if field.fieldPath == column), None)
            if target is None:
                field_info.append(EditableSchemaFieldInfoClass(fieldPath=column, description=description))
            else:
                target.description = description

            now = int(datetime.now().timestamp() * 1000)
            stamp = AuditStampClass(time=now, actor=make_user_urn("datahub-repair-agent"))
            self.graph.emit_mcp(
                MetadataChangeProposalWrapper(
                    entityUrn=dataset_urn,
                    aspect=EditableSchemaMetadataClass(
                        editableSchemaFieldInfo=field_info,
                        created=existing.created if existing else stamp,
                        lastModified=stamp,
                    ),
                )
            )
            return self._action(
                kind="document_column",
                target_urn=dataset_urn,
                detail=f"Documented column '{column}'.",
            )
        except Exception as exc:  # DataHub errors vary by transport and server version.
            return self._action(
                kind="document_column",
                target_urn=dataset_urn,
                detail=f"Could not document column '{column}'.",
                error=exc,
            )

    def update_fine_grained_lineage(
        self,
        dataset_urn: str,
        edges: list[FglEdge],
    ) -> WritebackAction:
        """Replace known field edges with corrected edges using patch proposals."""

        try:
            current = self.datahub_io.fine_grained_lineage(dataset_urn, skip_cache=True)
            builder = DatasetPatchBuilder(dataset_urn)
            for edge in current:
                builder.remove_fine_grained_lineage(self._fine_grained_lineage(edge))
            for upstream_urn in sorted({edge.upstream_urn for edge in edges}):
                builder.add_upstream_lineage(
                    UpstreamClass(dataset=upstream_urn, type=DatasetLineageTypeClass.TRANSFORMED)
                )
            for edge in edges:
                builder.add_fine_grained_lineage(self._fine_grained_lineage(edge))
            proposals = list(builder.build())
            for proposal in proposals:
                self.graph.emit_mcp(proposal)
            return self._action(
                kind="update_fine_grained_lineage",
                target_urn=dataset_urn,
                detail=f"Reconciled {len(edges)} corrected field-lineage edge(s) with patch-style writes.",
                suffix="/Lineage",
            )
        except Exception as exc:  # DataHub errors vary by transport and server version.
            return self._action(
                kind="update_fine_grained_lineage",
                target_urn=dataset_urn,
                detail="Could not update corrected fine-grained lineage.",
                error=exc,
                suffix="/Lineage",
            )

    def tag_assets(
        self,
        source_dataset_urn: str,
        source_column: str,
        patched_dataset_urns: list[str],
    ) -> WritebackAction:
        """Tag the source dataset/field as detected and patched datasets as repaired."""

        detected_tag = "schema-drift-detected"
        repaired_tag = "schema-drift-repaired"
        try:
            ensured = [
                self.ensure_tag_exists(detected_tag, "A schema drift was detected on this asset."),
                self.ensure_tag_exists(repaired_tag, "A schema drift repair passed deterministic validation."),
            ]
            failures = [action.error for action in ensured if not action.ok]
            if failures:
                raise RuntimeError("; ".join(error or "tag creation failed" for error in failures))

            detected = TagAssociationClass(tag=make_tag_urn(detected_tag))
            self._add_dataset_tag(source_dataset_urn, detected)

            existing = self.graph.get_aspect(source_dataset_urn, EditableSchemaMetadataClass)
            field_info = deepcopy(existing.editableSchemaFieldInfo) if existing else []
            target = next((field for field in field_info if field.fieldPath == source_column), None)
            if target is None:
                target = EditableSchemaFieldInfoClass(fieldPath=source_column)
                field_info.append(target)
            associations = list(target.globalTags.tags) if target.globalTags else []
            if detected.tag not in {association.tag for association in associations}:
                associations.append(detected)
            target.globalTags = GlobalTagsClass(tags=associations)
            now = int(datetime.now().timestamp() * 1000)
            stamp = AuditStampClass(time=now, actor=make_user_urn("datahub-repair-agent"))
            self.graph.emit_mcp(
                MetadataChangeProposalWrapper(
                    entityUrn=source_dataset_urn,
                    aspect=EditableSchemaMetadataClass(
                        editableSchemaFieldInfo=field_info,
                        created=existing.created if existing else stamp,
                        lastModified=stamp,
                    ),
                )
            )

            repaired = TagAssociationClass(tag=make_tag_urn(repaired_tag))
            for urn in sorted(set(patched_dataset_urns)):
                self._add_dataset_tag(urn, repaired)
            return self._action(
                kind="tag_assets",
                target_urn=source_dataset_urn,
                detail=(
                    f"Tagged the source dataset and `{source_column}` as detected; tagged "
                    f"{len(set(patched_dataset_urns))} repaired dataset(s)."
                ),
            )
        except Exception as exc:  # DataHub errors vary by transport and server version.
            return self._action(
                kind="tag_assets",
                target_urn=source_dataset_urn,
                detail="Could not apply schema-drift governance tags.",
                error=exc,
            )

    def _add_dataset_tag(self, dataset_urn: str, association: TagAssociationClass) -> None:
        """Idempotently add one dataset-level tag via read-modify-write.

        Deliberately NOT ``DatasetPatchBuilder.add_tag``: that emits a JSON-patch ``add`` at
        ``/globalTags/tags/<tagUrn>``, and when the dataset has no ``globalTags`` aspect yet
        GMS v1.5.0.6 rejects it with
        ``JsonException: The JSON Object '{}' contains no mapping for the name '<tagUrn>'``.
        Reading the aspect and writing the merged value back works on every server version
        and stays idempotent, which matters because repair runs are re-run constantly.
        """

        existing = self.graph.get_aspect(dataset_urn, GlobalTagsClass)
        tags = list(existing.tags) if existing else []
        if association.tag in {item.tag for item in tags}:
            return
        tags.append(association)
        self.graph.emit_mcp(
            MetadataChangeProposalWrapper(entityUrn=dataset_urn, aspect=GlobalTagsClass(tags=tags))
        )

    def raise_incident(
        self,
        drift: DriftEvent,
        pr_url: str | None = None,
    ) -> WritebackAction:
        """Raise an OSS incident in TRIAGE and resolve it as FIXED after PR creation."""

        try:
            subject = drift.old_column or drift.new_column or "schema"
            title = f"Schema drift: {drift.dataset_name}.{subject}"
            # Deterministic URN derived from the drift identity, so re-running a repair
            # updates one incident instead of minting another. `raiseIncident` mints a random
            # URN, and de-duplicating by title afterwards is unreliable: the incident search
            # index lags, so a lookup right after a reset finds nothing and a duplicate is
            # created anyway. Five identical incidents had piled up this way.
            incident_urn = str(
                IncidentUrn(datahub_guid({"drift": drift.id, "dataset": drift.dataset_urn, "column": subject}))
            )
            existed = self.graph.exists(incident_urn)
            now_ms = int(datetime.now().timestamp() * 1000)
            stamp = AuditStampClass(time=now_ms, actor=make_user_urn("datahub-repair-agent"))
            self.graph.emit_mcp(
                MetadataChangeProposalWrapper(
                    entityUrn=incident_urn,
                    aspect=IncidentInfoClass(
                        type=IncidentTypeClass.DATA_SCHEMA,
                        title=title,
                        description=(
                            f"{drift.rationale} This OSS incident is the governance substitute for a "
                            "DataHub Cloud metadata proposal, which is not available in DataHub Core."
                        ),
                        entities=[drift.dataset_urn],
                        priority=1,
                        source=IncidentSourceClass(type=IncidentSourceTypeClass.MANUAL),
                        status=IncidentStatusClass(
                            state=IncidentStateClass.ACTIVE,
                            stage=IncidentStageClass.TRIAGE,
                            message=drift.rationale,
                            lastUpdated=stamp,
                        ),
                        created=stamp,
                    ),
                )
            )
            reused = existed
            stage = "TRIAGE"
            review_reference = _safe_reference(pr_url)
            if review_reference:
                self._update_incident_status(
                    incident_urn,
                    state="RESOLVED",
                    stage="FIXED",
                    message=f"Validated repair is available for review at {review_reference}",
                )
                stage = "FIXED"
            return self._action(
                kind="raise_incident",
                target_urn=drift.dataset_urn,
                detail=(
                    f"{'Reused' if reused else 'Raised'} OSS incident {incident_urn} and moved it to {stage}."
                ),
                suffix="/Incidents",
            )
        except Exception as exc:  # DataHub errors vary by transport and server version.
            return self._action(
                kind="raise_incident",
                target_urn=drift.dataset_urn,
                detail="Could not raise or transition the OSS schema-drift incident.",
                error=exc,
                suffix="/Incidents",
            )

    def resolve_namespace_incidents(self, dataset_urns: list[str]) -> list[str]:
        """Resolve incidents attached to explicitly enumerated in-namespace datasets."""

        resolved: list[str] = []
        for dataset_urn in sorted(set(dataset_urns)):
            name = DatasetUrn.from_string(dataset_urn).name
            if not name.startswith(self.settings.namespace_prefix):
                raise ValueError(f"Refusing to resolve incidents outside {self.settings.namespace_prefix}: {dataset_urn}")
            for incident in self._dataset_incidents(dataset_urn):
                incident_urn = incident.get("urn")
                if not isinstance(incident_urn, str):
                    continue
                self._update_incident_status(
                    incident_urn,
                    state="RESOLVED",
                    stage="FIXED",
                    message="Resolved by the ShopFlow demo namespace reset.",
                )
                resolved.append(incident_urn)
        return sorted(set(resolved))

    def _dataset_incidents(self, dataset_urn: str) -> list[dict[str, Any]]:
        response = self.graph.execute_graphql(_DATASET_INCIDENTS_QUERY, variables={"urn": dataset_urn})
        incidents = (((response.get("dataset") or {}).get("incidents") or {}).get("incidents") or [])
        return [incident for incident in incidents if isinstance(incident, dict)]

    def _update_incident_status(
        self,
        incident_urn: str,
        *,
        state: str,
        stage: str,
        message: str,
    ) -> None:
        self.graph.execute_graphql(
            _UPDATE_INCIDENT_STATUS,
            variables={
                "urn": incident_urn,
                "input": {"state": state, "stage": stage, "message": message},
            },
        )

    def attach_migration_doc(
        self,
        target_urn: str,
        pr_url: str | None,
        migration_doc_url: str | None,
    ) -> WritebackAction:
        """Attach stable PR and migration-document links as institutional memory."""

        try:
            existing = self.graph.get_aspect(target_urn, InstitutionalMemoryClass)
            elements = deepcopy(existing.elements) if existing else []
            stamp = AuditStampClass(
                time=int(datetime.now().timestamp() * 1000),
                actor=make_user_urn("datahub-repair-agent"),
            )
            additions = tuple(
                (url, description)
                for reference, description in (
                    (pr_url, "Schema-drift repair pull request"),
                    (migration_doc_url, "Schema-drift migration and rollback guide"),
                )
                if (url := _safe_reference(reference)) is not None
            )
            known_urls = {element.url for element in elements}
            for url, description in additions:
                if url not in known_urls:
                    elements.append(
                        InstitutionalMemoryMetadataClass(url=url, description=description, createStamp=stamp)
                    )
            self.graph.emit_mcp(
                MetadataChangeProposalWrapper(
                    entityUrn=target_urn,
                    aspect=InstitutionalMemoryClass(elements=elements),
                )
            )
            return self._action(
                kind="attach_migration_doc",
                target_urn=target_urn,
                detail="Attached the PR and migration guide as InstitutionalMemory.",
            )
        except Exception as exc:  # DataHub errors vary by transport and server version.
            return self._action(
                kind="attach_migration_doc",
                target_urn=target_urn,
                detail="Could not attach PR and migration-document institutional memory.",
                error=exc,
            )

    def record_run(
        self,
        run_id: str,
        source_dataset_urn: str,
        outlet_urns: list[str],
        *,
        succeeded: bool,
        started_at: datetime,
        finished_at: datetime,
    ) -> WritebackAction:
        """Record one deterministic, idempotent DataProcessInstance lifecycle."""

        instance = DataProcessInstance(
            id=run_id,
            orchestrator="datahub-repair-agent",
            cluster="prod",
            inlets=[DatasetUrn.from_string(source_dataset_urn)],
            outlets=[DatasetUrn.from_string(urn) for urn in sorted(set(outlet_urns))],
        )
        try:
            emitter = DataHubRestEmitter(
                gms_server=self.settings.datahub_gms_url,
                token=self.settings.datahub_gms_token or None,
            )
            start_millis = int(started_at.timestamp() * 1000)
            finish_millis = int(finished_at.timestamp() * 1000)
            instance.emit_process_start(
                emitter=emitter,
                start_timestamp_millis=start_millis,
                emit_template=True,
                materialize_iolets=True,
            )
            instance.emit_process_end(
                emitter=emitter,
                end_timestamp_millis=finish_millis,
                result=InstanceRunResult.SUCCESS if succeeded else InstanceRunResult.FAILURE,
                result_type="datahub-repair-agent",
                start_timestamp_millis=start_millis,
            )
            return self._action(
                kind="record_run",
                target_urn=str(instance.urn),
                detail=(
                    f"Recorded deterministic process run `{run_id}` with result "
                    f"{'SUCCESS' if succeeded else 'FAILURE'}."
                ),
            )
        except Exception as exc:  # DataHub errors vary by transport and server version.
            return self._action(
                kind="record_run",
                target_urn=str(instance.urn),
                detail=f"Could not record DataProcessInstance for run `{run_id}`.",
                error=exc,
            )

    def _action(
        self,
        *,
        kind: str,
        target_urn: str,
        detail: str,
        error: Exception | None = None,
        suffix: str = "",
    ) -> WritebackAction:
        return WritebackAction(
            kind=kind,
            target_urn=target_urn,
            detail=detail,
            datahub_url=datahub_entity_url(self.settings.datahub_frontend_url, target_urn, suffix=suffix),
            ok=error is None,
            error=str(error) if error else None,
        )

    @staticmethod
    def _fine_grained_lineage(edge: FglEdge) -> FineGrainedLineageClass:
        if edge.upstream_path is None or edge.downstream_path is None:
            raise ValueError("Fine-grained lineage write-back requires both upstream and downstream field paths.")
        return FineGrainedLineageClass(
            upstreamType=FineGrainedLineageUpstreamTypeClass.FIELD_SET,
            downstreamType=FineGrainedLineageDownstreamTypeClass.FIELD,
            upstreams=[make_schema_field_urn(edge.upstream_urn, edge.upstream_path)],
            downstreams=[make_schema_field_urn(edge.downstream_urn, edge.downstream_path)],
            transformOperation=edge.transform_operation,
            query=edge.query,
        )


def _safe_reference(reference: str | None) -> str | None:
    """Allow web URLs and clean repository-relative paths, never local file URLs."""

    if not reference or not reference.strip():
        return None
    value = reference.strip()
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value
    if parsed.scheme or value.startswith(("/", "~")):
        return None
    path = PurePosixPath(value)
    if ".." in path.parts:
        return None
    return path.as_posix()
