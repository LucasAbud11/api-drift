"""Builds a lightweight catalog of available tools across the fleet.

Used by the orchestrator agent to decide which tool to call and to
validate arguments before calling it, by inspecting each tool's
`inputSchema` as returned by the SDK's discovery calls.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from opsmesh.client.session_group import FleetClient

logger = logging.getLogger(__name__)


@dataclass
class CatalogedTool:
    server_name: str
    tool_name: str
    description: str
    input_schema: dict[str, Any]

    def required_arguments(self) -> list[str]:
        return list(self.input_schema.get("required", []))


class ToolCatalog:
    def __init__(self) -> None:
        self._tools: list[CatalogedTool] = []

    @classmethod
    async def build(cls, fleet: FleetClient) -> "ToolCatalog":
        catalog = cls()
        discovered = await fleet.discover_all_tools()
        for server_name, tools in discovered.items():
            for tool in tools:
                # `tool.inputSchema` is camelCase because it comes straight
                # off the wire from the SDK's discovery payload.
                catalog._tools.append(
                    CatalogedTool(
                        server_name=server_name,
                        tool_name=tool.name,
                        description=getattr(tool, "description", "") or "",
                        input_schema=getattr(tool, "inputSchema", {}) or {},
                    )
                )
        logger.debug("Built tool catalog with %d tools", len(catalog._tools))
        return catalog

    def find(self, tool_name: str) -> CatalogedTool | None:
        for tool in self._tools:
            if tool.tool_name == tool_name:
                return tool
        return None

    def by_server(self, server_name: str) -> list[CatalogedTool]:
        return [t for t in self._tools if t.server_name == server_name]

    def all(self) -> list[CatalogedTool]:
        return list(self._tools)
