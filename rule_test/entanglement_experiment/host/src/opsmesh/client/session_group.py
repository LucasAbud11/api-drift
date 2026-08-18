"""Wrapper around mcp's ClientSessionGroup.

`FleetClient` is how the rest of the app (mainly the orchestrator)
talks to a *group* of upstream MCP servers at once, without needing to
know the SDK's session-group calling contract directly. Note that
`ClientSessionGroup.call_tool` has a different signature/contract than
`ClientSession.call_tool` (see `session.py`) - that asymmetry is
exactly why these live in two separate wrapper classes rather than one.
"""
from __future__ import annotations

import logging
from typing import Any

from mcp.client.session_group import ClientSessionGroup

from opsmesh.client.errors import UpstreamCallError
from opsmesh.client.registry import UpstreamServer

logger = logging.getLogger(__name__)


class FleetClient:
    """Aggregates calls across every registered upstream MCP server."""

    def __init__(self, group: ClientSessionGroup, servers: list[UpstreamServer]) -> None:
        self._group = group
        self._servers = {s.name: s for s in servers}

    @property
    def server_names(self) -> list[str]:
        return list(self._servers.keys())

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict[str, Any]) -> Any:
        if server_name not in self._servers:
            raise UpstreamCallError(server_name, tool_name, reason="unregistered server")
        try:
            return await self._group.call_tool(tool_name, arguments)
        except Exception as exc:  # noqa: BLE001
            logger.warning("fleet call_tool(%s.%s) failed", server_name, tool_name)
            raise UpstreamCallError(server_name, tool_name) from exc

    async def discover_all_tools(self) -> dict[str, list[Any]]:
        """Return {server_name: [tool, ...]} for every registered server."""
        discovered: dict[str, list[Any]] = {}
        for name in self._servers:
            discovered[name] = await self._group.list_tools()
        return discovered
