# B8b ground-truth verification — empirical, not argued

**Question**: does `tests/test_jmeter_server.py:12` (`class FastMCP:`) need
its own text edited to complete the MCP v1→v2 migration, as
`ground_truth.md` originally claimed (site "B8b")? Runs 1–2 of the
27-run reinstated-spec test argued no — a class's own bound identifier
doesn't have to match what it's exposed as. Settled by actually performing
the migration and running the test suite, not by further argument.

## Method

1. Copied the live `QAInsights_jmeter-mcp-server` repo to a scratch
   directory (not touching `repos/`).
2. Confirmed baseline: the **unmodified** (v1) test suite imports cleanly
   and passes 6/9 tests. The 3 failures are pre-existing, unrelated to the
   MCP migration (kwarg-count mismatches in `assert_awaited_with` — a
   pre-existing bug in this repo's test suite, present before any of my
   edits).
3. Performed the actual migration:
   - `jmeter_server.py`: `from mcp.server.fastmcp import FastMCP` →
     `from mcp.server.mcpserver import MCPServer`; `mcp = FastMCP("jmeter")`
     → `mcp = MCPServer("jmeter")`.
   - `tests/test_jmeter_server.py`: renamed the `sys.modules` key (B8d) and
     the module's exposed attribute (B8c) to match. **Line 12 (`class
     FastMCP:`) left untouched, deliberately** — this is the disputed line.
4. Ran the test suite again.
5. Ran a negative control: reverted *only* the B8c attribute rename
   (leaving everything else migrated) to confirm the harness actually
   detects a real break, not just that nothing was checked.

## Before/after (full diff)

`jmeter_server.py`:
```diff
-from mcp.server.fastmcp import FastMCP
+from mcp.server.mcpserver import MCPServer
 ...
-mcp = FastMCP("jmeter")
+mcp = MCPServer("jmeter")
```

`tests/test_jmeter_server.py`:
```diff
-fastmcp_mod = types.ModuleType('mcp.server.fastmcp')
+fastmcp_mod = types.ModuleType('mcp.server.mcpserver')
 class FastMCP:                          # <-- UNCHANGED, this is the test
     def __init__(self, *args, **kwargs):
         pass
     def tool(self, *args, **kwargs):
         def decorator(func):
             return func
         return decorator
     def run(self, *args, **kwargs):
         pass
-fastmcp_mod.FastMCP = FastMCP
-sys.modules['mcp.server.fastmcp'] = fastmcp_mod
+fastmcp_mod.MCPServer = FastMCP
+sys.modules['mcp.server.mcpserver'] = fastmcp_mod
```

## Results

| Condition | Import | Tests run | Pass | Fail |
|---|---|---|---|---|
| Baseline (v1, unmodified) | OK | 9 | 6 | 3 (pre-existing, unrelated) |
| Migrated, B8b left as `class FastMCP:` | OK | 9 | 6 | 3 (same 3, unchanged) |
| Negative control: B8c attribute rename reverted | **`ImportError: cannot import name 'MCPServer' from 'mcp.server.mcpserver'`** | 0 | — | — |

Migrating everything *except* the class statement produces test output
**byte-identical** to a fully-migrated baseline. The negative control
confirms the harness isn't just failing to notice a real break — reverting
the one line that actually matters (B8c) breaks the import immediately, on
the first line of `jmeter_server.py`.

## Why: the actual mechanism

`from mcp.server.mcpserver import MCPServer` resolves via two things only:
the `sys.modules['mcp.server.mcpserver']` dict entry, and a `getattr` for
`MCPServer` on whatever object sits there. Neither of those cares what
Python identifier the class object happens to be bound to inside the test
file's own module namespace — `class FastMCP:` merely creates a class
object and binds it locally to the name `FastMCP` *within
`test_jmeter_server.py`*, a binding `jmeter_server.py` never sees or
touches. What's actually inspected by the import system is the **attribute
name on the fake module** (`fastmcp_mod.MCPServer = FastMCP` — note this
line's *left-hand side* is what matters; the right-hand side is just a
variable reference to whatever object line 12 produced, under whatever
name) and the **`sys.modules` key**. Nothing in `jmeter_server.py` or the
test file inspects `.__name__`, does `isinstance()`, or otherwise cares
about the class's own declared identity.

## Verdict

**`ground_truth.md` was wrong on B8b under its own stated standard** ("only
lines that literally need to change count," the same standard already
applied to reject counting `ai.get_answer()`'s caller in MAGI just because
`ai.py`'s import broke). Corrected in `ground_truth/ground_truth.md`:
Target B total 21 → 20 sites, QAInsights 5 → 4 sites, test/mock class 4 →
3. Re-scoring below.

## Side finding, not verified, not corrected

The same setup incidentally showed that B8a's `types.ModuleType('mcp.server.
fastmcp')` constructor-argument string is *also* apparently non-load-bearing
— reverting only that string (while correctly migrating B8c and B8d) also
produced byte-identical test output to baseline. This wasn't what was asked
verified and hasn't been controlled to the same standard (no dedicated
negative control run for this specific line in isolation) — flagged here,
not acted on, pending a decision on whether it's worth the same treatment.

## Re-scoring: what changes

Only `QAInsights_jmeter-mcp-server`'s GT set shrinks by one (8→7 sites);
no other repo's ground truth changes; the ablation study (m0xai/danilop
only) is entirely unaffected. Recomputed with the corrected GT
(`score_reinstated.py`, GT dict updated):

| run | old recall (GT=34) | new recall (GT=33) | old QAInsights | new QAInsights |
|---|---|---|---|---|
| 1 | 33/34 = 97.1% | 33/33 = **100%** | 7/8 (missed only line 12) | 7/7 = **100%** |
| 2 | 33/34 = 97.1% | 33/33 = **100%** | 7/8 (missed only line 12) | 7/7 = **100%** |
| 3 | 30/34 = 88.2% | 30/33 = **90.9%** | 4/8 (missed 11,12,21,22) | 4/7 = 57.1% (missed 11, 21, 22) |

Precision is unaffected by this correction in every run (it was already
100% everywhere; removing a GT site nobody's output ever falsely proposed
against doesn't change any run's numerator or denominator on the precision
side).

**Runs 1 and 2 go from "missed one site" to "clean, 100% recall."** Their
disagreement with the old ground truth is resolved in *their* favor — they
were right, not hedging on a wrong instinct. **Run 3's miss shrinks from 4
to 3 but does not go away**: it still misses lines 11, 21, and 22, all
three of which *are* independently-required edits (the sys.modules key,
the exposed attribute, and — per the still-open side finding — possibly
the constructor string). Run 3's mechanism — misapplying the "downstream,
resolves automatically" framing to lines that don't actually resolve
automatically — is untouched by this correction. The per-run spread this
raised as the study's most interesting number is now **0, 0, 3 misses**
instead of 1, 1, 4: less alarming in raw miss-count, but the *shape* of the
finding (one run behaves qualitatively differently from the other two, on
the same input) is unchanged and, if anything, sharper now that runs 1–2
are confirmed fully correct rather than partially wrong.
