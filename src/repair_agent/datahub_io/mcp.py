"""OpenAI Agents SDK MCP server factory for DataHub reads."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from repair_agent.config import Settings, get_settings


def build_datahub_mcp_server(settings: Settings | None = None) -> Any:
    """Build the pinned DataHub stdio MCP server without importing Agents SDK eagerly."""

    from agents.mcp import MCPServerStdio

    config = settings or get_settings()
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "DATAHUB_GMS_URL": config.datahub_gms_url,
        "TOOLS_IS_MUTATION_ENABLED": "true",
        "DATAHUB_TELEMETRY_ENABLED": "false",
        "UV_TOOL_DIR": os.environ.get(
            "UV_TOOL_DIR",
            str(Path(tempfile.gettempdir()) / "repair-agent-uv-tools"),
        ),
    }
    if os.environ.get("UV_CACHE_DIR"):
        environment["UV_CACHE_DIR"] = os.environ["UV_CACHE_DIR"]
    if config.datahub_gms_token:
        environment["DATAHUB_GMS_TOKEN"] = config.datahub_gms_token

    return MCPServerStdio(
        params={
            "command": "uvx",
            "args": [f"mcp-server-datahub=={config.mcp_server_version}"],
            "env": environment,
        },
        cache_tools_list=True,
        client_session_timeout_seconds=120,
    )
