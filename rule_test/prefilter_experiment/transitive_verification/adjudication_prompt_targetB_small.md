TASK: You are adjudicating a fixed, pre-generated, PRE-FILTERED candidate list of lines from a codebase, checking each one against the Model Context Protocol (MCP) Python SDK's v1 -> v2 migration (a real, recently-shipped breaking change, released July 2026). Do NOT fix anything.

IMPORTANT — READ BEFORE STARTING: The candidate list below was produced by an exhaustive vocabulary search (grep), then passed through a deterministic mechanical pre-filter (no LLM) that removed candidates whose file never references the mcp package at all, and candidates whose match was entirely inside a comment/docstring/unrelated string literal. It is a closed, finite, complete set. **Your job is adjudication only, not search.** Do not use Grep or Glob to look for additional candidates beyond this list; the list is final. You MAY use Read on files that already appear in the list below, to see surrounding context needed to apply the counting convention -- but every verdict you produce must be about one of the 111 candidates given below, and every one of those 111 candidates must receive exactly one verdict. Do not skip any.

Some candidates have a `duplicate_count` and `duplicate_lines` field. This means the pre-filter found that exact same line of text repeated verbatim, byte-for-byte, at multiple line numbers within the same file (e.g. the same `await ctx.error(error_msg)` call appearing in 5 near-identical handler functions). You only need to give ONE verdict for that candidate -- it will automatically be applied to every line listed in `duplicate_lines`, so do not list them separately and do not worry about re-justifying each occurrence.

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

4. Decorators `@mcp.tool()`, `@mcp.resource()`, `@mcp.prompt()`, `@mcp.completion()` on the HIGH-LEVEL MCPServer/FastMCP API are UNCHANGED in v2 -- same arguments, same handler signatures. `MCPServer.add_tool()` is also UNCHANGED. The decorator -> constructor-kwargs change described below applies ONLY to the separate LOW-LEVEL `Server` class (`from mcp.server import Server`, NOT FastMCP/MCPServer):
   v1: `@server.list_tools()` decorator on the lowlevel Server
   v2: `Server(name="x", on_list_tools=handler)` -- decorators replaced by constructor keyword arguments, but ONLY for this lowlevel class.

5. Client SDK (`ClientSession`, `StdioServerParameters`, `mcp.client.stdio.stdio_client`): `cursor` parameter removed from `ClientSession.list_tools()`/`list_resources()` etc; a DIFFERENT class, `ClientSessionGroup.call_tool()`, lost its `args` parameter (plain `ClientSession.call_tool(name, arguments={...})` is unaffected); timeouts are now `float` seconds instead of `timedelta`; `get_server_capabilities()` replaced by `sampling_capabilities`/`roots_list_supported` properties. Import paths for ClientSession/StdioServerParameters/stdio_client did NOT change.

6. HTTP transport: the MCP SDK's OWN internal transport moved from `httpx` to `httpx2`, affecting code that constructs a custom `httpx.AsyncClient` or `httpx.Auth` subclass and passes it INTO SDK functions. This does NOT affect application code that independently uses the `httpx` library for its own unrelated HTTP calls.

7. `McpError` renamed to `MCPError` (case change), constructor now takes `code, message, data` directly instead of a wrapped `ErrorData` object.

8. `mcp.types` remains fully backward compatible -- `from mcp.types import X` and `from mcp import types` both still work unchanged in v2. This is NOT a breaking change for existing code and should not be flagged.

9. `ctx.elicit()`, `ctx.sample()`, `ctx.list_roots()` raise `NoBackChannelError` when called against a modern (2026-07-28) protocol connection -- only relevant if code actually calls these methods.

COUNTING CONVENTION (applies to every pattern above): A site is a line that must itself be edited to fix the migration. If fixing one line (e.g. an import statement) automatically repairs another line's behavior without that other line's own text needing to change, the other line is NOT a separate site — do not report it. Only report a line if its own text has to change. Example: if `Context` is imported from a path that moved, fixing the import statement alone makes every downstream `ctx: Context` type annotation resolve correctly again — the annotation's own text does not need to change. Contrast this with `FastMCP`: if a repo constructs `FastMCP(...)` or annotates a return type as `-> FastMCP:`, fixing the import does NOT make `FastMCP(...)` resolve — that identifier no longer exists under that name anywhere, so the construction/annotation site's own text must change to `MCPServer`. That IS a separate site.

