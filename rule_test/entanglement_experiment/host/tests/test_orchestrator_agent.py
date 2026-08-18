"""Tests for the tool catalog + orchestrator's naive tool-routing logic.

These stay at the unit level - they don't exercise a real
ClientSessionGroup, just the FleetClient/ToolCatalog layers on top.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from opsmesh.client.registry import UpstreamServer
from opsmesh.client.session_group import FleetClient
from opsmesh.orchestrator.tool_catalog import ToolCatalog


def _fake_tool(name: str, description: str, schema: dict):
    return SimpleNamespace(name=name, description=description, inputSchema=schema)


@pytest.mark.asyncio
async def test_tool_catalog_build_reads_input_schema(mock_session_group):
    mock_session_group.list_tools.return_value = [
        _fake_tool(
            "get_deployment_status",
            "Return the most recent deployment for a service",
            {"type": "object", "required": ["service"], "properties": {"service": {"type": "string"}}},
        )
    ]
    servers = [UpstreamServer(name="opsmesh", url="http://localhost:8765", description="")]
    fleet = FleetClient(mock_session_group, servers)

    catalog = await ToolCatalog.build(fleet)

    tool = catalog.find("get_deployment_status")
    assert tool is not None
    assert tool.required_arguments() == ["service"]


@pytest.mark.asyncio
async def test_tool_catalog_by_server(mock_session_group):
    mock_session_group.list_tools.return_value = [
        _fake_tool("search_runbooks", "search", {}),
    ]
    servers = [UpstreamServer(name="opsmesh", url="http://localhost:8765", description="")]
    fleet = FleetClient(mock_session_group, servers)

    catalog = await ToolCatalog.build(fleet)

    assert len(catalog.by_server("opsmesh")) == 1
    assert catalog.by_server("nonexistent") == []
