# MIGRATION SPEC — MCP Python SDK v1 → v2 (9-fact, authoritative)

The following are the ONLY confirmed changes in this migration. Anything
not described below is unaffected — including things you might expect to
be affected.

1. FastMCP -> MCPServer rename. `from mcp.server.fastmcp import FastMCP` no
   longer works (ModuleNotFoundError) -- the whole module tree moves:
   `from mcp.server.mcpserver import MCPServer`. ALL submodules under
   mcp.server.fastmcp.* move to mcp.server.mcpserver.*, including `Context`
   if imported from that path. No compatibility alias exists. Any import of
   `FastMCP` or any symbol from `mcp.server.fastmcp`, any construction of
   `FastMCP(...)`, and any type annotation referencing `FastMCP` is broken.

2. camelCase -> snake_case field renames on protocol objects (Python
   ATTRIBUTE ACCESS only -- constructor kwargs still accept both spellings):
   result.isError -> result.is_error
   tools.nextCursor -> tools.next_cursor
   tool.inputSchema -> tool.input_schema
   tool.outputSchema -> tool.output_schema
   content.mimeType -> content.mime_type
   params.structuredContent -> params.structured_content
   info.serverInfo -> info.server_info
   info.protocolVersion -> info.protocol_version
   template.uriTemplate -> template.uri_template
   notification.listChanged -> notification.list_changed
   params.progressToken -> params.progress_token

3. High-level Context (mcp.server.mcpserver.Context) changes: `.log()`
   parameter renamed message -> data; `extra=` parameter REMOVED from
   `.debug()/.info()/.warning()/.error()` (calls using only a positional
   message string are UNAFFECTED); `client_id` removed; `mcp.get_context()`
   removed entirely (inject `ctx: Context` as a handler parameter instead --
   if a repo already does this, it is NOT affected).

4. Decorators `@mcp.tool()`, `@mcp.resource()`, `@mcp.prompt()`,
   `@mcp.completion()` on the HIGH-LEVEL MCPServer/FastMCP API are UNCHANGED
   in v2 -- same arguments, same handler signatures. `MCPServer.add_tool()`
   is also UNCHANGED. The decorator -> constructor-kwargs change described
   below applies ONLY to the separate LOW-LEVEL `Server` class
   (`from mcp.server import Server`, NOT FastMCP/MCPServer):
   v1: `@server.list_tools()` decorator on the lowlevel Server
   v2: `Server(name="x", on_list_tools=handler)` -- decorators replaced by
       constructor keyword arguments, but ONLY for this lowlevel class.

5. Client SDK (`ClientSession`, `StdioServerParameters`,
   `mcp.client.stdio.stdio_client`): `cursor` parameter removed from
   `ClientSession.list_tools()`/`list_resources()` etc; a DIFFERENT class,
   `ClientSessionGroup.call_tool()`, lost its `args` parameter (plain
   `ClientSession.call_tool(name, arguments={...})` is unaffected); timeouts
   are now `float` seconds instead of `timedelta`; `get_server_capabilities()`
   replaced by `sampling_capabilities`/`roots_list_supported` properties.
   Import paths for ClientSession/StdioServerParameters/stdio_client did NOT
   change.

6. HTTP transport: the MCP SDK's OWN internal transport moved from `httpx`
   to `httpx2`, affecting code that constructs a custom `httpx.AsyncClient`
   or `httpx.Auth` subclass and passes it INTO SDK functions. This does NOT
   affect application code that independently uses the `httpx` library for
   its own unrelated HTTP calls.

7. `McpError` renamed to `MCPError` (case change), constructor now takes
   `code, message, data` directly instead of a wrapped `ErrorData` object.

8. `mcp.types` remains fully backward compatible -- `from mcp.types import X`
   and `from mcp import types` both still work unchanged in v2. This is NOT
   a breaking change for existing code and should not be flagged.

9. `ctx.elicit()`, `ctx.sample()`, `ctx.list_roots()` raise
   `NoBackChannelError` when called against a modern (2026-07-28) protocol
   connection -- only relevant if code actually calls these methods.

COUNTING CONVENTION (applies to every pattern above): A site is a line that
must itself be edited to fix the migration. If fixing one line (e.g. an
import statement) automatically repairs another line's behavior without
that other line's own text needing to change, the other line is NOT a
separate site — do not report it. Only report a line if its own text has
to change. Example: if `Context` is imported from a path that moved, fixing
the import statement alone makes every downstream `ctx: Context` type
annotation resolve correctly again — the annotation's own text does not
need to change. Contrast this with `FastMCP`: if a repo constructs
`FastMCP(...)` or annotates a return type as `-> FastMCP:`, fixing the
import does NOT make `FastMCP(...)` resolve — that identifier no longer
exists under that name anywhere, so the construction/annotation site's own
text must change to `MCPServer`. That IS a separate site.

Note for fix-generation (as opposed to detection): "this line must change"
and "here is the exact correct replacement for this line" are different
questions. Some sites above may turn out, once you actually read the
surrounding code, to require touching more than this one line, or to have
no single line-level replacement that fully repairs them. If the correct
edit isn't a confident, self-contained replacement of the detected line,
say so rather than guessing.
