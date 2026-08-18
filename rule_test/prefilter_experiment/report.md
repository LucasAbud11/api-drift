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
repos. Stage A's module-qualified pattern is specific to this target's
actual API shape — a different migration guide would need its own
qualified-relevance pattern. The *zero-GT-loss discipline* generalizes;
the specific regexes do not, and shouldn't be assumed to transfer
without the same measure-before-trust step applied here.

**Superseded by the hardening pass below**: the whitelist mechanism
described in "Bug 1" above (a fixed 2-item list of load-bearing string
forms) was removed entirely — see "Hardening pass" for why passing this
study's own zero-GT-loss test was never sufficient grounds to trust it
on a host this filter has never seen.

## Hardening pass: fail-safe by construction, not by passing this study's test set (2026-08-18)

Zero GT loss on this study's own repos is not the same claim as "cannot
silently drop a real site." A rule can pass every test here and still
drop on ambiguity — it just means this study's GT never happened to
exercise the ambiguous case. The prefilter is the one component in the
whole pipeline that *can* cause silent, unrecoverable recall loss (grep
is exhaustive by construction; the agent only judges what it's handed),
so it was audited against a stricter standard: **a candidate is dropped
only when the drop reason is provably, structurally certain — never
because no positive evidence of relevance was found.** Absence of a
match is not proof of absence of relevance.

**Audit result — two rules violated this, both by the same mechanism at
different scopes:**

1. **Stage A (file-level).** "This file has no module-qualified
   reference to the package" was being treated as certain, but it's
   really "no *known* reference *form* was found" — aliased imports,
   `importlib.import_module`, `__import__`, and dynamically-built
   module names are all real Python and none are fully enumerable by a
   static regex. Fixed by broadening the pattern to cover all of the
   above, defaulting an unreadable file to *keep* (was: drop) on
   `OSError`, and logging every drop with the exact file/line/reason —
   the residual risk (a reference form no regex enumerates) is reduced
   and made auditable, not eliminated. This is flagged explicitly in
   the module docstring as the one stage that cannot reach true
   certainty by construction.

2. **Stage B (string-literal level) — the same bug the stage-B
   whitelist was already a patch for.** The original fix for "any
   string on the line" (too coarse) was a 2-item whitelist of the
   specific string forms this study's own known GT needed
   (`types.ModuleType(...)` args, `sys.modules[...]` keys). That's the
   identical certainty violation, just scoped down: "not on a
   hand-built whitelist of forms I've seen before" is not proof a
   string is safe to drop, only proof it isn't one of the two forms
   this study happened to need. **Fixed by removing the whitelist
   mechanism entirely** — stage B now drops only what's structurally
   certain (a `#` comment token via `tokenize`, or a real docstring —
   first statement of a module/class/function body — via `ast`), and
   keeps every other string-literal match unconditionally, letting the
   agent adjudicate it like any other candidate.

Stage C (duplicate collapse) was audited and found not to need changes:
it isn't a drop at all, it's provably lossless via expansion (verified
directly, not assumed), so the certainty concern doesn't apply.

**Every drop, all three stages, now logs `{stage, rule, file, line,
snippet, matched_span, reason}`** to `droplog_<scale>.json` — any
exclusion is auditable after the fact without re-running anything.

**A regression the broadening introduced, caught before shipping the
numbers below:** the broadened stage-A pattern's qualified-reference
component (`{pkg}\.\w+`) initially had no leading word boundary, so it
matched the substring `mcp.something` *inside* an unrelated identifier
like `youtrack_mcp.something` — not a real qualified reference to the
`mcp` package, just a coincidence of a locally-named object ending in
the same three letters. Confirmed directly: `pat.search("youtrack_mcp.
something")` matched. This isn't a safety violation (it errs toward
over-keeping, the safe direction under the fail-safe principle), but it
silently cost reduction power — every file in a repo like
`youtrack_mcp` was passing stage A regardless of whether it touched the
SDK. Fixed with a leading `\b`, re-measured.

**Result: the fail-safe redesign, once this regression was fixed, costs
nothing.** Same reduction power as the pre-hardening numbers, zero GT
loss reconfirmed at every stage, both targets, both scales — now with
construction-level safety and a full audit trail instead of
empirically-tuned safety and none:

| scale | raw | final | reduction | GT covered |
|---|---|---|---|---|
| Target A, small | 13 | 9 | 30.8% | 13/13 |
| Target A, diluted | 13 | 9 | 30.8% | 13/13 |
| Target B, small | 587 | 111 | 81.1% | 20/20 |
| Target B, diluted | 1121 | **111** | **90.1%** | 20/20 |

(Identical to the table at the top of this report. The one thing that
changed is *why* those numbers are trustworthy: not "this passed the
known GT," but "every remaining drop is either structurally certain or
logged with the exact reason it wasn't kept.")
