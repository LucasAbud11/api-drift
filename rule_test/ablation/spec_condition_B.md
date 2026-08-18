# CONDITION B — item 3 removed (the "Context keeps its own name" line)

Identical to Condition A except the item stating that `Context` keeps its
own name is deleted outright (not softened, not hedged) and the remaining
items renumbered 1-5. Item 1's "everything that used to live there moves"
still implies Context's *import path* changes along with FastMCP's — that
much is unavoidable to state or the migration wouldn't make sense at all.
What's specifically withheld is whether `Context`, once moved, was *also*
renamed the way `FastMCP` explicitly was (item 2) — i.e. this is a
genuinely incomplete/ambiguous changelog on exactly the point that caused
the original run's 17 false positives, not a differently-worded version of
the same information.

MIGRATION SPEC — MCP Python SDK v1 → v2

The following are the ONLY confirmed changes in this migration. Anything not described below is unaffected — including things you might expect to be affected.

1. The `mcp.server.fastmcp` module path is removed entirely. Everything that used to live there moves to `mcp.server.mcpserver`. Any `from mcp.server.fastmcp import X` (or `import mcp.server.fastmcp`) must become `from mcp.server.mcpserver import X`.
2. As part of that move, the main server class itself is renamed: `FastMCP` no longer exists under that name anywhere in the package. It is renamed to `MCPServer`. Every place that imports it, uses it as a type annotation, subclasses it, or constructs it (`FastMCP(...)`) needs the identifier itself changed to `MCPServer` — this is a real rename of the class name, not just a change to where you import it from.
3. On the MCP *client* side: tool metadata objects returned by the SDK change their field-naming convention from camelCase to snake_case. Specifically `tool.inputSchema` is renamed to `tool.input_schema`. Client code reading `.inputSchema` off a discovered tool object needs to change.
4. `ClientSessionGroup.call_tool()` (the class managing calls across a *group* of client sessions) has a changed calling contract in v2. Plain `ClientSession.call_tool()` (a single session) is UNCHANGED — do not conflate the two classes.
5. Internally, the SDK's own HTTP transport dependency changed from the `httpx` package to `httpx2`. This is purely internal to the SDK's implementation and has ZERO relevance to any application code that happens to import and use the separate `httpx` package for its own purposes (e.g. making its own unrelated HTTP calls). Do not flag ordinary application-level `httpx` usage just because the word matches.

CONFIRMED UNCHANGED — do not flag any of these even though they look related:
- The `@mcp.tool()`, `@mcp.resource()`, `@mcp.prompt()` decorators — identical signature and behavior in v2.
- `.add_tool(...)` — unchanged.
- `ctx.error(...)` / `ctx.info(...)` calls that do not pass an `extra=` keyword argument — unchanged. (Calls that DO pass `extra=` have a different, changed signature, but treat plain calls without it as unaffected.)
- `get_context()` — unchanged.
- Anything imported from `mcp.types` — this subpackage remains aliased and working in v2.
