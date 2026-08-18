# OpsMesh

OpsMesh is an internal developer-platform service that exposes a slice
of our operational tooling — deployment status, open incidents, the
service catalog, and runbook search — to AI agents over the Model
Context Protocol (MCP). It also ships a small client-side
orchestrator that can fan a question out across OpsMesh's own tools
*and* other internal MCP servers (docs search, GitHub, PagerDuty-style
integrations) registered in its upstream server list.

## Why this exists

Engineers already ask "is billing-api's latest deploy healthy?" or
"what incidents are open on notifications-worker?" in Slack. OpsMesh
lets an LLM-backed assistant answer those questions directly against
live data instead of stale runbook screenshots, without engineers
having to memorize which internal API each question maps to.

## Architecture

```
                +-------------------+
   AI client -> |  OpsMesh MCP      |  server/ (FastMCP subclass)
   (Claude,     |  server           |    tools/  - deployment, incident,
    Cursor,     |                   |              catalog, runbook tools
    etc.)       +-------------------+    resources.py, prompts.py

   opsmesh ask  +-------------------+
   (CLI) -----> |  Orchestrator      |  orchestrator/
                |  agent             |    talks to a *fleet* of MCP
                +-------------------+    servers via client/
                          |
                          v
                +-------------------+
                |  FleetClient /     |  client/ (wraps mcp SDK client
                |  OpsMeshClient     |  objects - see below)
                +-------------------+
```

- **`opsmesh.server.base.OpsMeshServer`** subclasses
  `mcp.server.fastmcp.FastMCP` to centralize startup/config/logging
  concerns. `opsmesh.server.app.create_server()` builds the concrete
  instance and registers all tools/resources/prompts on it.
- **`opsmesh.client.session.OpsMeshClient`** wraps a single
  `mcp.client.session.ClientSession`.
- **`opsmesh.client.session_group.FleetClient`** wraps
  `mcp.client.session_group.ClientSessionGroup` to call tools across
  every registered upstream MCP server.
- **`opsmesh.orchestrator`** sits on top of `FleetClient` to answer
  free-text questions by picking a relevant tool from a catalog built
  from each server's `list_tools()` discovery response (using each
  tool's `inputSchema`).

Application code elsewhere in the repo is expected to import
`OpsMeshClient` / `FleetClient` from `opsmesh.client`, not
`mcp.client.session` / `mcp.client.session_group` directly.

## Getting started

```bash
pip install -e ".[dev]"
opsmesh serve                 # start the MCP server over stdio
opsmesh ask "is billing-api healthy?"
```

Configuration is loaded from environment variables (prefixed
`OPSMESH_`, e.g. `OPSMESH_LOG_LEVEL=DEBUG`) and optionally a YAML file
passed via `--config`. See `opsmesh.config.OpsMeshConfig` for the full
set of fields, including the `upstream_servers` list used by the
orchestrator.

## Running tests

```bash
pytest
```

Most tests mock the `mcp` SDK's client/server objects directly rather
than requiring a live server, so they run fast and don't need network
access.

## Layout

```
src/opsmesh/
  config.py, logging_setup.py, exceptions.py, cli.py
  server/            MCP server: FastMCP subclass + tool/resource/prompt registration
  client/            Wrappers around mcp's client-side session objects
  orchestrator/       Fleet-wide question answering on top of client/
  integrations/       Plain HTTP clients (GitHub) unrelated to MCP
tests/               pytest suite, mocks mcp SDK objects
```
