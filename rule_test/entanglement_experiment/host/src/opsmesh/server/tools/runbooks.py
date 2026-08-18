"""Runbook search tool - naive substring search over a small static index.

A real implementation would hit an internal docs-search backend; this
keeps things dependency-free for the example.
"""
from __future__ import annotations

from opsmesh.server.context import current_context

_RUNBOOKS = [
    {
        "title": "Billing API elevated error rate",
        "tags": ["billing-api", "5xx", "rollback"],
        "url": "https://runbooks.internal/billing-api-5xx",
    },
    {
        "title": "Notifications worker backlog drain",
        "tags": ["notifications-worker", "queue", "backlog"],
        "url": "https://runbooks.internal/notifications-backlog",
    },
    {
        "title": "Auth gateway cert rotation",
        "tags": ["auth-gateway", "tls", "certs"],
        "url": "https://runbooks.internal/auth-gateway-cert-rotation",
    },
]


def register(mcp) -> None:
    @mcp.tool()
    async def search_runbooks(query: str) -> list[dict]:
        """Search runbook titles/tags for a query string."""
        current_context()
        query_lower = query.lower()
        matches = [
            rb
            for rb in _RUNBOOKS
            if query_lower in rb["title"].lower() or any(query_lower in t for t in rb["tags"])
        ]
        return matches
