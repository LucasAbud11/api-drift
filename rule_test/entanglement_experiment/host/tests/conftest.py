"""Shared pytest fixtures.

We mock the `mcp` SDK objects rather than requiring a live server for
most tests - only a couple of integration-flavored tests spin up
anything resembling a real session.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from opsmesh.config import OpsMeshConfig, UpstreamServerSpec


@pytest.fixture
def config() -> OpsMeshConfig:
    return OpsMeshConfig(
        server_name="opsmesh-test",
        log_level="DEBUG",
        upstream_servers=[
            UpstreamServerSpec(name="docs-mcp", url="http://localhost:9001", description="internal docs"),
        ],
    )


@pytest.fixture
def mock_context():
    ctx = MagicMock()
    ctx.error = AsyncMock()
    ctx.info = AsyncMock()
    return ctx


@pytest.fixture
def mock_client_session():
    session = MagicMock()
    session.call_tool = AsyncMock(return_value={"ok": True})
    session.list_tools = AsyncMock(return_value=[])
    return session


@pytest.fixture
def mock_session_group():
    group = MagicMock()
    group.call_tool = AsyncMock(return_value={"ok": True})
    group.list_tools = AsyncMock(return_value=[])
    return group
