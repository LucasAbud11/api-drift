"""Tests for FleetClient, the wrapper around mcp's ClientSessionGroup."""
from __future__ import annotations

import pytest

from opsmesh.client.errors import UpstreamCallError
from opsmesh.client.registry import UpstreamServer
from opsmesh.client.session_group import FleetClient


@pytest.fixture
def servers():
    return [
        UpstreamServer(name="opsmesh", url="http://localhost:8765", description="self"),
        UpstreamServer(name="docs-mcp", url="http://localhost:9001", description="docs"),
    ]


@pytest.mark.asyncio
async def test_call_tool_against_known_server(mock_session_group, servers):
    fleet = FleetClient(mock_session_group, servers)
    result = await fleet.call_tool("docs-mcp", "search_docs", {"query": "rollback"})
    mock_session_group.call_tool.assert_awaited_once_with("search_docs", {"query": "rollback"})
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_call_tool_against_unregistered_server_raises(mock_session_group, servers):
    fleet = FleetClient(mock_session_group, servers)
    with pytest.raises(UpstreamCallError):
        await fleet.call_tool("unknown-server", "search_docs", {})


def test_server_names(mock_session_group, servers):
    fleet = FleetClient(mock_session_group, servers)
    assert fleet.server_names == ["opsmesh", "docs-mcp"]
