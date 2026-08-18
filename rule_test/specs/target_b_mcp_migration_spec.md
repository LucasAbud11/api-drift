# MIGRATION SPEC — MCP Python SDK v1 → v2

(As given verbatim to each Target B detection agent on 2026-08-18. The
original session's spec text was never persisted anywhere on disk, so this
is a reconstruction — written by the orchestrator from the confirmed-changed
/ confirmed-unchanged facts already stated in `ground_truth.md`, which the
agents never saw. **Item 3 below states outright that `Context` keeps its
own name** — this is the exact fact whose absence (or ambiguity) is the
documented explanation for the original run's 17 false positives. Because
this spec states it directly, this is not a like-for-like replay of
whatever the original agents were given. See `rule_test.md` for the full
disclosure of what that implies for this run's near-perfect result.)

The following are the ONLY confirmed changes in this migration. Anything
not described below is unaffected — including things you might expect to
be affected.

1. The `mcp.server.fastmcp` module path is removed entirely. Everything
   that used to live there moves to `mcp.server.mcpserver`. Any `from
   mcp.server.fastmcp import X` (or `import mcp.server.fastmcp`) must
   become `from mcp.server.mcpserver import X`.
2. As part of that move, the main server class itself is renamed:
   `FastMCP` no longer exists under that name anywhere in the package. It
   is renamed to `MCPServer`. Every place that imports it, uses it as a
   type annotation, subclasses it, or constructs it (`FastMCP(...)`) needs
   the identifier itself changed to `MCPServer` — this is a real rename of
   the class name, not just a change to where you import it from.
3. The `Context` class moves along with the rest of the module (same
   import-path change as above: `from mcp.server.fastmcp import Context`
   → `from mcp.server.mcpserver import Context`), but `Context` keeps its
   own name. Nothing else about `Context` — its methods, its behavior, how
   it's used as a type annotation elsewhere — changes.
4. On the MCP *client* side: tool metadata objects returned by the SDK
   change their field-naming convention from camelCase to snake_case.
   Specifically `tool.inputSchema` is renamed to `tool.input_schema`.
   Client code reading `.inputSchema` off a discovered tool object needs
   to change.
5. `ClientSessionGroup.call_tool()` (the class managing calls across a
   *group* of client sessions) has a changed calling contract in v2. Plain
   `ClientSession.call_tool()` (a single session) is UNCHANGED — do not
   conflate the two classes.
6. Internally, the SDK's own HTTP transport dependency changed from the
   `httpx` package to `httpx2`. This is purely internal to the SDK's
   implementation and has ZERO relevance to any application code that
   happens to import and use the separate `httpx` package for its own
   purposes (e.g. making its own unrelated HTTP calls). Do not flag
   ordinary application-level `httpx` usage just because the word matches.

CONFIRMED UNCHANGED — do not flag any of these even though they look
related:
- The `@mcp.tool()`, `@mcp.resource()`, `@mcp.prompt()` decorators —
  identical signature and behavior in v2.
- `.add_tool(...)` — unchanged.
- `ctx.error(...)` / `ctx.info(...)` calls that do not pass an `extra=`
  keyword argument — unchanged. (Calls that DO pass `extra=` have a
  different, changed signature, but treat plain calls without it as
  unaffected.)
- `get_context()` — unchanged.
- Anything imported from `mcp.types` — this subpackage remains aliased and
  working in v2.

TASK: Find every call site in the assigned repository that needs to be
edited because of this migration. This includes sites reached indirectly
through the repo's own helper functions and test files — trace call
chains and check tests, don't just grep the entry point file. For each
site, report the file (relative to repo root), line number, the exact
code snippet, and why it needs to change. Also watch for: string literals
that reference the old module path (e.g. inside test mocks), and don't
assume every `Context`, `httpx`, or `mcp.tool`-shaped token you see is
actually affected — check what it's really doing.

(Each of the 5 agents also received one or two extra sentences pointing at
that specific repo's structural quirk — e.g. "check both the client and
server subdirectories" for danilop, "watch for the getattr/dir-based
loader" for tonyzorin — reproduced verbatim in each agent's prompt in this
conversation's tool-call log, not repeated here since they're repo-specific
hints, not part of the shared spec.)
