# Deterministic pre-filter: candidate-set reduction with zero GT loss

Grep's candidate set is exhaustive by construction, which is exactly why
it's also expensive: every candidate the agent has to individually
adjudicate costs the same whether it's a real site or Django's own
`get_context()`. This experiment inserts a mechanical, LLM-free filter
between grep and the agent, built from the three ideas given: drop
candidates in files that never reference the target package, drop
matches inside comments/docstrings/unrelated string literals, and
collapse identical repeated matches within a file into one adjudication.
**Constraint: zero GT loss, absolute.** All three stages were measured
independently and cumulatively against all 4 blind-vocabulary candidate
sets from the previous experiment, with GT coverage checked after every
single stage before moving on.

## Result

| scale | raw candidates | final | reduction | GT covered |
|---|---|---|---|---|
| Target A, small | 13 | 9 | 30.8% | **13/13** |
| Target A, diluted | 13 | 9 | 30.8% | **13/13** |
| Target B, small | 587 | 111 | 81.1% | **20/20** |
| Target B, diluted | 1121 | **111** | **90.1%** | **20/20** |

Zero GT sites lost at any stage, at any scale, either target. The
diluted Target B set — the one that was unreliable and expensive at
1121 candidates — drops to 111, roughly the size of the small-scale
runs that were reliable throughout this whole study.

## Two bugs the "zero loss" constraint caught before this could ship

The constraint did real work — the first version of stage B failed it
outright, and got rejected rather than patched-and-shipped-anyway:

**Bug 1 — line-level string detection was too coarse.** The first
implementation flagged an entire line as "inside a string, drop it" if
*any* string literal appeared anywhere on that line, which silently
killed 7 real GT sites like `mcp = FastMCP("jmeter")` (line has a real
code match — the `FastMCP` construction — plus an unrelated string
argument `"jmeter"`) and `def create_server(...) -> FastMCP:` (the
default parameter `"0.0.0.0"` is a string, `FastMCP` in the return
annotation is not). Fixed by re-matching the exact vocabulary regex
against the line to get precise column spans, then checking whether the
*specific matched span* — not the whole line — falls inside a
comment/string token span. A match with real code anywhere in its own
span is kept regardless of what else shares the line.

**Bug 2 — the file-relevance filter used a bare token, which is
answerable by naming coincidence.** Checking "does this file contain
the substring `mcp` anywhere" passes trivially for every file in a repo
named `youtrack_mcp` or `trello-mcp-server`, whether or not that file
ever touches the actual SDK — confirmed empirically:
`youtrack_mcp/api/client.py`, `issues.py`, `projects.py` and 6 other
files never import `mcp` at all, but "passed" the bare-token filter on
their own package name alone, leaving hundreds of `logger.error()`/
`data=` false positives in place. Fixed by requiring a module-qualified
pattern instead — a real `import mcp`/`from mcp` statement, or a
literal `mcp.server.`/`mcp.client.`/`mcp.types` reference, or (to keep
the one legitimate exception) a `sys.modules['mcp...]` registration,
which is what the QAInsights test stub does instead of a normal import.
This alone took stage A's yield on Target B diluted from 337 candidates
down to 137 — the dominant lever in the whole filter.

## Per-stage breakdown (Target B diluted, 1121 -> 111)

| stage | mechanism | candidates remaining |
|---|---|---|
| raw (blind vocab) | — | 1121 |
| + A (module-qualified file relevance) | drops files that never actually reference `mcp` (Django noise, and same-repo-but-unrelated files like `youtrack_mcp/api/*.py`) | 137 |
| + B (comment/docstring/string, column-aware) | drops prose mentions, log-message text, dict-literal wire-format keys — keeps the 3 sys.modules/ModuleType string-literal GT sites via an explicit whitelist | 133 |
| + C (collapse identical duplicates per file) | one adjudication per unique line-text-per-file, expanded back to every line before scoring | **111** |

Stage A does nearly all the work (1121 -> 137, 87.8% of the total
reduction on its own). Stage B is a small additional cut (4 items) at
this scale because most of what's left after A is genuine code, not
prose — the earlier composition/blind-vocab runs' large REJECT buckets
were dominated by *file-irrelevant* noise (Django, unrelated repo files),
not by comment/docstring noise, so A was always going to be the bigger
lever once refined. Stage C adds a modest further cut (22 items
collapsed, e.g. 4-5x repeated `ctx.error(error_msg)` calls across
near-identical handler functions in the same file) without losing any
information: every collapsed representative still expands back to every
original line number before scoring, verified directly (not assumed) —
`TomaszRewak_MAGI/ai.py`'s three byte-identical `openai.api_key = key`
lines (6, 51, 64), each an independently required GT site per the
counting convention despite sharing text, collapse to one adjudication
and correctly expand back to all three.

## What this doesn't claim

This filter is tuned against and validated on the study's own 5+4 known
repos. Stage A's module-qualified pattern (`mcp.server.`, `mcp.client.`,
etc.) and the sys.modules whitelist in stage B are specific to this
target's actual API shape — a different migration guide would need its
own qualified-relevance pattern and its own accounting for whichever
syntactic form (if any) legitimately puts a real site inside a string
literal. The *zero-GT-loss discipline* generalizes; the specific regexes
do not, and shouldn't be assumed to transfer without the same
measure-before-trust step applied here.
