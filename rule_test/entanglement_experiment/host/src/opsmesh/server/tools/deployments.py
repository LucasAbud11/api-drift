"""Deployment-status tools exposed to MCP clients."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from opsmesh.exceptions import ToolExecutionError
from opsmesh.server.context import current_context, report_error, report_info


@dataclass
class DeploymentRecord:
    service: str
    version: str
    environment: str
    deployed_at: dt.datetime
    deployed_by: str


_DEPLOYMENT_LOG: dict[str, DeploymentRecord] = {}


def _seed_demo_data() -> None:
    if _DEPLOYMENT_LOG:
        return
    now = dt.datetime.now(dt.timezone.utc)
    _DEPLOYMENT_LOG["billing-api"] = DeploymentRecord(
        service="billing-api",
        version="2.14.1",
        environment="production",
        deployed_at=now - dt.timedelta(hours=3),
        deployed_by="ci-bot",
    )
    _DEPLOYMENT_LOG["notifications-worker"] = DeploymentRecord(
        service="notifications-worker",
        version="0.9.7",
        environment="production",
        deployed_at=now - dt.timedelta(days=1, hours=2),
        deployed_by="jordan",
    )


def register(mcp) -> None:
    """Register deployment tools on the given OpsMeshServer instance."""
    _seed_demo_data()

    @mcp.tool()
    async def get_deployment_status(service: str) -> dict:
        """Return the most recent deployment record for a service."""
        ctx = current_context()
        record = _DEPLOYMENT_LOG.get(service)
        if record is None:
            await report_error(ctx, f"No deployment records found for service {service!r}")
            raise ToolExecutionError(f"unknown service: {service}")
        await report_info(ctx, f"Fetched deployment status for {service}")
        return {
            "service": record.service,
            "version": record.version,
            "environment": record.environment,
            "deployed_at": record.deployed_at.isoformat(),
            "deployed_by": record.deployed_by,
        }

    async def trigger_rollback(service: str, target_version: str) -> dict:
        """Roll a service back to a previously known-good version."""
        ctx = current_context()
        record = _DEPLOYMENT_LOG.get(service)
        if record is None:
            raise ToolExecutionError(f"unknown service: {service}")
        record.version = target_version
        await report_info(ctx, f"Rolled {service} back to {target_version}")
        return {"service": service, "version": target_version, "status": "rolled_back"}

    # Registered imperatively (rather than with @mcp.tool()) because the
    # CLI's `opsmesh rollback` command also wants a plain reference to
    # this function to call directly in tests without going through MCP.
    mcp.add_tool(trigger_rollback)