OUTPUT CONTRACT — three buckets. For every one of the 111 candidates below, sort it into exactly one of:

- **PROPOSE**: confident this line's own text must change. Report with pattern number and reason.
- **REJECT**: confident this line does NOT need to change, and you can cite the specific fact above that settles it.
- **FLAG-UNCERTAIN**: the default when the two MANDATORY rules below apply, or when the facts above genuinely don't settle the question.

TWO MANDATORY, MECHANICAL ROUTING RULES — these override your own confidence. If a candidate matches either rule, you may NOT put it in REJECT (PROPOSE is still allowed if you are confident it IS a required site; otherwise it must go to FLAG-UNCERTAIN):

**RULE 1 (name-impersonation):** the candidate line is part of machinery that makes some OTHER piece of code's import/reference of an SDK symbol resolve to a locally-built stand-in, rather than the real installed package (e.g. a `sys.modules[...]` assignment, a `types.ModuleType(...)` construction representing an `mcp.*` path, or an attribute assignment exposing a class/function under an SDK name on such a constructed object).

**RULE 2 (test/mock path floor):** the candidate's file path contains `/tests/`, starts with `tests/`, matches `test_*.py` or `*_test.py`, or contains "mock" or "fixture" in the path/filename. Any such candidate you would otherwise REJECT must go to FLAG-UNCERTAIN instead.

CANDIDATE LIST (111 items, root: <repo-root>/repos):

