# Results — API drift recall/precision experiment

Detection agents were walled off from `ground_truth/ground_truth.md` and
`methodology_notes.md` for the entire run — each agent started cold, scoped
to exactly one repo directory, given only the relevant migration spec (never
the ground truth file or the difficulty taxonomy).

## Master table — agent vs. grep, recall & precision, per class, per target

| Target | Class | GT sites | Grep R / P | Agent R / P | Δ Precision |
|---|---|---|---|---|---|
| **A (openai)** | literal | 4 | 100% / 100% | 100% / 100% | 0 |
| A | helper-wrapped | 9 | 100% / 100% | 100% / 100% | 0 |
| A | **total** | **13** | **100% / 100%** | **100% / 100%** | **0** |
| **B (MCP)** | literal | 16 | 100% / 39.0% (16/41) | 100% / 48.5% (16/33) | +9.5 |
| B | decorator/registration | 0 | N/A / 0% (0/43) | N/A / — (0 proposed) | +43 fewer false leads |
| B | dynamic/reflection | 0 | N/A / N/A (0 proposed) | N/A / N/A (0 proposed) | tie (both clean) |
| B | test/mock | 4 | 100% / 100% | 100% / 100% | 0 (tie) |
| B | client-side | 1 | 100% / 12.5% (1/8) | 100% / 100% (1/1) | +87.5 |
| B | helper-wrapped | 0 | N/A / N/A | N/A / N/A | — |
| B | **total** | **21** | **100% / 21.9% (21/96)** | **100% / 55.3% (21/38)** | **+33.4** |

**Recall is 100%/100% on every class, both targets, both methods.** The
entire agent-vs-grep story is precision.

## Where the delta comes from

- **Target A: zero delta.** All 4 agent outputs were identical to the grep
  baseline's true positives, zero false positives on either side. Confirms
  the earlier finding: Target A is 100% grep-solvable regardless of method.
- **Target B decorator/registration — the single biggest agent win.** Grep
  proposed 43 false leads across the 5 repos (18 `@mcp.tool()` in
  securityfortech, 6 in QAInsights, 18 `add_tool()` in m0xai, 1 in
  tonyzorin). Every one of the 9 agents independently read the spec's own
  caveat and excluded every decorator/`add_tool()` call, with explicit
  reasoning in the transcript. Zero false positives across 43 opportunities
  to get it wrong.
- **Target B client-side — second-biggest win.** Grep flagged 7 unchanged
  `ClientSession`/`stdio_client`/`StdioServerParameters` construction lines
  alongside the 1 real break. The danilop agent explicitly distinguished
  plain `ClientSession.call_tool()` from the different, actually-broken
  `ClientSessionGroup.call_tool()` — a distinction the orchestrator only
  caught after careful manual reading during ground-truth construction.
- **securityfortech's httpx-CLI-tool collision.** `tools/httpx.py` wraps the
  `httpx` command-line recon tool, unrelated to the Python `httpx` library
  the SDK uses internally. Grep, primed by the guide's "httpx→httpx2"
  bullet, walked straight into it (4 FP: 2 docstrings, 1 subprocess command
  list, 1 import). Every agent that saw this repo correctly identified it as
  a naming coincidence. This specific trap was not anticipated when the
  decoy list was built — it emerged from the measurement itself.
- **The agent's one real, systematic mistake.** On m0xai (14 instances) and
  danilop (3 instances), agents flagged every function signature typed
  `ctx: Context` as a separately-broken line, reasoning that the annotation
  "depends on" the broken import. This is a category error: fixing the one
  import line (`from mcp.server.fastmcp import Context` ->
  `from mcp.server.mcpserver import Context`) automatically repairs every
  downstream annotation; none of those 17 lines need an independent edit,
  under the same "only lines that literally need to change count" standard
  applied consistently everywhere else in ground truth (e.g., no caller of
  `ai.get_answer()` in MAGI was counted just because `ai.py`'s import broke).
  Real, explainable, consistent failure mode — not random noise — and the
  entire reason Target B literal-class precision (48.5%) isn't higher.

## Ship recommendation

The agent, not grep — but not as-is. Recall is identical, so grep's only
case is "free and instant," but a precision gap this size (21.9% vs 55.3%
overall, 0% vs clean on the decorator class specifically) means grep output
needs a human to manually reject roughly 4 of every 5 proposed sites before
it's usable — not a tool, a worse version of reading the migration guide
yourself. The agent's output needs a human to reject roughly 2 in 5 —
better, but not yet "trust the list."

Ship it with one fix first: a rule separating *definition/import sites*
(genuinely broken, must change) from *usage sites of a name that came from a
broken import* (not broken, resolves automatically once the import is
fixed). That single rule would have eliminated all 17 of the agent's false
positives and pushed Target B literal precision from 48.5% to 100% — turning
a 33-point precision edge over grep into something close to a clean sweep on
the one axis where the agent still stumbled.
