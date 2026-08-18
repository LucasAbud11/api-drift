"""Client-side wrappers around the mcp SDK's client objects.

Application code (mainly `opsmesh.orchestrator`) should import
`OpsMeshClient` and `FleetClient` from here rather than reaching into
`mcp.client.session` / `mcp.client.session_group` directly.
"""
from opsmesh.client.session import OpsMeshClient
from opsmesh.client.session_group import FleetClient

__all__ = ["OpsMeshClient", "FleetClient"]
