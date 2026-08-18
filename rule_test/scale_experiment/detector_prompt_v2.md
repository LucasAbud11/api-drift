# Detector prompt v2 — prospective three-bucket contract + scale host

Breaking-change facts (items 1-9) and the COUNTING CONVENTION paragraph
are unchanged, word-for-word, from `rule_test/spec_reinstated/target_b_spec.md`
(itself the verbatim recovered original spec plus the convention addition).
That wording is deliberately NOT being touched by this experiment — see
`results.md` revision 5 for why it's on hold. What's new here is (1) the
task/constraints section, rewritten for a single large host directory
instead of one clean repo, and (2) the output contract, which is
rewritten from binary propose/reject to a stated three-bucket contract
with explicit instructions on when to hedge. This is a prospective test:
the detector is TOLD about FLAG-UNCERTAIN before it searches, not scored
retroactively for hedge language it was never asked to produce.

---

TASK: You are auditing a large codebase for lines of code broken by the Model Context Protocol (MCP) Python SDK's v1 -> v2 migration (a real, recently-shipped breaking change, released July 2026). Do NOT fix anything. Only report every line you find that is broken.

IMPORTANT CONTEXT ABOUT THIS CODEBASE: {REPO_PATH} is a large host directory containing multiple unrelated subsystems. Most of it has nothing to do with the MCP SDK. MCP SDK usage, where it exists, is NOT confined to any single top-level folder and is not announced to you in advance -- you have to find it yourself, the same way you would in an unfamiliar production monorepo. Some code in this host defines its OWN classes/objects that happen to share a name with an MCP SDK symbol (for example, a totally unrelated `Context` class from a different framework) -- a name match alone is not evidence of MCP SDK usage; check the actual import path and usage before flagging anything.

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

COUNTING CONVENTION (applies to every pattern above): A site is a line that must itself be edited to fix the migration. If fixing one line (e.g. an import statement) automatically repairs another line's behavior without that other line's own text needing to change, the other line is NOT a separate site — do not report it. Only report a line if its own text has to change. Example: if `Context` is imported from a path that moved, fixing the import statement alone makes every downstream `ctx: Context` type annotation resolve correctly again — the annotation's own text does not need to change. Those annotation lines are not separate sites, even though they reference a name whose import was broken, because nothing about their own text is wrong once the import is fixed. Contrast this with `FastMCP`: if a repo constructs `FastMCP(...)` or annotates a return type as `-> FastMCP:`, fixing the import to `from mcp.server.mcpserver import MCPServer` does NOT make `FastMCP(...)` resolve — that identifier no longer exists under that name anywhere, so the construction/annotation site's own text must change to `MCPServer`. That IS a separate site. The distinguishing question for any downstream reference is always: after fixing only the import line, does this specific line's text still need to change, or does it now work as written?

OUTPUT CONTRACT — three buckets, not two. For every candidate line you examine, you must sort it into exactly one of:

- **PROPOSE**: you are confident this line's own text must change to fix the migration. Report it with the pattern number and a concrete reason.
- **FLAG-UNCERTAIN**: the breaking-change facts above and the counting convention do not clearly settle whether this line counts as a site. This is NOT a weaker version of PROPOSE or REJECT -- it is the correct bucket specifically when the spec is silent or ambiguous on the question, and guessing either way would not be justified by anything actually stated above. Use this instead of picking PROPOSE or REJECT by best guess. State the specific ambiguity: what fact would resolve it if you had it.
- **REJECT**: you are confident this line does NOT need to change, and you can point to a specific fact above (or the absence of any matching pattern) that settles it.

Do not use REJECT as a default bucket for "didn't seem important" -- a REJECT needs the same level of justification as a PROPOSE. If you're not sure whether something is affected, that is precisely what FLAG-UNCERTAIN is for; do not silently fold it into REJECT to keep the list short, and do not fold it into PROPOSE to be safe. Guessing in either direction defeats the purpose of having this bucket.

YOUR TASK: search the ENTIRE host directory at {REPO_PATH} (every .py file, not just files that look obviously MCP-related) and sort every candidate line into PROPOSE, FLAG-UNCERTAIN, or REJECT per the contract above. Include sites reached only through helper functions, dynamically constructed/registered tools, or test mocks -- do not stop at the first occurrence in a subdirectory, and do not assume MCP usage is confined to any particular folder just because you found some there.

CONSTRAINTS:
- Restrict ALL reads, greps, and file listings to exactly this directory: {REPO_PATH} -- do not read, list, or reference any path outside it, including parent or sibling directories.
- Do not modify any files. Do not run the code. This is a read-only audit.
- Be exhaustive but justify every bucket assignment, including REJECT and FLAG-UNCERTAIN, the same way you would justify a PROPOSE.
- End your report with a total count of findings in each bucket.

OUTPUT FORMAT — your final response must end with a fenced ```json code block containing exactly this structure, and nothing else inside that fence:

{
  "proposed_sites": [
    {"file": "relative/path.py", "line": 12, "snippet": "exact line text", "pattern": "1-9", "reason": "why this needs to change"}
  ],
  "flag_uncertain": [
    {"file": "relative/path.py", "line": 20, "snippet": "exact line text", "reason": "the specific ambiguity, and what fact would resolve it"}
  ],
  "considered_and_rejected": [
    {"file": "relative/path.py", "line": 34, "snippet": "exact line text", "reason": "why you decided this does NOT need to change, citing the specific fact that settles it"}
  ]
}

Every one of the three top-level keys must be present in the JSON block even if a bucket is empty (use `[]`) -- the scoring pipeline hard-fails on a missing key, it does not treat a missing bucket as "empty."
