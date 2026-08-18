"""Tests for OpsMeshServer (the FastMCP subclass)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from opsmesh.config import OpsMeshConfig
from opsmesh.exceptions import ServerStartupError
from opsmesh.server.base import OpsMeshServer


def test_mark_ready_is_idempotent(config: OpsMeshConfig):
    server = OpsMeshServer(config)
    assert not server.is_ready
    server.mark_ready()
    assert server.is_ready
    server.mark_ready()  # should not raise or double-log
    assert server.is_ready


def test_run_raises_without_server_name(config: OpsMeshConfig):
    config.server_name = ""
    server = OpsMeshServer(config)
    with pytest.raises(ServerStartupError):
        server.run()


def test_run_marks_ready_and_delegates_to_fastmcp(config: OpsMeshConfig):
    server = OpsMeshServer(config)
    with patch("mcp.server.fastmcp.FastMCP.run") as fastmcp_run:
        server.run()
    assert server.is_ready
    fastmcp_run.assert_called_once()
