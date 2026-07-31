"""Provider-neutral pull-request interface."""

from __future__ import annotations

from typing import Protocol

from repair_agent.models import PRRequest, PullRequestResult


class PRProvider(Protocol):
    """Open a live or dry-run pull request from an immutable request payload."""

    def open_pr(self, request: PRRequest) -> PullRequestResult:
        """Create the requested review surface and return its stable location."""

