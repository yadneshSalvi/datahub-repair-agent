"""DataHub-lineage-first three-bucket impact engine."""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from datahub.metadata.urns import DatasetUrn
from ruamel.yaml import YAML

from repair_agent.codegen.airflow_ops import extract_sql_constants
from repair_agent.codegen.sql_ops import ColumnRef, find_column_references
from repair_agent.config import Settings, get_settings
from repair_agent.datahub_io.client import DataHubIO
from repair_agent.datahub_io.links import datahub_entity_url
from repair_agent.models import (
    ColumnImpactHit,
    DriftEvent,
    FglEdge,
    ImpactBucket,
    ImpactedAsset,
    ImpactReport,
    LineageEdge,
    LineageGraph,
    LineageHop,
    LineageNode,
)

LOGGER = logging.getLogger(__name__)


class CodeMapMissing(RuntimeError):
    """Raised when catalog lineage finds impacted code that cannot be located."""


class LineageUnavailable(RuntimeError):
    """Raised when DataHub's lineage index cannot answer, so the blast radius is unknown.

    Deliberately distinct from "nothing is affected". Reporting an empty impact set when the
    index is merely lagging would tell a reviewer their pipeline is safe when it is not.
    """


class ImpactEngine:
    """Compute a precise blast radius from DataHub evidence and exact SQL references."""

    #: Budget for waiting out DataHub graph-index lag (see _lineage_with_index_settling).
    LINEAGE_SETTLE_ATTEMPTS = 10
    LINEAGE_SETTLE_SECONDS = 3.0

    def __init__(self, datahub_io: DataHubIO | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.datahub_io = datahub_io or DataHubIO(self.settings)
        self.code_map = _load_code_map(self.settings.repo_root / "demo-warehouse" / "code_map.yml")
        self._fgl_cache: dict[str, list[FglEdge]] = {}

    def _lineage_with_index_settling(self, drift: DriftEvent) -> tuple[list[Any], list[Any]]:
        """Read column-level and table-level lineage, waiting out graph-index lag.

        DataHub's lineage graph is populated asynchronously, so an empty column-lineage read
        is ambiguous: it can mean the index has not caught up, or that nothing consumes the
        column. The lineage ASPECTS resolve the ambiguity, because they are written
        synchronously and read entity-by-entity rather than through the index.

        The rule is therefore about agreement, not about emptiness:

        * aspects declare downstream edges the index cannot see -> they DISAGREE, the index
          is lagging or broken, and we refuse rather than report a short blast radius;
        * aspects agree there are no edges for this column -> genuinely empty, and we answer
          honestly with a narrowed result. This covers both a column nobody consumes and a
          drift a previous run already repaired onto its successor name;
        * nothing declares any edge out of the dataset and nothing could be corroborated ->
          the catalog is unseeded or unreadable, so we refuse.

        Refusing on agreement was a real bug: it hard-failed the documented second run, whose
        downstream models correctly carry healthy edges for the NEW column and none for the
        old one.
        """

        assert drift.old_column is not None
        expected = self._aspect_declared_downstreams(drift)
        if not expected and not self._aspect_declares_any_edge_from(drift.dataset_urn):
            # Nothing anywhere declares an edge out of the drifted dataset, and we could not
            # read otherwise. On a seeded ShopFlow catalog that is impossible, so the catalog
            # is unseeded, was wiped mid-run, or its aspects are unreadable. Fail here rather
            # than let every asset fall through to SKIPPED.
            raise LineageUnavailable(
                f"No dataset in the catalog declares any column-level lineage from "
                f"{drift.dataset_name}, and its lineage aspects could not be corroborated. The "
                "ShopFlow catalog looks unseeded or was modified mid-run, so the blast radius "
                "cannot be computed. Run `make seed verify` and retry — reporting an empty "
                "impact set here would wrongly imply nothing is affected."
            )
        column_hits: list[Any] = []
        table_hits: list[Any] = []
        for attempt in range(self.LINEAGE_SETTLE_ATTEMPTS):
            column_hits = self.datahub_io.column_impact(drift.dataset_urn, drift.old_column, max_hops=3)
            table_hits = self.datahub_io.table_downstreams(drift.dataset_urn, max_hops=3)
            if not expected or {hit.urn for hit in column_hits} >= expected:
                break
            if attempt < self.LINEAGE_SETTLE_ATTEMPTS - 1:
                LOGGER.info(
                    "Column-lineage search returned %d of the %d downstream(s) that %s.%s's "
                    "lineage aspects declare; waiting for the DataHub graph index to settle "
                    "(attempt %d/%d).",
                    len(column_hits),
                    len(expected),
                    drift.dataset_name,
                    drift.old_column,
                    attempt + 1,
                    self.LINEAGE_SETTLE_ATTEMPTS,
                )
                time.sleep(self.LINEAGE_SETTLE_SECONDS)
        missing = expected - {hit.urn for hit in column_hits}
        if missing:
            # Refuse to answer rather than answer wrongly. Silently returning a short (or
            # empty) blast radius is this tool's most dangerous failure: the UI would render
            # "N models correctly skipped" and a reviewer would conclude nothing is broken.
            raise LineageUnavailable(
                f"DataHub's lineage search still omits {len(missing)} dataset(s) whose lineage "
                f"aspects declare a column edge from {drift.dataset_name}.{drift.old_column} "
                f"({', '.join(sorted(_asset_name(urn) for urn in missing))}), after waiting "
                f"{self.LINEAGE_SETTLE_ATTEMPTS * self.LINEAGE_SETTLE_SECONDS:.0f}s for the graph "
                "index to settle. Refusing to report an incomplete blast radius — re-run once "
                "DataHub has caught up."
            )
        if not column_hits:
            # The index reports no consumers of the drifted column and the aspect store agrees
            # (``expected`` is empty, and it was readable — otherwise we raised above). Aspects
            # and index AGREEING is a genuine answer, not a fault: either the column was never
            # consumed, or a previous run already repaired its consumers onto the new name.
            # Refusing here is what broke the documented re-run, where stg_orders correctly has
            # healthy edges for `order_created_at` and none for `order_placed_at`.
            successor = drift.new_column
            repaired_by = (
                self._aspect_declared_downstreams(drift, successor)
                if successor and successor != drift.old_column
                else set()
            )
            if repaired_by:
                LOGGER.info(
                    "No consumers remain for %s.%s, but %d dataset(s) now consume `%s` — this "
                    "drift was already repaired, so there is less to do.",
                    drift.dataset_name,
                    drift.old_column,
                    len(repaired_by),
                    successor,
                )
            else:
                LOGGER.info(
                    "No dataset consumes %s.%s; the catalog is readable and agrees, so the "
                    "blast radius is genuinely empty.",
                    drift.dataset_name,
                    drift.old_column,
                )
        return column_hits, table_hits

    def _aspect_declares_any_edge_from(self, dataset_urn: str) -> bool:
        """True if any mapped dataset declares a column edge out of ``dataset_urn``.

        Index-independent sanity check on the catalog itself, used to tell "this column is
        genuinely unused" apart from "the catalog is not seeded".
        """

        source = dataset_urn.lower()
        for urn in self.code_map["datasets"]:
            for edge in self._fgl_cache.get(urn, []):
                if edge.upstream_urn.lower() == source:
                    return True
        return False

    def _aspect_declared_downstreams(self, drift: DriftEvent, column: str | None = None) -> set[str]:
        """Datasets whose lineage ASPECTS declare a path from ``column`` on the drifted dataset.

        Defaults to the drifted (old) column. Read entity-by-entity over GraphQL rather than
        through lineage search, so it does not depend on the asynchronously-built graph index.
        This is the oracle that tells the settle loop whether an empty search result is real or
        merely early: aspects are written synchronously, the index catches up seconds later.
        """

        source_column = column if column is not None else drift.old_column
        assert source_column is not None
        edges: list[FglEdge] = []
        for urn in self.code_map["datasets"]:
            try:
                dataset_edges = self._fgl_cache.get(urn) or self.datahub_io.fine_grained_lineage(urn, skip_cache=True)
            except Exception as exc:  # pragma: no cover - only a live-catalog degradation
                LOGGER.debug("Could not pre-read fine-grained lineage for %s: %s", urn, exc)
                continue
            self._fgl_cache[urn] = dataset_edges
            edges.extend(dataset_edges)

        # Walk the aspect graph transitively: a hop-2 model is indexed slightly later than a
        # hop-1 model, so a direct-edge-only oracle stops waiting too early and reports a
        # blast radius that is short by exactly the deeper models.
        frontier = {(drift.dataset_urn.lower(), source_column.lower())}
        seen: set[tuple[str, str]] = set()
        declared: set[str] = set()
        while frontier:
            current = frontier.pop()
            if current in seen:
                continue
            seen.add(current)
            for edge in edges:
                if (edge.upstream_urn.lower(), (edge.upstream_path or "").lower()) != current:
                    continue
                declared.add(edge.downstream_urn)
                frontier.add((edge.downstream_urn.lower(), (edge.downstream_path or "").lower()))
        return declared

    def analyze(self, drift: DriftEvent) -> ImpactReport:
        """Run the seven impact-analysis steps in the locked plan order."""

        if drift.old_column is None:
            return self._addition_report(drift)

        # 1 & 2. Exact column blast radius, plus the full table downstream set for contrast.
        column_hits, table_hits = self._lineage_with_index_settling(drift)
        column_by_urn = {hit.urn: hit for hit in column_hits}
        table_by_urn = {hit.urn: hit for hit in table_hits}

        # 3. Sweep all namespace dbt datasets, including unrelated models.
        namespace_urns = self.datahub_io.list_namespace_datasets(self.settings.namespace_prefix, skip_cache=True)
        dbt_namespace_urns = {urn for urn in namespace_urns if "urn:li:dataPlatform:dbt" in urn}

        # 4. Every column-impacted dataset must map to code.
        for urn in column_by_urn:
            if urn not in self.code_map["datasets"]:
                raise CodeMapMissing(
                    f"DataHub says {urn} is impacted, but demo-warehouse/code_map.yml has no dataset entry. "
                    "Add its SQL and schema.yml mapping before running repair; silently skipping it would be "
                    "a false negative."
                )

        all_dataset_urns = sorted(dbt_namespace_urns | set(self.code_map["datasets"]))
        fgl_by_urn: dict[str, list[FglEdge]] = {}

        def read_fgl(urn: str) -> list[FglEdge]:
            if urn in self._fgl_cache:
                return self._fgl_cache[urn]
            # The SDK graph client serializes requests through its session. Separate
            # read-only clients let independent GraphQL entity reads actually overlap.
            if type(self.datahub_io) is DataHubIO:
                return DataHubIO(self.settings).fine_grained_lineage(urn, skip_cache=True)
            return self.datahub_io.fine_grained_lineage(urn, skip_cache=True)

        with ThreadPoolExecutor(max_workers=min(8, len(all_dataset_urns) or 1)) as executor:
            futures = {executor.submit(read_fgl, urn): urn for urn in all_dataset_urns}
            for future in as_completed(futures):
                urn = futures[future]
                try:
                    fgl_by_urn[urn] = future.result()
                    self._fgl_cache[urn] = fgl_by_urn[urn]
                except Exception as exc:  # pragma: no cover - only a live-catalog degradation
                    LOGGER.warning("Could not read fine-grained lineage for %s: %s", urn, exc)
                    fgl_by_urn[urn] = []

        lineage_paths, graph_edges = _reachable_lineage(
            drift.dataset_urn,
            drift.old_column,
            [edge for edges in fgl_by_urn.values() for edge in edges],
        )

        assets: list[ImpactedAsset] = []
        # 5. Classify column-impacted code by exact AST references.
        for urn in all_dataset_urns:
            mapping = self.code_map["datasets"].get(urn)
            hit = column_by_urn.get(urn)
            if mapping is None:
                assets.append(
                    ImpactedAsset(
                        urn=urn,
                        name=_asset_name(urn),
                        kind="dataset",
                        bucket=ImpactBucket.SKIPPED,
                        hops=table_by_urn.get(urn).hops if urn in table_by_urn else None,
                        reason=(
                            "No code mapping exists, and DataHub reports no path from the changed column to this "
                            "catalog dataset."
                        ),
                    )
                )
                continue
            sql_path = self.settings.repo_root / mapping["sql"]
            sql = sql_path.read_text(encoding="utf-8")
            references = _matching_references(sql, drift.old_column)
            consumed = _consumed_evidence(fgl_by_urn.get(urn, []))
            if hit is not None:
                if references:
                    locations = _reference_locations(references)
                    bucket = ImpactBucket.REQUIRES_PATCH
                    reason = (
                        f"SQL references `{drift.old_column}` exactly {locations}; this lineage-bearing file "
                        "requires repair."
                    )
                else:
                    bucket = ImpactBucket.DOWNSTREAM_UNAFFECTED
                    insulated = _insulating_columns(sql, hit, drift.old_column)
                    reason = (
                        f"Reads {insulated}, aliases created upstream on the changed column's lineage path; "
                        f"`{drift.old_column}` does not appear in this file's SQL. Flagged for review only."
                    )
                queries = self._captured_queries(urn, drift.old_column) if bucket is ImpactBucket.REQUIRES_PATCH else []
                assets.append(
                    ImpactedAsset(
                        urn=urn,
                        name=mapping.get("model_name") or _asset_name(urn),
                        kind=mapping.get("kind", "dbt_model"),
                        bucket=bucket,
                        hops=hit.hops,
                        matched_columns=hit.matched_columns,
                        code_path=mapping["sql"],
                        reason=reason,
                        lineage_path=lineage_paths.get(urn, []),
                        captured_queries=queries,
                    )
                )
            else:
                table_hit = table_by_urn.get(urn)
                if table_hit is not None:
                    reason = (
                        f"In the table-level downstream graph, but consumes {consumed}; none is on the exact "
                        f"`{drift.dataset_name}.{drift.old_column}` column-lineage path."
                    )
                else:
                    reason = (
                        f"No lineage path from the changed column; this model consumes {consumed}, "
                        f"not `{drift.dataset_name}.{drift.old_column}`."
                    )
                assets.append(
                    ImpactedAsset(
                        urn=urn,
                        name=mapping.get("model_name") or _asset_name(urn),
                        kind=mapping.get("kind", "dbt_model"),
                        bucket=ImpactBucket.SKIPPED,
                        hops=table_hit.hops if table_hit else None,
                        code_path=mapping["sql"],
                        reason=reason,
                    )
                )

        # DataJobs do not carry field lineage in OSS. A table-lineage candidate is promoted
        # only when its mapped SQL constant has an exact AST reference to the drifted field.
        for urn, mapping in sorted(self.code_map["datajobs"].items()):
            path = self.settings.repo_root / mapping["file"]
            constants = extract_sql_constants(path.read_text(encoding="utf-8"), list(mapping.get("sql_constants", [])))
            references = [
                reference for sql in constants.values() for reference in _matching_references(sql, drift.old_column)
            ]
            table_hit = table_by_urn.get(urn)
            if table_hit is not None and references:
                locations = _reference_locations(references)
                bucket = ImpactBucket.REQUIRES_PATCH
                reason = (
                    f"DataHub table lineage links this Airflow task to `{drift.dataset_name}`, and its configured SQL "
                    f"constant references `{drift.old_column}` exactly {locations}."
                )
                path_evidence = [
                    LineageHop(
                        upstream_urn=drift.dataset_urn,
                        upstream_column=drift.old_column,
                        downstream_urn=urn,
                        downstream_column=drift.old_column,
                        transform_operation="DIRECT_SQL_REFERENCE",
                        hops=table_hit.hops,
                    )
                ]
                queries = self._captured_queries(drift.dataset_urn, drift.old_column)
                graph_edges.append(
                    LineageEdge(
                        source_urn=drift.dataset_urn,
                        target_urn=urn,
                        source_columns=[drift.old_column],
                        target_columns=[drift.old_column],
                        transform_operation="DIRECT_SQL_REFERENCE",
                    )
                )
            else:
                bucket = ImpactBucket.SKIPPED
                names = sorted({reference.name for sql in constants.values() for reference in find_column_references(sql)})
                consumed_names = ", ".join(f"`{name}`" for name in names)
                reason = (
                    f"No exact changed-column reference; configured Airflow SQL consumes {consumed_names}, "
                    f"not `{drift.old_column}`."
                )
                path_evidence = []
                queries = []
            assets.append(
                ImpactedAsset(
                    urn=urn,
                    name=_asset_name(urn),
                    kind=mapping.get("kind", "airflow_task"),
                    bucket=bucket,
                    hops=table_hit.hops if table_hit else None,
                    matched_columns=[drift.old_column] if bucket is ImpactBucket.REQUIRES_PATCH else [],
                    code_path=mapping["file"],
                    reason=reason,
                    lineage_path=path_evidence,
                    captured_queries=queries,
                )
            )

        # 6. Captured queries and lineage paths were attached above.
        assets.sort(key=lambda asset: (_bucket_order(asset.bucket), asset.name))

        # 7. Renderable graph with bucket and transform evidence.
        source_node = LineageNode(
            urn=drift.dataset_urn,
            name=drift.dataset_name,
            kind="dataset",
            columns=[drift.old_column],
            hops=0,
            datahub_url=datahub_entity_url(self.settings.datahub_frontend_url, drift.dataset_urn),
        )
        graph_nodes = [source_node] + [
            LineageNode(
                urn=asset.urn,
                name=asset.name,
                kind=asset.kind,
                bucket=asset.bucket,
                columns=asset.matched_columns,
                hops=asset.hops,
                datahub_url=datahub_entity_url(self.settings.datahub_frontend_url, asset.urn),
            )
            for asset in assets
        ]
        stats = {
            "requires_patch": sum(asset.bucket is ImpactBucket.REQUIRES_PATCH for asset in assets),
            "downstream_unaffected": sum(asset.bucket is ImpactBucket.DOWNSTREAM_UNAFFECTED for asset in assets),
            "skipped": sum(asset.bucket is ImpactBucket.SKIPPED for asset in assets),
            "total_scanned": len(assets),
            "max_hops_reached": max((asset.hops or 0 for asset in assets), default=0),
        }
        return ImpactReport(
            drift=drift, assets=assets[:25], graph=LineageGraph(nodes=graph_nodes[:26], edges=graph_edges), stats=stats
        )

    def _captured_queries(self, urn: str, column: str) -> list[str]:
        try:
            return self.datahub_io.dataset_queries(urn, column=column, skip_cache=True)[:3]
        except Exception as exc:  # pragma: no cover - depends on optional usage aspects
            LOGGER.warning("Could not read captured queries for %s: %s", urn, exc)
            return []

    def _addition_report(self, drift: DriftEvent) -> ImpactReport:
        stats = {"requires_patch": 0, "downstream_unaffected": 0, "skipped": 0, "total_scanned": 0, "max_hops_reached": 0}
        return ImpactReport(
            drift=drift,
            graph=LineageGraph(
                nodes=[LineageNode(urn=drift.dataset_urn, name=drift.dataset_name, columns=[drift.new_column or ""])]
            ),
            stats=stats,
        )


def analyze(
    drift: DriftEvent,
    datahub_io: DataHubIO | None = None,
    settings: Settings | None = None,
) -> ImpactReport:
    """Convenience entry point for one impact analysis."""

    return ImpactEngine(datahub_io, settings).analyze(drift)


def _load_code_map(path: Path) -> dict[str, dict[str, dict[str, Any]]]:
    yaml = YAML(typ="safe")
    document = yaml.load(path)
    if not isinstance(document, dict) or not isinstance(document.get("datasets"), dict):
        raise ValueError(f"Invalid code map at {path}; expected top-level datasets and datajobs mappings.")
    return {"datasets": document["datasets"], "datajobs": document.get("datajobs", {})}


def _matching_references(sql: str, column: str) -> list[ColumnRef]:
    return [reference for reference in find_column_references(sql) if reference.name.casefold() == column.casefold()]


def _reference_locations(references: list[ColumnRef]) -> str:
    lines = sorted({reference.line for reference in references if reference.line is not None})
    occurrence = "once" if len(references) == 1 else f"{len(references)} times"
    if not lines:
        return occurrence
    line_label = "line" if len(lines) == 1 else "lines"
    return f"{occurrence} on {line_label} {', '.join(str(line) for line in lines)}"


def _insulating_columns(sql: str, hit: ColumnImpactHit, old_column: str) -> str:
    sql_names = {reference.name for reference in find_column_references(sql)}
    matched = sorted(name for name in hit.matched_columns if name != old_column and name in sql_names)
    if not matched:
        matched = sorted(name for name in hit.matched_columns if name != old_column)
    return ", ".join(f"`{name}`" for name in matched) or "only upstream aliases"


def _consumed_evidence(edges: list[FglEdge]) -> str:
    consumed: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if edge.upstream_path:
            consumed[_asset_name(edge.upstream_urn)].add(edge.upstream_path)
    if not consumed:
        return "no cataloged input columns"
    groups = []
    for name, columns in sorted(consumed.items()):
        groups.append(f"`{name}` columns {{{', '.join(sorted(columns))}}}")
    return "; ".join(groups)


def _reachable_lineage(
    source_urn: str,
    source_column: str,
    edges: list[FglEdge],
) -> tuple[dict[str, list[LineageHop]], list[LineageEdge]]:
    adjacency: dict[tuple[str, str], list[FglEdge]] = defaultdict(list)
    for edge in edges:
        if edge.upstream_path and edge.downstream_path:
            adjacency[(edge.upstream_urn, edge.upstream_path)].append(edge)
    paths: dict[tuple[str, str], list[LineageHop]] = {(source_urn, source_column): []}
    queue: deque[tuple[str, str]] = deque([(source_urn, source_column)])
    graph_edges: list[LineageEdge] = []
    while queue:
        current = queue.popleft()
        for edge in adjacency.get(current, []):
            target = (edge.downstream_urn, edge.downstream_path or "")
            hop = LineageHop(
                upstream_urn=edge.upstream_urn,
                upstream_column=edge.upstream_path,
                downstream_urn=edge.downstream_urn,
                downstream_column=edge.downstream_path,
                transform_operation=edge.transform_operation,
                hops=len(paths[current]) + 1,
            )
            graph_edges.append(
                LineageEdge(
                    source_urn=edge.upstream_urn,
                    target_urn=edge.downstream_urn,
                    source_columns=[edge.upstream_path] if edge.upstream_path else [],
                    target_columns=[edge.downstream_path] if edge.downstream_path else [],
                    transform_operation=edge.transform_operation,
                )
            )
            if target not in paths:
                paths[target] = [*paths[current], hop]
                queue.append(target)
    by_urn: dict[str, list[LineageHop]] = {}
    for (urn, _), path in sorted(paths.items(), key=lambda item: len(item[1])):
        if urn != source_urn and urn not in by_urn:
            by_urn[urn] = path
    unique_edges = list(
        {
            (edge.source_urn, edge.target_urn, tuple(edge.source_columns), tuple(edge.target_columns)): edge
            for edge in graph_edges
        }.values()
    )
    return by_urn, unique_edges


def _asset_name(urn: str) -> str:
    if urn.startswith("urn:li:dataset:"):
        try:
            return DatasetUrn.from_string(urn).name.rsplit(".", 1)[-1]
        except ValueError:
            pass
    return urn.rsplit(",", 1)[-1].rstrip(")")


def _bucket_order(bucket: ImpactBucket) -> int:
    return {
        ImpactBucket.REQUIRES_PATCH: 0,
        ImpactBucket.DOWNSTREAM_UNAFFECTED: 1,
        ImpactBucket.SKIPPED: 2,
    }[bucket]
