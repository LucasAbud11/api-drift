"""Concrete OpsMesh MCP server: wires config -> OpsMeshServer -> tool/resource/prompt registration."""
from __future__ import annotations

import logging

from opsmesh.config import OpsMeshConfig
from opsmesh.server import prompts, resources
from opsmesh.server.base import OpsMeshServer
from opsmesh.server.tools import deployments, incidents, runbooks, service_catalog

logger = logging.getLogger(__name__)


def create_server(config: OpsMeshConfig | None = None) -> OpsMeshServer:
    """Build a fully-wired OpsMeshServer instance ready to `.run()`."""
    config = config or OpsMeshConfig.load()
    server = OpsMeshServer(config)

    deployments.register(server)
    incidents.register(server)
    service_catalog.register(server)
    runbooks.register(server)
    resources.register(server)
    prompts.register(server)

    logger.info("Registered OpsMesh tools/resources/prompts for %s", config.server_name)
    return server
