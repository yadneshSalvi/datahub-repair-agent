"""Best-effort DataHub governance write-back surface."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from urllib.parse import quote

from datahub.api.entities.dataprocess.dataprocess_instance import DataProcessInstance, InstanceRunResult
from datahub.emitter.mce_builder import make_schema_field_urn, make_tag_urn, make_user_urn
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
    InstitutionalMemoryClass,
    InstitutionalMemoryMetadataClass,
    TagAssociationClass,
    TagPropertiesClass,
    UpstreamClass,
)
from datahub.metadata.urns import DatasetUrn
from datahub.specific.dataset import DatasetPatchBuilder

from repair_agent.config import Settings, get_settings
from repair_agent.datahub_io.client import DataHubIO
from repair_agent.models import DriftEvent, FglEdge, WritebackAction


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
            source_builder = DatasetPatchBuilder(source_dataset_urn)
            source_builder.add_tag(detected)
            for proposal in source_builder.build():
                self.graph.emit_mcp(proposal)

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
                builder = DatasetPatchBuilder(urn)
                builder.add_tag(repaired)
                for proposal in builder.build():
                    self.graph.emit_mcp(proposal)
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

    def raise_incident(
        self,
        drift: DriftEvent,
        pr_url: str | None = None,
    ) -> WritebackAction:
        """Raise an OSS incident in TRIAGE and resolve it as FIXED after PR creation."""

        mutation = """
        mutation RaiseRepairIncident($input: RaiseIncidentInput!) {
          raiseIncident(input: $input)
        }
        """
        update = """
        mutation FixRepairIncident($urn: String!, $input: IncidentStatusInput!) {
          updateIncidentStatus(urn: $urn, input: $input)
        }
        """
        existing = """
        query ExistingRepairIncidents($urn: String!) {
          dataset(urn: $urn) {
            incidents(start: 0, count: 50) { incidents { urn title } }
          }
        }
        """
        try:
            subject = drift.old_column or drift.new_column or "schema"
            title = f"Schema drift: {drift.dataset_name}.{subject}"
            # Re-running the same repair must not pile up duplicate incidents (D18): reuse the
            # incident already raised for this drift if one exists. raiseIncident mints a fresh
            # random URN every call, so identity has to come from the title we control.
            incident_urn: str | None = None
            try:
                found = self.graph.execute_graphql(existing, variables={"urn": drift.dataset_urn})
                for candidate in (((found.get("dataset") or {}).get("incidents") or {}).get("incidents") or []):
                    if candidate.get("title") == title:
                        incident_urn = candidate.get("urn")
                        break
            except Exception:
                # A failed lookup must not block raising a new incident.
                incident_urn = None
            raised = {"raiseIncident": incident_urn} if incident_urn else self.graph.execute_graphql(
                mutation,
                variables={
                    "input": {
                        "type": "DATA_SCHEMA",
                        "title": title,
                        "description": f"{drift.rationale} This OSS incident is the governance substitute for a "
                        "DataHub Cloud metadata proposal.",
                        "resourceUrn": drift.dataset_urn,
                        "startedAt": int(drift.detected_at.timestamp() * 1000),
                        "source": {"type": "MANUAL"},
                        "status": {"state": "ACTIVE", "stage": "TRIAGE"},
                        "priority": "HIGH",
                    }
                },
            )
            reused = incident_urn is not None
            incident_urn = raised.get("raiseIncident")
            if not incident_urn:
                raise RuntimeError("DataHub returned no incident URN from raiseIncident")
            if reused:
                # Reopen the reused incident so the TRIAGE -> FIXED transition is observable again.
                self.graph.execute_graphql(
                    update,
                    variables={
                        "urn": incident_urn,
                        "input": {"state": "ACTIVE", "stage": "TRIAGE", "message": drift.rationale},
                    },
                )
            stage = "TRIAGE"
            if pr_url:
                self.graph.execute_graphql(
                    update,
                    variables={
                        "urn": incident_urn,
                        "input": {
                            "state": "RESOLVED",
                            "stage": "FIXED",
                            "message": f"Validated repair is available for review at {pr_url}",
                        },
                    },
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

    def attach_migration_doc(
        self,
        target_urn: str,
        pr_url: str,
        migration_doc_url: str,
    ) -> WritebackAction:
        """Attach stable PR and migration-document links as institutional memory."""

        try:
            existing = self.graph.get_aspect(target_urn, InstitutionalMemoryClass)
            elements = deepcopy(existing.elements) if existing else []
            stamp = AuditStampClass(
                time=int(datetime.now().timestamp() * 1000),
                actor=make_user_urn("datahub-repair-agent"),
            )
            additions = (
                (pr_url, "Schema-drift repair pull request"),
                (migration_doc_url, "Schema-drift migration and rollback guide"),
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
            datahub_url=f"{self._entity_url(target_urn)}{suffix}",
            ok=error is None,
            error=str(error) if error else None,
        )

    def _entity_url(self, urn: str) -> str:
        encoded_urn = quote(urn, safe="")
        entity_type = "dataset"
        if urn.startswith("urn:li:tag:"):
            entity_type = "tag"
        elif urn.startswith("urn:li:dataProcessInstance:"):
            entity_type = "dataProcessInstance"
        return f"{self.settings.datahub_frontend_url.rstrip('/')}/{entity_type}/{encoded_urn}"

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
