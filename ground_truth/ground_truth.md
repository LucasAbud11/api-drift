# Ground truth — API drift recall experiment

Built via the locked search procedure in `../methodology_notes.md`. This file
and its directory are the ground-truth boundary: the detection agent must
never read this directory or any file in it.

Difficulty-class assignment rule (applied for consistency, since raw grep
visibility doesn't track call-depth): a site is `test/mock` if it lives in a
test file; else `client-side` if it's on the MCP client-consumption side;
else `decorator/registration` if the site IS a decorator/registration call
itself; else `dynamic/reflection` if the reference is constructed via
getattr/dir/string-building rather than a static token; else `literal` if
depth 0-1 (in the entry file or the first function invoked from it) with no
intervening user-defined helper; else `helper-wrapped` (depth >= 2).

---

## TARGET A — OpenAI v0.x -> v1.x

Ground-truth vocabulary (fixed at study start): `openai.<Namespace>.create(...)`
module-level calls, `openai.error.*` exception references, and module-level
`openai.api_key` / `api_base` / `organization` attribute assignment. Response
object dict-vs-attribute access is explicitly OUT of scope (not part of the
original spec, and uncertain whether it actually breaks given v1's
backward-compat accessors) — noted here so the boundary isn't silently redrawn
later.

### TomaszRewak/MAGI (6 sites)

| # | File:Line | Snippet | Depth | Class |
|---|---|---|---|---|
| A1 | ai.py:6 | `openai.api_key = key` | 2 | helper-wrapped |
| A2 | ai.py:7 | `openai.ChatCompletion.create(` | 2 | helper-wrapped |
| A3 | ai.py:51 | `openai.api_key = key` | 2 | helper-wrapped |
| A4 | ai.py:52 | `openai.ChatCompletion.create(` | 2 | helper-wrapped |
| A5 | ai.py:64 | `openai.api_key = key` | 2 | helper-wrapped |
| A6 | ai.py:65 | `openai.ChatCompletion.create(` | 2 | helper-wrapped |

All reached via: Dash `@callback` in main.py -> `ai.get_answer` /
`ai.classify_answer` / `ai.is_yes_or_no_question`.

### franalgaba/chatgpt-telegram-bot-serverless (1 site)

| # | File:Line | Snippet | Depth | Class |
|---|---|---|---|---|
| A7 | app.py:41 | `message = openai.ChatCompletion.create(` | 2 | helper-wrapped |

Reached via: `message_handler` (Lambda entry) -> dispatcher-registered
`process_message`/`process_voice_message` -> `ask_chatgpt`. No module-level
`api_key` assignment found (repo relies on SDK's automatic `OPENAI_API_KEY`
env pickup — confirmed absent by direct read, not assumed).

### batuhantoker/Flask-OpenAI-Chatbot (2 sites)

| # | File:Line | Snippet | Depth | Class |
|---|---|---|---|---|
| A8 | app.py:8 | `openai.api_key = "OPENAI_API"` | 0 | literal |
| A9 | app.py:48 | `output = openai.ChatCompletion.create(` | 4 | helper-wrapped |

A9 is the deepest site in the whole study: Flask route -> `get_response` ->
`chat` -> `chatcompletion`.

### g0ldencybersec/sus_params (4 sites)

| # | File:Line | Snippet | Depth | Class |
|---|---|---|---|---|
| A10 | PoC.py:7 | `openai.api_key = os.getenv("OPENAI_API_KEY")` | 0 | literal |
| A11 | PoC.py:11 | `response = openai.ChatCompletion.create(` | 2 | helper-wrapped |
| A12 | PoC.py:192 | `except openai.error.RateLimitError as e:` | 0 | literal |
| A13 | PoC.py:201 | `except openai.error.ServiceUnavailableError as e:` | 0 | literal |

A12/A13 sit directly in the `if __name__` main loop's except clauses — same
file, same repo, opposite end of the depth range from A11.

**Target A total: 13 sites. literal=4, helper-wrapped=9, decorator/registration=0,
dynamic/reflection=0, test/mock=0, client-side=0 (N/A — no client/server split
in these repos).**

---

## TARGET B — MCP Python SDK v1 -> v2

Ground-truth vocabulary: confirmed against the fetched migration guide, not
assumed. Confirmed NOT breaking (and therefore explicitly excluded, not just
omitted): `@mcp.tool()`/`@mcp.resource()`/`@mcp.prompt()` decorators, `.add_tool()`,
`ctx.error()`/`ctx.info()` without `extra=`, `get_context()` (unused in all 5
repos anyway), `mcp.types` imports (guide states these remain aliased/working).

### tonyzorin/youtrack-mcp (3 sites)

| # | File:Line | Snippet | Depth | Class |
|---|---|---|---|---|
| B1 | main.py:10 | `from mcp.server.fastmcp import FastMCP` | 0 | literal |
| B2 | main.py:25 | `def create_server(...) -> FastMCP:` | 0 | literal |
| B3 | main.py:27 | `mcp = FastMCP(` | 0 | literal |

**Documented rejection (see methodology notes for full evidence):** the
reflection-based tool loader (`loader.py` + `mcp_wrappers.py`, 20+ methods
across `youtrack_mcp/tools/*` and `youtrack_mcp/api/*`) was flagged as the
likely hardest recall case in the set. Full-tree grep for all 13 categories
of the breaking-change spec found zero hits outside `main.py`. Not a
ground-truth site anywhere in the reflected code.

### QAInsights/jmeter-mcp-server (4 sites)

| # | File:Line | Snippet | Depth | Class |
|---|---|---|---|---|
| B4 | main.py:2 | `from mcp.server.fastmcp import FastMCP` | 0 | literal |
| B5 | main.py:9 | `mcp = FastMCP("jmeter")` | 0 | literal |
| B6 | jmeter_server.py:4 | `from mcp.server.fastmcp import FastMCP` | 0 | literal |
| B7 | jmeter_server.py:23 | `mcp = FastMCP("jmeter")` | 0 | literal |
| B8a | tests/test_jmeter_server.py:11 | `fastmcp_mod = types.ModuleType('mcp.server.fastmcp')` | 0 | test/mock |
| B8c | tests/test_jmeter_server.py:21 | `fastmcp_mod.FastMCP = FastMCP` | 0 | test/mock |
| B8d | tests/test_jmeter_server.py:22 | `sys.modules['mcp.server.fastmcp'] = fastmcp_mod` | 0 | test/mock |

Re-grained from a single block-level site (originally "B8, lines 9-22") into
line-level sites for scoring consistency with every other entry in this
table. Lines 9-10 of that block (`sys.modules['mcp'] = ...`,
`sys.modules['mcp.server'] = ...`) reference module paths that are still
valid in v2 and do NOT need to change — excluded. Lines 13-20 (the stub
class body: `__init__`/`tool`/`run`) don't reference any renamed token —
excluded.

**Correction (2026-08-18, empirically verified — see
`rule_test/spec_reinstated/b8b_verification.md`): line 12 (`class FastMCP:`)
was originally counted as a fourth site ("B8b") and has been removed.** The
migration was actually performed (a live copy of this repo, migrated and
run under `python -m unittest`, not argued about): `jmeter_server.py`'s
import/construction were changed to `MCPServer`, and the test's `sys.modules`
key (B8d) and exposed attribute (B8c) were renamed accordingly, while the
class *statement* on line 12 was deliberately left reading `class FastMCP:`.
The test suite ran identically to a fully-migrated baseline — same 6/9 pass,
same 3 pre-existing (migration-unrelated) failures, zero import errors. A
negative control confirms the harness is sound: reverting *only* the B8c
attribute rename does break the import immediately (`ImportError: cannot
import name 'MCPServer'`). The class statement's own bound name has no
effect on what `jmeter_server.py`'s import sees — only the module object's
exposed attribute name (B8c) and its `sys.modules` key (B8d) are load-bearing;
`class FastMCP:` could be renamed for cosmetic consistency but is not a site
that must change under this study's own standard ("only lines that literally
need to change count").
**Not separately verified: B8a's `types.ModuleType('mcp.server.fastmcp')`
constructor-argument string may also be non-load-bearing (only the
`sys.modules` key at B8d appears to matter) — noticed as a side effect of
the same test, not requested, not corrected here pending confirmation.**

Note: `main.py` (B4-B5) is a dead/unused duplicate entry point — `jmeter_server.py`
is what's actually run — but it's live, valid, importable code that still
breaks. Included, flagged as dead code rather than silently excluded.

B8 is the best test/mock specimen in the study: the test fakes the entire
`mcp.server.fastmcp` module tree, including a stub `FastMCP` with a working
`.tool()` decorator, specifically so the import in `jmeter_server.py` succeeds
without the real SDK. When production code migrates to
`mcp.server.mcpserver.MCPServer`, this stub has to move with it or the test
starts mocking a module path nothing imports anymore.

### securityfortech/secops-mcp (2 sites)

| # | File:Line | Snippet | Depth | Class |
|---|---|---|---|---|
| B9 | main.py:7 | `from mcp.server.fastmcp import FastMCP` | 0 | literal |
| B10 | main.py:26 | `mcp = FastMCP(name="secops-mcp",` | 0 | literal |

12 `tools/*.py` files, each imported and wrapped with `@mcp.tool()` in
main.py — none of the 12 files import `mcp` themselves, none are broken.

### m0xai/trello-mcp-server (5 sites)

| # | File:Line | Snippet | Depth | Class |
|---|---|---|---|---|
| B11 | main.py:6 | `from mcp.server.fastmcp import FastMCP` | 0 | literal |
| B12 | main.py:23 | `mcp = FastMCP("Trello MCP Server")` | 0 | literal |
| B13 | server/tools/board.py:8 | `from mcp.server.fastmcp import Context` | 0 | literal |
| B14 | server/tools/card.py:8 | `from mcp.server.fastmcp import Context` | 0 | literal |
| B15 | server/tools/list.py:8 | `from mcp.server.fastmcp import Context` | 0 | literal |

B13-B15 break not because `Context`'s behavior changed (it didn't) but because
its *import path* moved along with the rest of `mcp.server.fastmcp.*` per the
"all submodules move" rule in the migration guide — verified directly against
that clause, not inferred.

