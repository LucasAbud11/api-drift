"""Thin helpers around mcp's per-request Context.

Handlers should generally go through these helpers instead of importing
``mcp.server.fastmcp.get_context`` directly, so we have one place to add
things like structured logging or request-id tagging later without
touching every tool module.
"""
from __future__ import annotations

import logging

from mcp.server.fastmcp import Context
from mcp.server.fastmcp import get_context as _mcp_get_context

logger = logging.getLogger(__name__)


def current_context() -> Context:
    """Return the active request Context, raising a clear error if unavailable."""
    ctx = _mcp_get_context()
    if ctx is None:
        raise RuntimeError("current_context() called outside of a request handler")
    return ctx


async def report_error(ctx: Context, message: str, *, exc: Exception | None = None) -> None:
    """Log locally and notify the connected client of an error."""
    if exc is not None:
        logger.exception(message)
    else:
        logger.error(message)
    await ctx.error(message)


async def report_info(ctx: Context, message: str) -> None:
    logger.info(message)
    await ctx.info(message)
