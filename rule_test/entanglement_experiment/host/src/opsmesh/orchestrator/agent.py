"""A small orchestrator agent that answers free-text questions by
calling tools across the fleet of registered MCP servers.

This is intentionally simple - no LLM call is wired in here, just the
plumbing an LLM-backed agent would sit on top of (connect, discover
tools, call tools, format an answer). Swapping in a real model call is
left as an exercise.
"""
from __future__ import annotations

import logging

from mcp.client.session_group import ClientSessionGroup

from opsmesh.client.registry import build_registry
from opsmesh.client.session_group import FleetClient
from opsmesh.config import OpsMeshConfig
from opsmesh.orchestrator.tool_catalog import ToolCatalog

logger = logging.getLogger(__name__)


class OrchestratorAgent:
    def __init__(self, fleet: FleetClient, catalog: ToolCatalog, *, group: ClientSessionGroup) -> None:
        self._fleet = fleet
        self._catalog = catalog
        self._group = group

    @classmethod
    async def connect(cls, config: OpsMeshConfig) -> "OrchestratorAgent":
        """Establish the raw ClientSessionGroup connection and wrap it.

        This is the one place in the app that touches
        `mcp.client.session_group.ClientSessionGroup` directly; every
        other call site goes through the `FleetClient` wrapper built
        here.
        """
        servers = build_registry(config)
        group = ClientSessionGroup()
        await group.__aenter__()
        fleet = FleetClient(group, servers)
        catalog = await ToolCatalog.build(fleet)
        logger.info("Orchestrator connected to %d upstream server(s)", len(servers))
        return cls(fleet, catalog, group=group)

    async def close(self) -> None:
        await self._group.__aexit__(None, None, None)

    async def ask(self, question: str) -> str:
        """Very small heuristic router: pick a tool whose name/description
        looks relevant to the question and call it.
        """
        question_lower = question.lower()
        candidate = None
        for tool in self._catalog.all():
            haystack = f"{tool.tool_name} {tool.description}".lower()
            if any(word in haystack for word in question_lower.split()):
                candidate = tool
                break

        if candidate is None:
            return "I couldn't find a relevant tool to answer that question."

        args = self._extract_arguments(candidate, question)
        result = await self._fleet.call_tool(candidate.server_name, candidate.tool_name, args)
        return f"[{candidate.server_name}.{candidate.tool_name}] {result}"

    def _extract_arguments(self, tool: "object", question: str) -> dict:
        # Extremely naive: just try to find a service-like token (one
        # containing a hyphen) in the question for any tool whose schema
        # requires a `service` field.
        args: dict = {}
        if "service" in tool.required_arguments():
            for token in question.replace("?", "").split():
                if "-" in token:
                    args["service"] = token
                    break
        return args
