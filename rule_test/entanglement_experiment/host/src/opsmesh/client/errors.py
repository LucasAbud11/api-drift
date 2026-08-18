"""Client-side error types.

Kept separate from `opsmesh.exceptions` because upstream-call failures
carry extra structured context (which server, which tool) that's only
relevant on the client side.
"""
from __future__ import annotations

from opsmesh.exceptions import OpsMeshError


class UpstreamCallError(OpsMeshError):
    """Raised when a call to an upstream MCP server fails."""

    def __init__(self, server_name: str, tool_name: str, *, reason: str | None = None) -> None:
        self.server_name = server_name
        self.tool_name = tool_name
        self.reason = reason
        message = f"call to {tool_name!r} on upstream server {server_name!r} failed"
        if reason:
            message += f": {reason}"
        super().__init__(message)
