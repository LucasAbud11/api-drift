"""Incident-lookup tools.

Written in a slightly more object-oriented style than
`deployments.py` - this module owns a small in-memory `IncidentStore`
that a real deployment would swap out for a call to an incident
management backend.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from opsmesh.server.context import current_context, report_info


@dataclass
class Incident:
    id: str
    service: str
    severity: str
    summary: str
    opened_at: dt.datetime
    resolved: bool = False


class IncidentStore:
    def __init__(self) -> None:
        self._incidents: list[Incident] = []
        self._seed()

    def _seed(self) -> None:
        now = dt.datetime.now(dt.timezone.utc)
        self._incidents.extend(
            [
                Incident(
                    id="INC-1042",
                    service="billing-api",
                    severity="sev2",
                    summary="Elevated 5xx rate after 2.14.1 rollout",
                    opened_at=now - dt.timedelta(hours=2, minutes=45),
                    resolved=False,
                ),
                Incident(
                    id="INC-1039",
                    service="notifications-worker",
                    severity="sev3",
                    summary="Delayed email delivery, backlog draining",
                    opened_at=now - dt.timedelta(days=2),
                    resolved=True,
                ),
            ]
        )

    def recent(self, service: str | None = None, *, include_resolved: bool = False) -> list[Incident]:
        results = self._incidents
        if service is not None:
            results = [i for i in results if i.service == service]
        if not include_resolved:
            results = [i for i in results if not i.resolved]
        return sorted(results, key=lambda i: i.opened_at, reverse=True)


_store = IncidentStore()


def register(mcp) -> None:
    @mcp.tool()
    async def list_recent_incidents(service: str = "", include_resolved: bool = False) -> list[dict]:
        """List recent incidents, optionally filtered to a single service."""
        ctx = current_context()
        incidents = _store.recent(service or None, include_resolved=include_resolved)
        await report_info(ctx, f"Returning {len(incidents)} incident(s)")
        return [
            {
                "id": i.id,
                "service": i.service,
                "severity": i.severity,
                "summary": i.summary,
                "opened_at": i.opened_at.isoformat(),
                "resolved": i.resolved,
            }
            for i in incidents
        ]
