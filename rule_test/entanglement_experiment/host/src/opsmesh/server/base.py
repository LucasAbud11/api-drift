"""Base server class that all OpsMesh MCP servers derive from.

This centralizes startup/config concerns (logging, readiness) so
individual server modules only need to worry about registering their
tools/resources/prompts. There's only one concrete server today (see
``app.py``), but keeping this split out means a future split-out
service (e.g. a standalone incidents-only server) can subclass
``OpsMeshServer`` instead of ``FastMCP`` directly and inherit the same
startup behavior for free.
"""
from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from opsmesh.config import OpsMeshConfig
from opsmesh.exceptions import ServerStartupError

logger = logging.getLogger(__name__)


class OpsMeshServer(FastMCP):
    """FastMCP subclass with OpsMesh-specific startup and lifecycle hooks."""

    def __init__(self, config: OpsMeshConfig, **kwargs: Any) -> None:
        self._config = config
        self._ready = False
        super().__init__(name=config.server_name, **kwargs)
        self._configure_logging()

    @property
    def config(self) -> OpsMeshConfig:
        return self._config

    @property
    def is_ready(self) -> bool:
        return self._ready

    def _configure_logging(self) -> None:
        level = getattr(logging, self._config.log_level.upper(), logging.INFO)
        logging.getLogger("opsmesh").setLevel(level)

    def mark_ready(self) -> None:
        if self._ready:
            return
        logger.info("OpsMesh server %r is ready to accept requests", self._config.server_name)
        self._ready = True

    def run(self, *args: Any, **kwargs: Any) -> None:
        if not self._config.server_name:
            raise ServerStartupError("server_name must be set before running the server")
        self.mark_ready()
        super().run(*args, **kwargs)
