# Fix ground truth — targetB_small, 20 sites

Built by direct source read (`repos/*` as of this session) + the migration
spec (`rule_test/specs/target_b_mcp_migration_spec.md`), same standard as
`ground_truth/ground_truth.md`. **This file is the answer key for the
fix-generation experiment. It must never be shown to a fix-generation agent.**
Each entry: original line -> required v2 line, and which spec fact justifies
the edit. Only the site's own line is edited (matches this study's existing
line-level counting convention, verified empirically in `b8b_verification.md`
for the test-mock class).

| id | file:line | original | v2 (required) | spec fact |
|---|---|---|---|---|
| B1 | tonyzorin_youtrack-mcp/main.py:10 | `from mcp.server.fastmcp import FastMCP` | `from mcp.server.mcpserver import MCPServer` | 1, 2 |
| B2 | tonyzorin_youtrack-mcp/main.py:25 | `def create_server(host: str = "0.0.0.0", port: int = 8000) -> FastMCP:` | `def create_server(host: str = "0.0.0.0", port: int = 8000) -> MCPServer:` | 2 |
| B3 | tonyzorin_youtrack-mcp/main.py:27 | `    mcp = FastMCP(` | `    mcp = MCPServer(` | 2 |
| B4 | QAInsights_jmeter-mcp-server/main.py:2 | `from mcp.server.fastmcp import FastMCP` | `from mcp.server.mcpserver import MCPServer` | 1, 2 |
| B5 | QAInsights_jmeter-mcp-server/main.py:9 | `mcp = FastMCP("jmeter")` | `mcp = MCPServer("jmeter")` | 2 |
| B6 | QAInsights_jmeter-mcp-server/jmeter_server.py:4 | `from mcp.server.fastmcp import FastMCP` | `from mcp.server.mcpserver import MCPServer` | 1, 2 |
| B7 | QAInsights_jmeter-mcp-server/jmeter_server.py:23 | `mcp = FastMCP("jmeter")` | `mcp = MCPServer("jmeter")` | 2 |
| B8a | QAInsights_.../tests/test_jmeter_server.py:11 | `fastmcp_mod = types.ModuleType('mcp.server.fastmcp')` | `fastmcp_mod = types.ModuleType('mcp.server.mcpserver')` | 1 (see note) |
| B8c | QAInsights_.../tests/test_jmeter_server.py:21 | `fastmcp_mod.FastMCP = FastMCP` | `fastmcp_mod.MCPServer = FastMCP` | 1, 2 (empirically confirmed load-bearing, `b8b_verification.md`) |
| B8d | QAInsights_.../tests/test_jmeter_server.py:22 | `sys.modules['mcp.server.fastmcp'] = fastmcp_mod` | `sys.modules['mcp.server.mcpserver'] = fastmcp_mod` | 1 (empirically confirmed load-bearing) |
| B9 | securityfortech_secops-mcp/main.py:7 | `from mcp.server.fastmcp import FastMCP` | `from mcp.server.mcpserver import MCPServer` | 1, 2 |
| B10 | securityfortech_secops-mcp/main.py:26 | `mcp = FastMCP(name="secops-mcp",` | `mcp = MCPServer(name="secops-mcp",` | 2 |
| B11 | m0xai_trello-mcp-server/main.py:6 | `from mcp.server.fastmcp import FastMCP` | `from mcp.server.mcpserver import MCPServer` | 1, 2 |
| B12 | m0xai_trello-mcp-server/main.py:23 | `mcp = FastMCP("Trello MCP Server")` | `mcp = MCPServer("Trello MCP Server")` | 2 |
| B13 | m0xai_.../server/tools/board.py:8 | `from mcp.server.fastmcp import Context` | `from mcp.server.mcpserver import Context` | 1, 3 |
| B14 | m0xai_.../server/tools/card.py:8 | `from mcp.server.fastmcp import Context` | `from mcp.server.mcpserver import Context` | 1, 3 |
| B15 | m0xai_.../server/tools/list.py:8 | `from mcp.server.fastmcp import Context` | `from mcp.server.mcpserver import Context` | 1, 3 |
| B16 | danilop_MCP2Lambda/main.py:6 | `from mcp.server.fastmcp import FastMCP, Context` | `from mcp.server.mcpserver import MCPServer, Context` | 1, 2, 3 |
| B17 | danilop_MCP2Lambda/main.py:30 | `mcp = FastMCP("MCP Gateway to AWS Lambda")` | `mcp = MCPServer("MCP Gateway to AWS Lambda")` | 2 |
| B18 | danilop_.../mcp_client_bedrock/main.py:44 | `                input_schema={'json': tool.inputSchema}` | `                input_schema={'json': tool.input_schema}` | 4 |

## Notes on the two genuinely uncertain cases

**B8a** — `rule_test/spec_reinstated/b8b_verification.md`'s side-finding
found this line's string argument *also* toggled without breaking the test
suite, but flagged that result as "not verified to the same standard" (no
dedicated negative control). `ground_truth/ground_truth.md` still counts B8a
as a required-edit site pending that confirmation, so the answer key here
does too, for consistency with the detection-stage GT this input list was
drawn from. A fix-generation agent that flags B8a to FLAG-FOR-HUMAN instead
of FIX, with a reason citing this exact ambiguity, is scored as a legitimate
hedge, not a miss — see `score.py`.

**B8c is the only site in this set where the identifier on the right of an
assignment must NOT change** (`fastmcp_mod.FastMCP = FastMCP` -> the
right-hand `FastMCP` stays put; the local class statement at line 12,
`class FastMCP:`, is correctly excluded from ground truth entirely and is
not part of this input list). This line is the sharpest trap in the whole
set: an agent renaming both sides (`fastmcp_mod.MCPServer = MCPServer`)
would produce a `NameError` on the scratch copy, since no `MCPServer`
identifier exists in that test file. Deliberately not flagged in the
`reason` field given to fix-generation agents.

## Scoring definitions

- **exact-match**: proposed replacement line, byte-identical after
  stripping trailing whitespace, to the "v2 (required)" column.
- **semantically-equivalent-but-different**: not exact-match, but
  normalizing whitespace and quote style (`'`/`"`) makes it identical, OR
  the proposed line parses to an AST that resolves to the same target
  module/identifier (e.g. reordered kwargs are NOT expected anywhere in
  this set, but harmless reformatting is).
- **wrong**: anything else — wrong identifier, wrong module path, edited
  the wrong token, or a proposed line that fails to parse.
