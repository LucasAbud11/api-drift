"""Shared exception hierarchy for OpsMesh.

Application code should raise these (or subclasses) rather than
letting raw SDK/library exceptions leak across module boundaries -
that keeps the CLI and orchestrator's error-handling logic simple.
"""
from __future__ import annotations


class OpsMeshError(Exception):
    """Base class for all OpsMesh-specific errors."""


class ConfigError(OpsMeshError):
    """Raised when configuration is missing or malformed."""


class ServerStartupError(OpsMeshError):
    """Raised when the MCP server cannot start due to bad state."""


class ToolExecutionError(OpsMeshError):
    """Raised by a tool handler when it cannot fulfill a request."""
