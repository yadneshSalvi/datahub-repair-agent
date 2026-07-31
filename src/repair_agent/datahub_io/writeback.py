"""Best-effort DataHub governance write-back surface."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from urllib.parse import quote

from datahub.emitter.mce_builder import make_tag_urn, make_user_urn
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.metadata.schema_classes import (
    AuditStampClass,
    EditableSchemaFieldInfoClass,
    EditableSchemaMetadataClass,
    TagPropertiesClass,
)

from repair_agent.config import Settings, get_settings
from repair_agent.datahub_io.client import DataHubIO
from repair_agent.models import DriftEvent, FglEdge, WritebackAction


class DataHubWriteback:
    """Governance write-backs; Slice C completes all methods marked as stubs."""

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
        """Update repaired column lineage (implemented in Slice C)."""

        raise NotImplementedError("Slice C implements repaired fine-grained lineage write-back.")

    def tag_assets(
        self,
        source_dataset_urn: str,
        source_column: str,
        patched_dataset_urns: list[str],
    ) -> WritebackAction:
        """Tag detected and repaired assets (implemented in Slice C)."""

        raise NotImplementedError("Slice C implements drift detection and repair tags.")

    def raise_incident(
        self,
        drift: DriftEvent,
        pr_url: str | None = None,
    ) -> WritebackAction:
        """Raise or resolve the OSS incident substitute (implemented in Slice C)."""

        raise NotImplementedError("Slice C implements OSS incident lifecycle write-back.")

    def attach_migration_doc(
        self,
        target_urn: str,
        pr_url: str,
        migration_doc_url: str,
    ) -> WritebackAction:
        """Attach PR and migration links (implemented in Slice C)."""

        raise NotImplementedError("Slice C implements institutional-memory write-back.")

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
        """Record a DataProcessInstance (implemented in Slice C)."""

        raise NotImplementedError("Slice C implements DataProcessInstance write-back.")

    def _action(
        self,
        *,
        kind: str,
        target_urn: str,
        detail: str,
        error: Exception | None = None,
    ) -> WritebackAction:
        return WritebackAction(
            kind=kind,
            target_urn=target_urn,
            detail=detail,
            datahub_url=self._entity_url(target_urn),
            ok=error is None,
            error=str(error) if error else None,
        )

    def _entity_url(self, urn: str) -> str:
        encoded_urn = quote(urn, safe="")
        return f"{self.settings.datahub_frontend_url.rstrip('/')}/dataset/{encoded_urn}"
