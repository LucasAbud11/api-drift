"""Tests for OpsMeshClient, the wrapper around mcp's ClientSession."""
from __future__ import annotations

import pytest

from opsmesh.client.errors import UpstreamCallError
from opsmesh.client.session import OpsMeshClient


@pytest.mark.asyncio
async def test_call_tool_delegates_to_session(mock_client_session):
    client = OpsMeshClient(mock_client_session, server_label="opsmesh")
    result = await client.call_tool("get_deployment_status", {"service": "billing-api"})
    mock_client_session.call_tool.assert_awaited_once_with(
        "get_deployment_status", {"service": "billing-api"}
    )
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_call_tool_wraps_session_errors(mock_client_session):
    mock_client_session.call_tool.side_effect = RuntimeError("boom")
    client = OpsMeshClient(mock_client_session, server_label="opsmesh")
    with pytest.raises(UpstreamCallError):
        await client.call_tool("get_deployment_status")


def test_raw_session_escape_hatch(mock_client_session):
    client = OpsMeshClient(mock_client_session, server_label="opsmesh")
    assert client.raw_session is mock_client_session
