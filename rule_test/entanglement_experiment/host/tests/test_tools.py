"""Tests for the deployment/incident/runbook tool handlers.

These call the registered handler functions directly (unwrapped from
the FastMCP decorator by capturing them via a fake `mcp` object),
rather than spinning up a real FastMCP server.
"""
from __future__ import annotations

import pytest

from opsmesh.server.tools import deployments, incidents, runbooks


class _FakeMCP:
    """Captures whatever `@mcp.tool()` / `mcp.add_tool()` registers."""

    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator

    def add_tool(self, fn):
        self.tools[fn.__name__] = fn


@pytest.fixture
def fake_mcp():
    return _FakeMCP()


@pytest.mark.asyncio
async def test_get_deployment_status_known_service(fake_mcp, mock_context, monkeypatch):
    deployments.register(fake_mcp)
    monkeypatch.setattr("opsmesh.server.tools.deployments.current_context", lambda: mock_context)
    result = await fake_mcp.tools["get_deployment_status"]("billing-api")
    assert result["service"] == "billing-api"
    assert result["environment"] == "production"


@pytest.mark.asyncio
async def test_get_deployment_status_unknown_service_raises(fake_mcp, mock_context, monkeypatch):
    from opsmesh.exceptions import ToolExecutionError

    deployments.register(fake_mcp)
    monkeypatch.setattr("opsmesh.server.tools.deployments.current_context", lambda: mock_context)
    with pytest.raises(ToolExecutionError):
        await fake_mcp.tools["get_deployment_status"]("does-not-exist")
    mock_context.error.assert_awaited()


@pytest.mark.asyncio
async def test_trigger_rollback_updates_version(fake_mcp, mock_context, monkeypatch):
    deployments.register(fake_mcp)
    monkeypatch.setattr("opsmesh.server.tools.deployments.current_context", lambda: mock_context)
    result = await fake_mcp.tools["trigger_rollback"]("billing-api", "2.13.0")
    assert result["status"] == "rolled_back"
    assert result["version"] == "2.13.0"


@pytest.mark.asyncio
async def test_list_recent_incidents_filters_resolved(fake_mcp, mock_context, monkeypatch):
    incidents.register(fake_mcp)
    monkeypatch.setattr("opsmesh.server.tools.incidents.current_context", lambda: mock_context)
    result = await fake_mcp.tools["list_recent_incidents"]()
    assert all(not i["resolved"] for i in result)


@pytest.mark.asyncio
async def test_search_runbooks_matches_tag(fake_mcp, mock_context, monkeypatch):
    runbooks.register(fake_mcp)
    monkeypatch.setattr("opsmesh.server.tools.runbooks.current_context", lambda: mock_context)
    matches = await fake_mcp.tools["search_runbooks"]("5xx")
    assert any("Billing API" in m["title"] for m in matches)
