"""MCP resources exposed by OpsMesh.

Currently just the service catalog, addressable as
``catalog://{service}``.
"""
from __future__ import annotations

from opsmesh.server.tools.service_catalog import CATALOG


def register(mcp) -> None:
    @mcp.resource("catalog://{service}")
    def service_catalog_entry(service: str) -> str:
        """Return a human-readable catalog entry for a service."""
        entry = CATALOG.get(service)
        if entry is None:
            return f"No catalog entry for {service!r}."
        return (
            f"Service: {service}\n"
            f"Owner: {entry['owner']}\n"
            f"Repo: {entry['repo']}\n"
            f"Tier: {entry['tier']}"
        )
