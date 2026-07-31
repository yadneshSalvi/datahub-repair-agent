"""Deterministically infer normalized drift events from ordered schema snapshots."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from difflib import SequenceMatcher

from datahub.metadata.urns import DatasetUrn

from repair_agent.drift.snapshot import SchemaSnapshot
from repair_agent.models import ColumnSpec, DriftEvent, DriftKind

LOGGER = logging.getLogger(__name__)
RENAME_SIMILARITY_THRESHOLD = 0.55


def detect_drift(baseline: SchemaSnapshot, live: SchemaSnapshot) -> list[DriftEvent]:
    """Return deterministic drift events between baseline and live schemas."""

    events: list[DriftEvent] = []
    for dataset_urn, baseline_columns in baseline.items():
        live_columns = live.get(dataset_urn)
        if live_columns is None:
            LOGGER.warning("Live snapshot omitted baseline dataset %s; dataset deletion is outside Slice B", dataset_urn)
            continue

        common_names = baseline_columns.keys() & live_columns.keys()
        for name in common_names:
            old = baseline_columns[name]
            new = live_columns[name]
            if old.native_type != new.native_type:
                events.append(
                    declare_drift(
                        kind=DriftKind.RETYPE,
                        dataset_urn=dataset_urn,
                        old_column=name,
                        new_column=name,
                        old_type=old.native_type,
                        new_type=new.native_type,
                        confidence=1.0,
                        rationale=(
                            f"`{name}` remains present, but its native type changed from "
                            f"{old.native_type} to {new.native_type} — detected as a retype."
                        ),
                    )
                )

        removed = [name for name in baseline_columns if name not in live_columns]
        added = [name for name in live_columns if name not in baseline_columns]
        paired_removed: set[str] = set()
        paired_added: set[str] = set()

        if len(removed) == 1 and len(added) == 1:
            old_name, new_name = removed[0], added[0]
            old, new = baseline_columns[old_name], live_columns[new_name]
            if old.native_type == new.native_type:
                events.append(
                    _rename_event(
                        dataset_urn,
                        old_name,
                        new_name,
                        old,
                        new,
                        _ordinal(baseline_columns, old_name),
                        _ordinal(live_columns, new_name),
                        0.95,
                        fast_path=True,
                    )
                )
                paired_removed.add(old_name)
                paired_added.add(new_name)
        else:
            candidates = _rename_candidates(removed, added, baseline_columns, live_columns)
            for _, similarity, same_type, same_ordinal, old_name, new_name in candidates:
                if old_name in paired_removed or new_name in paired_added:
                    continue
                if similarity < RENAME_SIMILARITY_THRESHOLD:
                    continue
                confidence = min(0.9, (0.5 if same_type else 0.0) + 0.4 * similarity + (0.1 if same_ordinal else 0.0))
                events.append(
                    _rename_event(
                        dataset_urn,
                        old_name,
                        new_name,
                        baseline_columns[old_name],
                        live_columns[new_name],
                        _ordinal(baseline_columns, old_name),
                        _ordinal(live_columns, new_name),
                        confidence,
                        fast_path=False,
                        similarity=similarity,
                    )
                )
                paired_removed.add(old_name)
                paired_added.add(new_name)

        for old_name in removed:
            if old_name in paired_removed:
                continue
            old = baseline_columns[old_name]
            events.append(
                declare_drift(
                    kind=DriftKind.DROP,
                    dataset_urn=dataset_urn,
                    old_column=old_name,
                    old_type=old.native_type,
                    confidence=1.0,
                    rationale=(
                        f"`{old_name}` disappeared from the live schema and no added column met the "
                        f"{RENAME_SIMILARITY_THRESHOLD:.2f} rename-similarity threshold — detected as a drop."
                    ),
                )
            )
        for new_name in added:
            if new_name in paired_added:
                continue
            new = live_columns[new_name]
            events.append(
                declare_drift(
                    kind=DriftKind.ADD,
                    dataset_urn=dataset_urn,
                    new_column=new_name,
                    new_type=new.native_type,
                    confidence=1.0,
                    rationale=(
                        f"`{new_name}` appeared in the live schema without a credible removed-column match — "
                        "detected as an add."
                    ),
                )
            )

    return sorted(events, key=lambda event: (event.dataset_name, event.id))


def declare_drift(
    *,
    kind: DriftKind | str,
    dataset_urn: str,
    old_column: str | None = None,
    new_column: str | None = None,
    old_type: str | None = None,
    new_type: str | None = None,
    confidence: float = 1.0,
    rationale: str | None = None,
    detected_at: datetime | None = None,
) -> DriftEvent:
    """Construct the same ``DriftEvent`` model from an explicit declaration."""

    normalized_kind = DriftKind(kind)
    dataset_name = _dataset_name(dataset_urn)
    subject = old_column or new_column or "schema"
    if rationale is None:
        rationale = _explicit_rationale(normalized_kind, subject, old_column, new_column, old_type, new_type)
    return DriftEvent(
        id=f"{normalized_kind.value.lower()}-{_slug(dataset_name.rsplit('.', 1)[-1])}-{_slug(subject)}",
        kind=normalized_kind,
        dataset_urn=dataset_urn,
        dataset_name=dataset_name,
        old_column=old_column,
        new_column=new_column,
        old_type=old_type,
        new_type=new_type,
        confidence=confidence,
        rationale=rationale,
        detected_at=detected_at or datetime.now(UTC),
    )


def drift_event_from_declaration(**kwargs: object) -> DriftEvent:
    """Compatibility alias for explicit UI and simulation declarations."""

    return declare_drift(**kwargs)  # type: ignore[arg-type]


def _rename_candidates(
    removed: list[str],
    added: list[str],
    baseline: dict[str, ColumnSpec],
    live: dict[str, ColumnSpec],
) -> list[tuple[tuple[int, float, int], float, bool, bool, str, str]]:
    candidates = []
    for old_name in removed:
        for new_name in added:
            same_type = baseline[old_name].native_type == live[new_name].native_type
            similarity = SequenceMatcher(None, old_name.casefold(), new_name.casefold()).ratio()
            same_ordinal = _ordinal(baseline, old_name) == _ordinal(live, new_name)
            rank = (int(same_type), similarity, int(same_ordinal))
            candidates.append((rank, similarity, same_type, same_ordinal, old_name, new_name))
    return sorted(candidates, key=lambda item: (item[0], item[4], item[5]), reverse=True)


def _rename_event(
    dataset_urn: str,
    old_name: str,
    new_name: str,
    old: ColumnSpec,
    new: ColumnSpec,
    old_ordinal: int,
    new_ordinal: int,
    confidence: float,
    *,
    fast_path: bool,
    similarity: float | None = None,
) -> DriftEvent:
    if fast_path:
        if old_ordinal == new_ordinal:
            evidence = f"the same type {old.native_type} at the same ordinal position ({old_ordinal})"
        else:
            evidence = f"the same type {old.native_type}; its ordinal position moved from {old_ordinal} to {new_ordinal}"
    else:
        type_evidence = (
            f"the same native type {old.native_type}" if old.native_type == new.native_type else "different native types"
        )
        position_evidence = (
            f"the same ordinal position ({old_ordinal})"
            if old_ordinal == new_ordinal
            else f"ordinal positions {old_ordinal} and {new_ordinal}"
        )
        evidence = f"{type_evidence}, name similarity {similarity:.2f}, and {position_evidence}"
    rationale = (
        f"`{old_name}` disappeared and `{new_name}` appeared with {evidence} — "
        f"inferred as a rename with {confidence:.2f} confidence."
    )
    return declare_drift(
        kind=DriftKind.RENAME,
        dataset_urn=dataset_urn,
        old_column=old_name,
        new_column=new_name,
        old_type=old.native_type,
        new_type=new.native_type,
        confidence=confidence,
        rationale=rationale,
    )


def _explicit_rationale(
    kind: DriftKind,
    subject: str,
    old_column: str | None,
    new_column: str | None,
    old_type: str | None,
    new_type: str | None,
) -> str:
    if kind is DriftKind.RENAME:
        return f"An explicit declaration states that `{old_column}` was renamed to `{new_column}`."
    if kind is DriftKind.RETYPE:
        return f"An explicit declaration states that `{subject}` changed type from {old_type} to {new_type}."
    if kind is DriftKind.DROP:
        return f"An explicit declaration states that upstream column `{old_column}` was dropped."
    return f"An explicit declaration states that upstream column `{new_column}` was added."


def _dataset_name(dataset_urn: str) -> str:
    try:
        return DatasetUrn.from_string(dataset_urn).name
    except ValueError as exc:
        raise ValueError(f"Invalid dataset URN {dataset_urn!r}; declare drift with a DataHub dataset URN.") from exc


def _ordinal(columns: dict[str, ColumnSpec], name: str) -> int:
    return list(columns).index(name) + 1


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "-", value.casefold()).strip("-")
