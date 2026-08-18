# Target B spec — reinstated original (verbatim) + counting convention

The breaking-change facts (items 1-9) and the surrounding TASK/CONSTRAINTS
language below are extracted verbatim from the original session
(`rule_test/original_session_recovered/`), not reconstructed. Only the
COUNTING CONVENTION paragraph is new (added per instruction) and the JSON
output-format block replaces the original's "numbered list" instruction so
this run's output can be scored programmatically the same way as every
other run in this study — that substitution is infrastructure, not spec
content.

---

TASK: You are auditing a Python codebase for lines of code broken by the Model Context Protocol (MCP) Python SDK's v1 -> v2 migration (a real, recently-shipped breaking change, released July 2026). Do NOT fix anything. Only report every line you find that is broken.

THE BREAKING CHANGE (from the official migration guide, verbatim facts):

1. FastMCP -> MCPServer rename. `from mcp.server.fastmcp import FastMCP` no longer works (ModuleNotFoundError) -- the whole module tree moves: `from mcp.server.mcpserver import MCPServer`. ALL submodules under mcp.server.fastmcp.* move to mcp.server.mcpserver.*, including `Context` if imported from that path. No compatibility alias exists. Any import of `FastMCP` or any symbol from `mcp.server.fastmcp`, any construction of `FastMCP(...)`, and any type annotation referencing `FastMCP` is broken.

2. camelCase -> snake_case field renames on protocol objects (Python ATTRIBUTE ACCESS only -- constructor kwargs still accept both spellings):
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

3. High-level Context (mcp.server.mcpserver.Context) changes: `.log()` parameter renamed message -> data; `extra=` parameter REMOVED from `.debug()/.info()/.warning()/.error()` (calls using only a positional message string are UNAFFECTED); `client_id` removed; `mcp.get_context()` removed entirely (inject `ctx: Context` as a handler parameter instead -- if a repo already does this, it is NOT affected).

4. Decorators `@mcp.tool()`, `@mcp.resource()`, `@mcp.prompt()`, `@mcp.completion()` on the HIGH-LEVEL MCPServer/FastMCP API are UNCHANGED in v2 -- same arguments, same handler signatures. Do not flag these as broken. `MCPServer.add_tool()` is also UNCHANGED. The decorator -> constructor-kwargs change described below applies ONLY to the separate LOW-LEVEL `Server` class (`from mcp.server import Server`, NOT FastMCP/MCPServer):
   v1: `@server.list_tools()` decorator on the lowlevel Server
   v2: `Server(name="x", on_list_tools=handler)` -- decorators replaced by constructor keyword arguments, but ONLY for this lowlevel class.

5. Client SDK (`ClientSession`, `StdioServerParameters`, `mcp.client.stdio.stdio_client`): `cursor` parameter removed from `ClientSession.list_tools()`/`list_resources()` etc; a DIFFERENT class, `ClientSessionGroup.call_tool()`, lost its `args` parameter (plain `ClientSession.call_tool(name, arguments={...})` is unaffected); timeouts are now `float` seconds instead of `timedelta`; `get_server_capabilities()` replaced by `sampling_capabilities`/`roots_list_supported` properties. Import paths for ClientSession/StdioServerParameters/stdio_client did NOT change.

6. HTTP transport: the MCP SDK's OWN internal transport moved from `httpx` to `httpx2`, affecting code that constructs a custom `httpx.AsyncClient` or `httpx.Auth` subclass and passes it INTO SDK functions. This does NOT affect application code that independently uses the `httpx` library for its own unrelated HTTP calls (e.g. calling a third-party REST API) -- that usage has nothing to do with the MCP SDK and is not broken.

7. `McpError` renamed to `MCPError` (case change), constructor now takes `code, message, data` directly instead of a wrapped `ErrorData` object.

8. `mcp.types` remains fully backward compatible -- `from mcp.types import X` and `from mcp import types` both still work unchanged in v2. This is NOT a breaking change for existing code and should not be flagged.

9. `ctx.elicit()`, `ctx.sample()`, `ctx.list_roots()` raise `NoBackChannelError` when called against a modern (2026-07-28) protocol connection -- only relevant if code actually calls these methods.

COUNTING CONVENTION (applies to every pattern above): A site is a line
that must itself be edited to fix the migration. If fixing one line (e.g.
an import statement) automatically repairs another line's behavior
without that other line's own text needing to change, the other line is
NOT a separate site — do not report it. Only report a line if its own
text has to change. Example: if `Context` is imported from a path that
moved, fixing the import statement alone makes every downstream `ctx:
Context` type annotation resolve correctly again — the annotation's own
text does not need to change. Those annotation lines are not separate
sites, even though they reference a name whose import was broken,
because nothing about their own text is wrong once the import is fixed.
Contrast this with `FastMCP`: if a repo constructs `FastMCP(...)` or
annotates a return type as `-> FastMCP:`, fixing the import to `from
mcp.server.mcpserver import MCPServer` does NOT make `FastMCP(...)`
resolve — that identifier no longer exists under that name anywhere, so
the construction/annotation site's own text must change to `MCPServer`.
That IS a separate site. The distinguishing question for any downstream
reference is always: after fixing only the import line, does this
specific line's text still need to change, or does it now work as
written?

YOUR TASK: search the ENTIRE codebase at {REPO_PATH} (every .py file, including test files, not just the main entry point) and report every single line affected by any of the numbered patterns above. Include sites reached only through helper functions, dynamically constructed/registered tools, or test mocks -- do not stop at the first occurrence in a file. For each finding, report: file path (relative to repo root), line number, the exact line of code, and which numbered pattern it matches. If you are unsure whether something is actually affected, say so explicitly rather than silently including or excluding it.

{DANILOP_EXTRA}

CONSTRAINTS:
- Restrict ALL reads, greps, and file listings to exactly this directory: {REPO_PATH} -- do not read, list, or reference any path outside it, including parent or sibling directories.
- Do not modify any files. Do not run the code. This is a read-only audit.
- Report your findings as a numbered list. Be exhaustive but do not report something as affected if it clearly does not match any pattern above (e.g. do not flag decorators, add_tool(), or unrelated httpx usage just because those terms appear in this guide -- read the guide's own caveats about what is NOT broken).
- End your report with a total count of findings.

OUTPUT FORMAT (added for this study, not part of the original spec) — your
final response must end with a fenced ```json code block containing exactly
this structure, and nothing else inside that fence:

{
  "proposed_sites": [
    {"file": "relative/path.py", "line": 12, "snippet": "exact line text", "pattern": "1-9", "reason": "why this needs to change"}
  ],
  "considered_and_rejected": [
    {"file": "relative/path.py", "line": 34, "snippet": "exact line text", "reason": "why you decided this does NOT need to change"}
  ]
}

Original danilop-specific sentence (inserted where {DANILOP_EXTRA} appears
above, for that repo only): "This repository contains BOTH an MCP server
AND a separate MCP client component (check subdirectories) -- check both
sides."
