"""Capture and persist ordered DataHub schema snapshots."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path

from pydantic import RootModel

from repair_agent.config import get_settings
from repair_agent.datahub_io.client import DataHubIO
from repair_agent.models import ColumnSpec

LOGGER = logging.getLogger(__name__)


class SchemaSnapshot(RootModel[dict[str, dict[str, ColumnSpec]]]):
    """Ordered dataset-to-column mapping used as a drift baseline or live view."""

    def __getitem__(self, dataset_urn: str) -> dict[str, ColumnSpec]:
        return self.root[dataset_urn]

    def __contains__(self, dataset_urn: object) -> bool:
        return dataset_urn in self.root

    def __iter__(self) -> Iterator[str]:
        return iter(self.root)

    def items(self):  # type: ignore[no-untyped-def]
        """Return ordered dataset snapshot items."""

        return self.root.items()

    def get(self, dataset_urn: str, default: dict[str, ColumnSpec] | None = None) -> dict[str, ColumnSpec] | None:
        """Return one dataset schema if present."""

        return self.root.get(dataset_urn, default)

    def dataset_urns(self) -> list[str]:
        """Return every dataset URN in this snapshot.

        Passed to :meth:`capture` as ``known_urns`` so a live capture never loses a dataset
        just because the DataHub search index has not caught up.
        """

        return list(self.root)

    @classmethod
    def capture(
        cls,
        datahub_io: DataHubIO,
        prefix: str,
        *,
        known_urns: Iterable[str] = (),
    ) -> SchemaSnapshot:
        """Capture all live schemas in ``prefix`` from DataHub.

        Dataset discovery goes through DataHub search, which is eventually consistent —
        immediately after a re-seed it can omit datasets that certainly exist. Any URN the
        caller already knows about (in practice, every dataset in the committed baseline)
        is therefore fetched directly rather than trusted to the search index. Without this
        a freshly seeded catalog silently reports datasets as deleted, and drift on them is
        never detected.
        """

        discovered = list(datahub_io.list_namespace_datasets(prefix, skip_cache=True))
        candidates = dict.fromkeys([*discovered, *known_urns])
        datasets: dict[str, dict[str, ColumnSpec]] = {}
        for urn in candidates:
            schema = datahub_io.get_schema(urn, skip_cache=True)
            if not schema.columns:
                # Genuinely absent (or hard-deleted): leave it out so drift detection can
                # see the removal rather than inventing an empty schema.
                continue
            datasets[urn] = {column.name: column for column in schema.columns}
        recovered = len(datasets) - len([u for u in discovered if u in datasets])
        if recovered > 0:
            LOGGER.info("Recovered %d dataset(s) missing from the DataHub search index", recovered)
        LOGGER.info("Captured %d DataHub schemas under %s", len(datasets), prefix)
        return cls(datasets)

    @classmethod
    def load(cls, path: Path | str | None = None) -> SchemaSnapshot:
        """Load a snapshot from JSON, with an actionable error when it is absent."""

        target = _snapshot_path(path)
        if not target.is_file():
            raise FileNotFoundError(f"Schema baseline is missing at {target}. Run `repair-agent seed` first.")
        return cls.model_validate_json(target.read_text(encoding="utf-8"))

    def save(self, path: Path | str | None = None) -> Path:
        """Persist this snapshot as stable, human-readable JSON."""

        target = _snapshot_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.model_dump(), indent=2) + "\n", encoding="utf-8")
        LOGGER.info("Saved schema snapshot to %s", target)
        return target


def _snapshot_path(path: Path | str | None) -> Path:
    if path is not None:
        return Path(path)
    return get_settings().repo_root / "demo-warehouse" / ".repair-agent" / "snapshot.json"


def capture(datahub_io: DataHubIO, prefix: str, *, known_urns: Iterable[str] = ()) -> SchemaSnapshot:
    """Capture live schemas from DataHub."""

    return SchemaSnapshot.capture(datahub_io, prefix, known_urns=known_urns)


def load(path: Path | str | None = None) -> SchemaSnapshot:
    """Load the configured baseline snapshot."""

    return SchemaSnapshot.load(path)


def save(snapshot: SchemaSnapshot | Mapping[str, Mapping[str, ColumnSpec]], path: Path | str | None = None) -> Path:
    """Save a snapshot mapping to the configured baseline location."""

    normalized = snapshot if isinstance(snapshot, SchemaSnapshot) else SchemaSnapshot.model_validate(snapshot)
    return normalized.save(path)
