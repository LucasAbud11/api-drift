"""Service-catalog lookup tool - who owns what.

`CATALOG` is left public (rather than prefixed `_CATALOG`) because
`opsmesh.server.resources` also renders it as a readable MCP resource.
"""
from __future__ import annotations

from opsmesh.server.context import current_context

CATALOG = {
    "billing-api": {"owner": "team-payments", "repo": "github.com/acme/billing-api", "tier": 1},
    "notifications-worker": {
        "owner": "team-comms",
        "repo": "github.com/acme/notifications-worker",
        "tier": 2,
    },
    "auth-gateway": {"owner": "team-identity", "repo": "github.com/acme/auth-gateway", "tier": 0},
}


def register(mcp) -> None:
    @mcp.tool()
    async def get_service_owner(service: str) -> dict:
        """Look up the owning team, repo, and criticality tier for a service."""
        current_context()  # validates we're inside a request; raises otherwise
        entry = CATALOG.get(service)
        if entry is None:
            return {"service": service, "owner": None, "found": False}
        return {"service": service, "found": True, **entry}
