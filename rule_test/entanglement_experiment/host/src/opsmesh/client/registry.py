"""Registry of upstream MCP servers the orchestrator can fan out to."""
from __future__ import annotations

from dataclasses import dataclass

from opsmesh.config import OpsMeshConfig


@dataclass(frozen=True)
class UpstreamServer:
    name: str
    url: str
    description: str


def build_registry(config: OpsMeshConfig) -> list[UpstreamServer]:
    """Translate config-level server specs into registry entries.

    Always includes OpsMesh's own server (self-registration), so the
    orchestrator can call OpsMesh's own tools the same way it calls
    any other upstream server.
    """
    servers = [
        UpstreamServer(
            name="opsmesh",
            url=f"http://{config.host}:{config.port}",
            description="OpsMesh's own deployment/incident/catalog tools",
        )
    ]
    for spec in config.upstream_servers:
        servers.append(UpstreamServer(name=spec.name, url=spec.url, description=spec.description))
    return servers
