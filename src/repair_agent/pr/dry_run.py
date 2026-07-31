"""Safe default PR provider that writes exact review artifacts locally."""

from __future__ import annotations

import json
import re
from pathlib import Path

from repair_agent.models import PRRequest, PullRequestResult


class DryRunPRProvider:
    """Persist the complete PR body and machine-readable request without git writes."""

    def __init__(self, output_dir: Path | str, *, repo_root: Path | str | None = None) -> None:
        self.output_dir = Path(output_dir)
        self.repo_root = Path(repo_root).resolve() if repo_root is not None else None

    def open_pr(self, request: PRRequest) -> PullRequestResult:
        """Write the exact body and payload used by the live provider."""

        self.output_dir.mkdir(parents=True, exist_ok=True)
        artifact_id = _artifact_id(request.branch)
        body_path = self.output_dir / f"{artifact_id}.md"
        payload_path = self.output_dir / f"{artifact_id}.payload.json"
        body_path.write_text(request.body_markdown, encoding="utf-8")
        payload = {
            "branch": request.branch,
            "base": request.base,
            "title": request.title,
            "commit_message": request.commit_message,
            "files": [change.path for change in request.files],
        }
        payload_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return PullRequestResult(
            mode="dry-run",
            url=self._artifact_reference(body_path),
            branch=request.branch,
            title=request.title,
            files=payload["files"],
        )

    def _artifact_reference(self, body_path: Path) -> str:
        if self.repo_root is not None:
            try:
                return body_path.resolve().relative_to(self.repo_root).as_posix()
            except ValueError:
                pass
        return body_path.name


def _artifact_id(branch: str) -> str:
    leaf = branch.removeprefix("repair/").strip("/") or "repair"
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", leaf)
