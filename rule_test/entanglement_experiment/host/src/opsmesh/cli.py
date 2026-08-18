"""Command-line entry point for OpsMesh.

Thin by design - most logic lives in the server/client/orchestrator
modules. This just wires config loading + logging + subcommands
together.
"""
from __future__ import annotations

import asyncio
import sys

import click

from opsmesh.config import OpsMeshConfig
from opsmesh.logging_setup import configure_logging
from opsmesh.server.app import create_server


@click.group()
@click.option("--config", "config_path", default=None, help="Path to a YAML config file.")
@click.pass_context
def main(ctx: click.Context, config_path: str | None) -> None:
    """OpsMesh: internal platform tooling exposed to AI agents over MCP."""
    cfg = OpsMeshConfig.load(config_path)
    configure_logging(cfg.log_level)
    ctx.obj = cfg


@main.command()
@click.pass_obj
def serve(cfg: OpsMeshConfig) -> None:
    """Start the OpsMesh MCP server (stdio transport)."""
    server = create_server(cfg)
    server.run()


@main.command()
@click.argument("question")
@click.pass_obj
def ask(cfg: OpsMeshConfig, question: str) -> None:
    """Ask the orchestrator agent a question, fanning out to upstream servers."""
    from opsmesh.orchestrator.agent import OrchestratorAgent

    async def _run() -> None:
        agent = await OrchestratorAgent.connect(cfg)
        try:
            answer = await agent.ask(question)
            click.echo(answer)
        finally:
            await agent.close()

    try:
        asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
