"""Wrapper around a single mcp ClientSession.

Application code should import `OpsMeshClient` from here rather than
constructing `mcp.client.session.ClientSession` directly, so we have a
single place to add retry/logging/error-translation behavior.
"""
from __future__ import annotations

import logging
from typing import Any

from mcp.client.session import ClientSession

from opsmesh.client.errors import UpstreamCallError

logger = logging.getLogger(__name__)


class OpsMeshClient:
    """A thin, app-flavored wrapper around a single `ClientSession`."""

    def __init__(self, session: ClientSession, *, server_label: str) -> None:
        self._session = session
        self._server_label = server_label

    @property
    def raw_session(self) -> ClientSession:
        """Escape hatch for callers that need the underlying SDK object."""
        return self._session

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        try:
            result = await self._session.call_tool(name, arguments or {})
        except Exception as exc:  # noqa: BLE001 - translated below
            logger.warning("call_tool(%s) failed against %s", name, self._server_label)
            raise UpstreamCallError(self._server_label, name) from exc
        return result

    async def list_tools(self) -> Any:
        return await self._session.list_tools()