**Documented rejection:** `server/tools/tools.py`'s 18 explicit
`mcp.add_tool(board.get_board)`-style calls — an imperative, hand-enumerated
registration list — checked and confirmed NOT broken (`add_tool()` signature
unchanged). **Documented rejection:** `server/utils/trello_api.py` imports
`httpx` and uses `httpx.AsyncClient`/`httpx.HTTPStatusError` for the app's own
Trello REST calls — unrelated to the MCP SDK's internal `httpx`->`httpx2`
transport change, confirmed by reading the actual usage, not just matching
the keyword.

### danilop/MCP2Lambda (3 sites)

| # | File:Line | Snippet | Depth | Class |
|---|---|---|---|---|
| B16 | main.py:6 | `from mcp.server.fastmcp import FastMCP, Context` | 0 | literal |
| B17 | main.py:30 | `mcp = FastMCP("MCP Gateway to AWS Lambda")` | 0 | literal |
| B18 | mcp_client_bedrock/main.py:44 | `input_schema={'json': tool.inputSchema}` | ~1 | client-side |

B18 is the only confirmed camelCase->snake_case field-rename true positive in
the whole study — `tool.inputSchema` must become `tool.input_schema`. It's on
the client side, inside the loop that registers discovered MCP tools with the
Bedrock Converse agent.

**Documented rejection (the second "I was wrong about where the hard case
lives" instance):** `create_lambda_tool()` (main.py:130-147) dynamically
builds a tool function per AWS Lambda function and applies
`mcp.tool(name=tool_name)(lambda_function)` in a loop over
`lambda_client.list_functions()` results — genuine dynamic construction, no
static `@mcp.tool()` token anywhere for these tools. Checked directly against
the confirmed-unchanged `.tool()` decorator and found no `extra=`/`get_context()`
usage nearby. Zero true positives here despite being structurally the most
"dynamic" code in Target B.

**Target B total: 20 sites (originally 21; B8b removed 2026-08-18, see
QAInsights section above). literal=16, helper-wrapped=0,
decorator/registration=0, dynamic/reflection=0, test/mock=3, client-side=1.**
