"""Deterministic DataHub read layer used by the repair engine."""

from __future__ import annotations

import re
import time
from typing import Any

import httpx
from datahub.metadata.urns import DatasetUrn, Urn

from repair_agent.config import Settings, get_settings
from repair_agent.models import ColumnImpactHit, ColumnSpec, DatasetSchema, FglEdge


class DataHubPreflightError(RuntimeError):
    """Raised when the configured URL does not identify a DataHub GMS server."""


class DataHubIO:
    """Thin, typed wrapper around verified DataHub SDK and GraphQL calls."""

    _FINE_GRAINED_QUERY = """
    query dsColumnLineage($urn: String!) {
      dataset(urn: $urn) {
        urn
        name
        schemaMetadata(version: 0) {
          fields { fieldPath type nativeDataType description }
        }
        fineGrainedLineages {
          upstreams { urn path }
          downstreams { urn path }
          transformOperation
          query
        }
      }
    }
    """

    def __init__(self, settings: Settings | None = None) -> None:
        import warnings

        from datahub.errors import ExperimentalWarning

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=ExperimentalWarning)
            from datahub.sdk import DataHubClient

        self.settings = settings or get_settings()
        self.client = DataHubClient(
            server=self.settings.datahub_gms_url,
            token=self.settings.datahub_gms_token or None,
        )
        self.graph = self.client._graph

    def preflight(self) -> dict[str, Any]:
        """Assert that the configured endpoint is DataHub GMS, not the service on port 8080."""

        endpoint = f"{self.settings.datahub_gms_url.rstrip('/')}/config"
        headers = self._auth_headers()
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(endpoint, headers=headers)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise DataHubPreflightError(
                f"DataHub preflight failed at {endpoint}: {exc}. "
                "The quickstart GMS must be exposed on host port 8081; port 8080 belongs "
                "to an unrelated application. Set DATAHUB_GMS_URL=http://localhost:8081."
            ) from exc

        server_type = payload.get("datahub", {}).get("serverType") if isinstance(payload, dict) else None
        if not server_type:
            raise DataHubPreflightError(
                f"{endpoint} responded, but it is not DataHub GMS (missing datahub.serverType). "
                "Do not use port 8080; set DATAHUB_GMS_URL=http://localhost:8081."
            )
        return payload

    def get_schema(self, dataset_urn: str, *, skip_cache: bool = True) -> DatasetSchema:
        """Read the latest schema metadata for a dataset."""

        del skip_cache  # get_schema_metadata is a direct aspect read and has no cache flag.
        schema = self.graph.get_schema_metadata(dataset_urn)
        if schema is None:
            return DatasetSchema(dataset_urn=dataset_urn)

        columns = [
            ColumnSpec(
                name=field.fieldPath,
                native_type=field.nativeDataType,
                data_type=self._logical_type(field.type.type),
                description=field.description,
                nullable=True if field.nullable is None else field.nullable,
            )
            for field in schema.fields
        ]
        return DatasetSchema(dataset_urn=dataset_urn, columns=columns)

    def column_impact(
        self,
        dataset_urn: str,
        column: str,
        max_hops: int = 3,
        *,
        skip_cache: bool = True,
    ) -> list[ColumnImpactHit]:
        """Return downstream entities reached from one exact source column."""

        results = self._get_lineage(
            source_urn=dataset_urn,
            source_column=column,
            max_hops=max_hops,
            skip_cache=skip_cache,
        )
        return [
            ColumnImpactHit(
                urn=str(result.urn),
                name=result.name,
                entity_type=result.type,
                hops=result.hops,
                direction=result.direction,
                platform=result.platform,
                matched_columns=sorted({path.column_name for path in (result.paths or []) if path.column_name}),
            )
            for result in results
        ]

    def table_downstreams(
        self,
        dataset_urn: str,
        max_hops: int = 3,
        *,
        skip_cache: bool = True,
    ) -> list[ColumnImpactHit]:
        """Return table-level downstream lineage for a dataset."""

        results = self._get_lineage(
            source_urn=dataset_urn,
            source_column=None,
            max_hops=max_hops,
            skip_cache=skip_cache,
        )
        return [
            ColumnImpactHit(
                urn=str(result.urn),
                name=result.name,
                entity_type=result.type,
                hops=result.hops,
                direction=result.direction,
                platform=result.platform,
            )
            for result in results
        ]

    def fine_grained_lineage(
        self,
        dataset_urn: str,
        *,
        skip_cache: bool = True,
    ) -> list[FglEdge]:
        """Read exact fine-grained lineage edges from a downstream dataset."""

        del skip_cache  # This entity lookup query does not expose SearchFlags.
        payload = self.graph.execute_graphql(
            self._FINE_GRAINED_QUERY,
            variables={"urn": dataset_urn},
        )
        dataset = payload.get("dataset") or {}
        edges: list[FglEdge] = []
        for lineage in dataset.get("fineGrainedLineages") or []:
            for upstream in lineage.get("upstreams") or []:
                for downstream in lineage.get("downstreams") or []:
                    edges.append(
                        FglEdge(
                            upstream_urn=upstream["urn"],
                            upstream_path=upstream.get("path"),
                            downstream_urn=downstream["urn"],
                            downstream_path=downstream.get("path"),
                            transform_operation=lineage.get("transformOperation"),
                            query=lineage.get("query"),
                        )
                    )
        return edges

    def dataset_queries(
        self,
        dataset_urn: str,
        column: str | None = None,
        *,
        skip_cache: bool = True,
    ) -> list[str]:
        """Return de-duplicated captured SQL text from dataset usage aspects."""

        del skip_cache  # Usage-aspect reads do not expose a cache-control argument.
        end_timestamp = int(time.time() * 1000)
        start_timestamp = end_timestamp - (365 * 24 * 60 * 60 * 1000)
        aspects = (
            self.graph.get_usage_aspects_from_urn(
                dataset_urn,
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
            )
            or []
        )
        pattern = re.compile(rf"\b{re.escape(column)}\b", re.IGNORECASE) if column else None
        queries: list[str] = []
        for aspect in aspects:
            for query in aspect.topSqlQueries or []:
                if pattern is not None and pattern.search(query) is None:
                    continue
                if query not in queries:
                    queries.append(query)
        return queries

    def list_namespace_datasets(
        self,
        prefix: str | None = None,
        *,
        skip_cache: bool = True,
    ) -> list[str]:
        """List active datasets whose parsed dataset name starts with the namespace prefix."""

        namespace = prefix or self.settings.namespace_prefix
        candidates = self.graph.get_urns_by_filter(
            entity_types=["dataset"],
            query=f"{namespace}*",
            batch_size=5000,
            skip_cache=skip_cache,
        )
        matches: list[str] = []
        for candidate in candidates:
            candidate_string = str(candidate)
            try:
                dataset_name = DatasetUrn.from_string(candidate_string).name
            except ValueError:
                continue
            if dataset_name.startswith(namespace):
                matches.append(candidate_string)
        return sorted(set(matches))

    def _get_lineage(
        self,
        *,
        source_urn: str,
        source_column: str | None,
        max_hops: int,
        skip_cache: bool,
    ) -> list[Any]:
        if not skip_cache:
            return self.client.lineage.get_lineage(
                source_urn=source_urn,
                source_column=source_column,
                direction="downstream",
                max_hops=max_hops,
            )

        # acryl-datahub 1.6.0.16 exposes SearchFlags internally but omits skip_cache from
        # the public method. The project pins that verified version, and D16 requires this
        # flag for correct read-after-write verification.
        lineage_client = self.client.lineage
        variables = lineage_client._process_input_variables(
            Urn.from_string(source_urn),
            source_column,
            None,
            "downstream",
            max_hops,
            500,
        )
        variables["input"].setdefault("searchFlags", {})["skipCache"] = True
        return lineage_client._execute_lineage_query(variables, "downstream")

    def _auth_headers(self) -> dict[str, str]:
        if not self.settings.datahub_gms_token:
            return {}
        return {"Authorization": f"Bearer {self.settings.datahub_gms_token}"}

    @staticmethod
    def _logical_type(data_type: object) -> str:
        class_name = type(data_type).__name__
        return class_name.removesuffix("TypeClass").lower()
