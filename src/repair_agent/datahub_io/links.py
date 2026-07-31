"""Canonical DataHub frontend links for every entity type the repair agent emits."""

from __future__ import annotations

from urllib.parse import quote

_ENTITY_ROUTES = {
    "urn:li:dataset:": "dataset",
    "urn:li:dataJob:": "tasks",
    "urn:li:dataFlow:": "pipelines",
    "urn:li:dataProcessInstance:": "dataProcessInstance",
    "urn:li:tag:": "tag",
}


def datahub_entity_url(frontend_url: str, urn: str, *, suffix: str = "") -> str:
    """Return the DataHub UI route for ``urn`` with a safely encoded identifier."""

    route = next((path for prefix, path in _ENTITY_ROUTES.items() if urn.startswith(prefix)), None)
    if route is None:
        raise ValueError(f"No DataHub frontend route is registered for entity URN {urn!r}.")
    normalized_suffix = f"/{suffix.lstrip('/')}" if suffix else ""
    return f"{frontend_url.rstrip('/')}/{route}/{quote(urn, safe='')}{normalized_suffix}"
