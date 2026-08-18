TASK: You are adjudicating a fixed, pre-generated candidate list of lines from a codebase, checking each one against the Model Context Protocol (MCP) Python SDK's v1 -> v2 migration (a real, recently-shipped breaking change, released July 2026). Do NOT fix anything.

IMPORTANT — READ BEFORE STARTING: The candidate list below was produced by an exhaustive vocabulary search (grep) tuned for coverage, not precision. It is a closed, finite, complete set — every line in this codebase that could plausibly be relevant is already in the list below. **Your job is adjudication only, not search.** Do not use Grep or Glob to look for additional candidates beyond this list; the list is final. You MAY use Read on files that already appear in the list below, to see surrounding context needed to apply the counting convention (e.g. to check whether an earlier import in the same file was already accounted for) -- but every verdict you produce must be about one of the {CANDIDATE_COUNT} candidates given below, and every one of those {CANDIDATE_COUNT} candidates must receive exactly one verdict. Do not skip any. Do not merge multiple candidates into one summarized verdict -- if two lines are identical for the same reason, still give each its own entry in your output.

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

COUNTING CONVENTION (applies to every pattern above): A site is a line that must itself be edited to fix the migration. If fixing one line (e.g. an import statement) automatically repairs another line's behavior without that other line's own text needing to change, the other line is NOT a separate site — do not report it. Only report a line if its own text has to change. Example: if `Context` is imported from a path that moved, fixing the import statement alone makes every downstream `ctx: Context` type annotation resolve correctly again — the annotation's own text does not need to change. Those annotation lines are not separate sites, even though they reference a name whose import was broken, because nothing about their own text is wrong once the import is fixed. Contrast this with `FastMCP`: if a repo constructs `FastMCP(...)` or annotates a return type as `-> FastMCP:`, fixing the import to `from mcp.server.mcpserver import MCPServer` does NOT make `FastMCP(...)` resolve — that identifier no longer exists under that name anywhere, so the construction/annotation site's own text must change to `MCPServer`. That IS a separate site.

OUTPUT CONTRACT — three buckets. For every one of the {CANDIDATE_COUNT} candidates below, sort it into exactly one of PROPOSE / FLAG-UNCERTAIN / REJECT:

- **PROPOSE**: confident this line's own text must change. Report with pattern number and reason.
- **REJECT**: confident this line does NOT need to change, and you can cite the specific fact above that settles it.
- **FLAG-UNCERTAIN**: the default when the two MANDATORY rules below apply, or when the facts above genuinely don't settle the question. Give a reason either way.

TWO MANDATORY, MECHANICAL ROUTING RULES — these override your own confidence. If a candidate matches either rule, you may NOT put it in REJECT (PROPOSE is still allowed if you are confident it IS a required site; otherwise it must go to FLAG-UNCERTAIN):

**RULE 1 (name-impersonation):** the candidate line is part of machinery that makes some OTHER piece of code's import of an SDK symbol resolve to a locally-built stand-in, rather than the real installed package. Concrete, observable anchors -- the line assigns into `sys.modules[...]`, or constructs a module object via `types.ModuleType(...)` representing an `mcp.*` path, or sets an attribute on such a constructed module object to expose a class under an SDK name (e.g. `fake_mod.FastMCP = SomeClass`). This rule does NOT apply merely because a local class or function happens to share a name with an SDK symbol (e.g. an app's own unrelated `class MCPServer:` with no `sys.modules` involvement and no relationship to satisfying anyone's import) -- only when the line is actively part of building or registering a stand-in for the real package.

**RULE 2 (test/mock path floor):** the candidate's file path contains `/tests/`, starts with `tests/`, matches `test_*.py` or `*_test.py`, or contains "mock" or "fixture" in the path/filename. Any such candidate you would otherwise REJECT must go to FLAG-UNCERTAIN instead. (You may still PROPOSE a test-file candidate you're confident is a genuine required site.)

These two rules exist because REJECT verdicts on candidates matching them have been wrong, with confident stated reasoning, in prior runs of this study -- the rule replaces self-assessed "am I sure" with a mechanical check you apply the same way every time, regardless of how confident your own reasoning feels.

CANDIDATE LIST ({CANDIDATE_COUNT} items, root: {REPO_PATH}):

```json
{CANDIDATE_LIST_JSON}
```

OUTPUT FORMAT — your final response must end with a fenced ```json code block, and every one of the {CANDIDATE_COUNT} candidates above must appear in exactly one of the three arrays below (matched by file+line):

{
  "proposed_sites": [
    {"file": "relative/path.py", "line": 12, "snippet": "exact line text", "pattern": "1-9", "reason": "why this needs to change"}
  ],
  "flag_uncertain": [
    {"file": "relative/path.py", "line": 20, "snippet": "exact line text", "reason": "which mandatory rule applies, or the specific ambiguity"}
  ],
  "considered_and_rejected": [
    {"file": "relative/path.py", "line": 34, "snippet": "exact line text", "reason": "why this does NOT need to change, citing the specific fact that settles it"}
  ]
}