```json
[
  {
    "file": "securityfortech_secops-mcp/main.py",
    "line": 7,
    "snippet": "from mcp.server.fastmcp import FastMCP"
  },
  {
    "file": "securityfortech_secops-mcp/main.py",
    "line": 26,
    "snippet": "mcp = FastMCP(name=\"secops-mcp\","
  },
  {
    "file": "securityfortech_secops-mcp/main.py",
    "line": 226,
    "snippet": "        data=data,"
  },
  {
    "file": "m0xai_trello-mcp-server/main.py",
    "line": 6,
    "snippet": "from mcp.server.fastmcp import FastMCP"
  },
  {
    "file": "m0xai_trello-mcp-server/main.py",
    "line": 23,
    "snippet": "mcp = FastMCP(\"Trello MCP Server\")"
  },
  {
    "file": "m0xai_trello-mcp-server/main.py",
    "line": 38,
    "snippet": "        logger.info(\"Starting Trello MCP Server in Claude app mode...\")"
  },
  {
    "file": "m0xai_trello-mcp-server/main.py",
    "line": 40,
    "snippet": "        logger.info(\"Trello MCP Server started successfully\")"
  },
  {
    "file": "m0xai_trello-mcp-server/main.py",
    "line": 42,
    "snippet": "        logger.error(f\"Error starting Claude server: {str(e)}\")"
  },
  {
    "file": "m0xai_trello-mcp-server/main.py",
    "line": 65,
    "snippet": "        logger.info("
  },
  {
    "file": "m0xai_trello-mcp-server/main.py",
    "line": 70,
    "snippet": "        logger.error(f\"Error starting SSE server: {str(e)}\")"
  },
  {
    "file": "m0xai_trello-mcp-server/main.py",
    "line": 86,
    "snippet": "        logger.info(\"Shutting down server...\")"
  },
  {
    "file": "m0xai_trello-mcp-server/main.py",
    "line": 88,
    "snippet": "        logger.error(f\"Server error: {str(e)}\")"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/board.py",
    "line": 8,
    "snippet": "from mcp.server.fastmcp import Context"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/board.py",
    "line": 20,
    "snippet": "async def get_board(ctx: Context, board_id: str) -> TrelloBoard:"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/board.py",
    "line": 30,
    "snippet": "        logger.info(f\"Getting board with ID: {board_id}\")"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/board.py",
    "line": 32,
    "snippet": "        logger.info(f\"Successfully retrieved board: {board_id}\")"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/board.py",
    "line": 36,
    "snippet": "        logger.error(error_msg)",
    "duplicate_count": 4,
    "duplicate_lines": [
      36,
      54,
      75,
      98
    ]
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/board.py",
    "line": 37,
    "snippet": "        await ctx.error(error_msg)",
    "duplicate_count": 4,
    "duplicate_lines": [
      37,
      55,
      76,
      99
    ]
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/board.py",
    "line": 41,
    "snippet": "async def get_boards(ctx: Context) -> List[TrelloBoard]:"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/board.py",
    "line": 48,
    "snippet": "        logger.info(\"Getting all boards\")"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/board.py",
    "line": 50,
    "snippet": "        logger.info(f\"Successfully retrieved {len(result)} boards\")"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/board.py",
    "line": 59,
    "snippet": "async def get_board_labels(ctx: Context, board_id: str) -> List[TrelloLabel]:"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/board.py",
    "line": 69,
    "snippet": "        logger.info(f\"Getting labels for board: {board_id}\")"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/board.py",
    "line": 71,
    "snippet": "        logger.info(f\"Successfully retrieved {len(result)} labels for board: {board_id}\")"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/board.py",
    "line": 80,
    "snippet": "async def create_board_label(ctx: Context, board_id: str, payload: CreateLabelPayload) -> TrelloLabel:"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/board.py",
    "line": 92,
    "snippet": "        logger.info(f\"Creating label {payload.name} label for board: {board_id}\")"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/board.py",
    "line": 94,
    "snippet": "        logger.info(f\"Successfully created label {payload.name} labels for board: {board_id}\")"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/list.py",
    "line": 8,
    "snippet": "from mcp.server.fastmcp import Context"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/list.py",
    "line": 20,
    "snippet": "async def get_list(ctx: Context, list_id: str) -> TrelloList:"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/list.py",
    "line": 30,
    "snippet": "        logger.info(f\"Getting list with ID: {list_id}\")"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/list.py",
    "line": 32,
    "snippet": "        logger.info(f\"Successfully retrieved list: {list_id}\")"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/list.py",
    "line": 36,
    "snippet": "        logger.error(error_msg)",
    "duplicate_count": 5,
    "duplicate_lines": [
      36,
      57,
      82,
      104,
      125
    ]
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/list.py",
    "line": 37,
    "snippet": "        await ctx.error(error_msg)",
    "duplicate_count": 5,
    "duplicate_lines": [
      37,
      58,
      83,
      105,
      126
    ]
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/list.py",
    "line": 41,
    "snippet": "async def get_lists(ctx: Context, board_id: str) -> List[TrelloList]:"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/list.py",
    "line": 51,
    "snippet": "        logger.info(f\"Getting lists for board: {board_id}\")"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/list.py",
    "line": 53,
    "snippet": "        logger.info(f\"Successfully retrieved {len(result)} lists for board: {board_id}\")"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/list.py",
    "line": 63,
    "snippet": "    ctx: Context, board_id: str, name: str, pos: str = \"bottom\""
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/list.py",
    "line": 76,
    "snippet": "        logger.info(f\"Creating list '{name}' in board: {board_id}\")"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/list.py",
    "line": 78,
    "snippet": "        logger.info(f\"Successfully created list '{name}' in board: {board_id}\")"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/list.py",
    "line": 87,
    "snippet": "async def update_list(ctx: Context, list_id: str, name: str) -> TrelloList:"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/list.py",
    "line": 98,
    "snippet": "        logger.info(f\"Updating list {list_id} with new name: {name}\")"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/list.py",
    "line": 100,
    "snippet": "        logger.info(f\"Successfully updated list: {list_id}\")"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/list.py",
    "line": 109,
    "snippet": "async def delete_list(ctx: Context, list_id: str) -> TrelloList:"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/list.py",
    "line": 119,
    "snippet": "        logger.info(f\"Archiving list: {list_id}\")"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/list.py",
    "line": 121,
    "snippet": "        logger.info(f\"Successfully archived list: {list_id}\")"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/card.py",
    "line": 8,
    "snippet": "from mcp.server.fastmcp import Context"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/card.py",
    "line": 21,
    "snippet": "async def get_card(ctx: Context, card_id: str) -> TrelloCard:"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/card.py",
    "line": 31,
    "snippet": "        logger.info(f\"Getting card with ID: {card_id}\")"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/card.py",
    "line": 33,
    "snippet": "        logger.info(f\"Successfully retrieved card: {card_id}\")"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/card.py",
    "line": 37,
    "snippet": "        logger.error(error_msg)",
    "duplicate_count": 5,
    "duplicate_lines": [
      37,
      58,
      81,
      107,
      128
    ]
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/card.py",
    "line": 38,
    "snippet": "        await ctx.error(error_msg)",
    "duplicate_count": 5,
    "duplicate_lines": [
      38,
      59,
      82,
      108,
      129
    ]
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/card.py",
    "line": 42,
    "snippet": "async def get_cards(ctx: Context, list_id: str) -> List[TrelloCard]:"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/card.py",
    "line": 52,
    "snippet": "        logger.info(f\"Getting cards for list: {list_id}\")"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/card.py",
    "line": 54,
    "snippet": "        logger.info(f\"Successfully retrieved {len(result)} cards for list: {list_id}\")"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/card.py",
    "line": 63,
    "snippet": "async def create_card(ctx: Context, payload: CreateCardPayload) -> TrelloCard:"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/card.py",
    "line": 75,
    "snippet": "        logger.info(f\"Creating card in list {payload.idList} with name: {payload.name}\")"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/card.py",
    "line": 77,
    "snippet": "        logger.info(f\"Successfully created card in list: {payload.idList}\")"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/card.py",
    "line": 87,
    "snippet": "    ctx: Context, card_id: str, payload: UpdateCardPayload"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/card.py",
    "line": 99,
    "snippet": "        logger.info(f\"Updating card: {card_id} with payload: {payload}\")"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/card.py",
    "line": 103,
    "snippet": "        logger.info(f\"Successfully updated card: {card_id}\")"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/card.py",
    "line": 112,
    "snippet": "async def delete_card(ctx: Context, card_id: str) -> dict:"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/card.py",
    "line": 122,
    "snippet": "        logger.info(f\"Deleting card: {card_id}\")"
  },
  {
    "file": "m0xai_trello-mcp-server/server/tools/card.py",
    "line": 124,
    "snippet": "        logger.info(f\"Successfully deleted card: {card_id}\")"
  },
  {
    "file": "tonyzorin_youtrack-mcp/main.py",
    "line": 10,
    "snippet": "from mcp.server.fastmcp import FastMCP"
  },
  {
    "file": "tonyzorin_youtrack-mcp/main.py",
    "line": 25,
    "snippet": "def create_server(host: str = \"0.0.0.0\", port: int = 8000) -> FastMCP:"
  },
  {
    "file": "tonyzorin_youtrack-mcp/main.py",
    "line": 27,
    "snippet": "    mcp = FastMCP("
  },
  {
    "file": "tonyzorin_youtrack-mcp/main.py",
    "line": 39,
    "snippet": "    logger.info(f\"Registered {len(tools)} tools with FastMCP\")"
  },
  {
    "file": "tonyzorin_youtrack-mcp/main.py",
    "line": 55,
    "snippet": "    args = parser.parse_args()"
  },
  {
    "file": "tonyzorin_youtrack-mcp/main.py",
    "line": 67,
    "snippet": "    logger.info(f\"Starting YouTrack MCP Server v{APP_VERSION} [{transport}]\")"
  },
  {
    "file": "danilop_MCP2Lambda/main.py",
    "line": 6,
    "snippet": "from mcp.server.fastmcp import FastMCP, Context"
  },
  {
    "file": "danilop_MCP2Lambda/main.py",
    "line": 17,
    "snippet": "args = parser.parse_args()"
  },
  {
    "file": "danilop_MCP2Lambda/main.py",
    "line": 30,
    "snippet": "mcp = FastMCP(\"MCP Gateway to AWS Lambda\")"
  },
  {
    "file": "danilop_MCP2Lambda/main.py",
    "line": 68,
    "snippet": "def list_lambda_functions_impl(ctx: Context) -> str:"
  },
  {
    "file": "danilop_MCP2Lambda/main.py",
    "line": 73,
    "snippet": "    ctx.info(\"Calling AWS Lambda ListFunctions...\")"
  },
  {
    "file": "danilop_MCP2Lambda/main.py",
    "line": 77,
    "snippet": "    ctx.info(f\"Found {len(functions['Functions'])} functions\")"
  },
  {
    "file": "danilop_MCP2Lambda/main.py",
    "line": 83,
    "snippet": "    ctx.info(f\"Found {len(functions_with_prefix)} functions with prefix {FUNCTION_PREFIX}\")"
  },
  {
    "file": "danilop_MCP2Lambda/main.py",
    "line": 94,
    "snippet": "def invoke_lambda_function_impl(function_name: str, parameters: dict, ctx: Context) -> str:"
  },
  {
    "file": "danilop_MCP2Lambda/main.py",
    "line": 101,
    "snippet": "    ctx.info(f\"Invoking {function_name} with parameters: {parameters}\")"
  },
  {
    "file": "danilop_MCP2Lambda/main.py",
    "line": 109,
    "snippet": "    ctx.info(f\"Function {function_name} returned with status code: {response['StatusCode']}\")"
  },
  {
    "file": "danilop_MCP2Lambda/main.py",
    "line": 113,
    "snippet": "        ctx.error(error_message)"
  },
  {
    "file": "danilop_MCP2Lambda/main.py",
    "line": 136,
    "snippet": "    def lambda_function(parameters: dict, ctx: Context) -> str:"
  },
  {
    "file": "danilop_MCP2Lambda/mcp_client_bedrock/mcp_client.py",
    "line": 1,
    "snippet": "from mcp import ClientSession, StdioServerParameters"
  },
  {
    "file": "danilop_MCP2Lambda/mcp_client_bedrock/mcp_client.py",
    "line": 2,
    "snippet": "from mcp.client.stdio import stdio_client"
  },
  {
    "file": "danilop_MCP2Lambda/mcp_client_bedrock/mcp_client.py",
    "line": 6,
    "snippet": "    def __init__(self, server_params: StdioServerParameters):"
  },
  {
    "file": "danilop_MCP2Lambda/mcp_client_bedrock/mcp_client.py",
    "line": 25,
    "snippet": "        self._client = stdio_client(self.server_params)"
  },
  {
    "file": "danilop_MCP2Lambda/mcp_client_bedrock/mcp_client.py",
    "line": 27,
    "snippet": "        session = ClientSession(self.read, self.write)"
  },
  {
    "file": "danilop_MCP2Lambda/mcp_client_bedrock/mcp_client.py",
    "line": 36,
    "snippet": "        tools = await self.session.list_tools()"
  },
  {
    "file": "danilop_MCP2Lambda/mcp_client_bedrock/mcp_client.py",
    "line": 44,
    "snippet": "        result = await self.session.call_tool(tool_name, arguments=arguments)"
  },
  {
    "file": "danilop_MCP2Lambda/mcp_client_bedrock/main.py",
    "line": 2,
    "snippet": "from mcp import StdioServerParameters"
  },
  {
    "file": "danilop_MCP2Lambda/mcp_client_bedrock/main.py",
    "line": 25,
    "snippet": "    server_params = StdioServerParameters("
  },
  {
    "file": "danilop_MCP2Lambda/mcp_client_bedrock/main.py",
    "line": 28,
    "snippet": "        args=[\"--directory\", \"..\", \"run\", \"main.py\"],"
  },
  {
    "file": "danilop_MCP2Lambda/mcp_client_bedrock/main.py",
    "line": 44,
    "snippet": "                input_schema={'json': tool.inputSchema}"
  },
  {
    "file": "QAInsights_jmeter-mcp-server/jmeter_server.py",
    "line": 4,
    "snippet": "from mcp.server.fastmcp import FastMCP"
  },
  {
    "file": "QAInsights_jmeter-mcp-server/jmeter_server.py",
    "line": 23,
    "snippet": "mcp = FastMCP(\"jmeter\")"
  },
  {
    "file": "QAInsights_jmeter-mcp-server/jmeter_server.py",
    "line": 54,
    "snippet": "        logger.info(f\"JMeter binary path: {jmeter_bin}\")"
  },
  {
    "file": "QAInsights_jmeter-mcp-server/jmeter_server.py",
    "line": 55,
    "snippet": "        logger.debug(f\"Java options: {java_opts}\")"
  },
  {
    "file": "QAInsights_jmeter-mcp-server/jmeter_server.py",
    "line": 68,
    "snippet": "                logger.debug(f\"Adding property: -J{prop_name}={prop_value}\")"
  },
  {
    "file": "QAInsights_jmeter-mcp-server/jmeter_server.py",
    "line": 76,
    "snippet": "                logger.debug(f\"Using generated unique log file: {log_file}\")"
  },
  {
    "file": "QAInsights_jmeter-mcp-server/jmeter_server.py",
    "line": 88,
    "snippet": "                logger.debug(f\"Making user-provided report directory unique: {original_dir} -> {report_output_dir}\")"
  },
  {
    "file": "QAInsights_jmeter-mcp-server/jmeter_server.py",
    "line": 92,
    "snippet": "                logger.debug(f\"Using generated unique report output directory: {report_output_dir}\")"
  },
  {
    "file": "QAInsights_jmeter-mcp-server/jmeter_server.py",
    "line": 97,
    "snippet": "        logger.debug(f\"Executing command: {' '.join(cmd)}\")"
  },
  {
    "file": "QAInsights_jmeter-mcp-server/jmeter_server.py",
    "line": 104,
    "snippet": "            logger.debug(\"Command output:\")"
  },
  {
    "file": "QAInsights_jmeter-mcp-server/jmeter_server.py",
    "line": 105,
    "snippet": "            logger.debug(f\"Return code: {result.returncode}\")"
  },
  {
    "file": "QAInsights_jmeter-mcp-server/jmeter_server.py",
    "line": 106,
    "snippet": "            logger.debug(f\"Stdout: {result.stdout}\")"
  },
  {
    "file": "QAInsights_jmeter-mcp-server/jmeter_server.py",
    "line": 107,
    "snippet": "            logger.debug(f\"Stderr: {result.stderr}\")"
  },
  {
    "file": "QAInsights_jmeter-mcp-server/main.py",
    "line": 2,
    "snippet": "from mcp.server.fastmcp import FastMCP"
  },
  {
    "file": "QAInsights_jmeter-mcp-server/main.py",
    "line": 9,
    "snippet": "mcp = FastMCP(\"jmeter\")"
  },
  {
    "file": "QAInsights_jmeter-mcp-server/tests/test_jmeter_server.py",
    "line": 11,
    "snippet": "fastmcp_mod = types.ModuleType('mcp.server.fastmcp')"
  },
  {
    "file": "QAInsights_jmeter-mcp-server/tests/test_jmeter_server.py",
    "line": 12,
    "snippet": "class FastMCP:"
  },
  {
    "file": "QAInsights_jmeter-mcp-server/tests/test_jmeter_server.py",
    "line": 21,
    "snippet": "fastmcp_mod.FastMCP = FastMCP"
  },
  {
    "file": "QAInsights_jmeter-mcp-server/tests/test_jmeter_server.py",
    "line": 22,
    "snippet": "sys.modules['mcp.server.fastmcp'] = fastmcp_mod"
  }
]
```

OUTPUT FORMAT — your final response must end with a fenced ```json code block, and every one of the 111 candidates above must appear in exactly one of the three arrays below (matched by file+line -- for a candidate with duplicate_lines, use its first/representative line):

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

Every one of the three top-level keys must be present even if a bucket is empty (use `[]`).
