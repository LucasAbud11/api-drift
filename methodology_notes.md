# Methodology notes — API drift recall experiment

## Lesson 1: detection difficulty is a property of (change × codebase), not codebase alone

Tonyzorin/youtrack-mcp has genuinely hard reflection-based tool discovery
(`dir()`/`getattr()` over 5 classes across 6+ files, zero static `@mcp.tool()`
decorators on the actual tool methods). That mechanism is real and would be
brutal to trace for a breaking change that touched `Context`, tool parameter
schemas, or per-method decorators.

The MCP v1->v2 change that actually shipped is a FastMCP->MCPServer rename plus
a set of field/behavior changes that never reach into the reflected methods —
none of them import `mcp`, reference `Context`, or touch any renamed field.
Ground truth for tonyzorin collapses to 3 lines in `main.py`.

**Conclusion:** the "reflection defeats static analysis" thesis is NOT disproven
by this result — it is untested by this particular change. Tonyzorin remains in
the study as a precision trap (many structurally-plausible false-positive sites
for an agent that pattern-matches "tool registration" without checking whether
the specific site touches anything that actually changed), not as a recall
test for the dynamic/reflection class. `danilop/MCP2Lambda`'s `create_lambda_tool`
(string-built tool names, decorator applied in a loop over discovered Lambda
functions) is the primary recall case for dynamic/reflection instead.

## Lesson 2: a specimen of the exact error the detection agent will make

Initial file-count for tonyzorin used the pattern `grep "from mcp"`, which
substring-matches `from youtrack_mcp.api import mcp_wrappers` — inflating the
"files touching the API" count from 1 to 2. This is a real, caught instance of
the false-positive class a text-matching detection strategy will produce:
matching the package name as a substring of an unrelated local package name.
Documented here rather than silently fixed, because the detection agent is
expected to make this exact mistake and precision scoring should watch for it.

## Search procedure (mandatory, same order, every repo)

Applied to avoid finding structure "by accident" (as happened with tonyzorin's
`youtrack_mcp/api/` subpackage, found via a test import rather than by design).

1. **Full directory + file tree first**, before any grep. `find <repo> -type f
   -name '*.py' | sort`. Build a mental inventory of every source directory
   before searching it. No grep result is trusted as "complete coverage" until
   it's been checked against this tree.
2. **Manifest check**: read `requirements*.txt` / `pyproject.toml` / `setup.py`
   to confirm the exact import name(s) the repo depends on (e.g. `openai`,
   `mcp`, `mcp[cli]`, `fastmcp` as a standalone PyPI package are NOT the same
   import surface — check which is actually pinned).
3. **Broad import grep, word-boundary safe** — never bare substring. Use
   anchored patterns: `grep -rnE '^\s*(from|import)\s+openai(\.|,|\s|$)'` /
   `^\s*(from|import)\s+mcp(\.|,|\s|$)` — this is the fix for the Lesson 2 bug.
4. **Full breaking-change vocabulary grep across the ENTIRE repo tree**
   (not just files caught by step 3) — covers cases where the API is touched
   without a top-of-file import (re-exports, `importlib`, passed-in objects).
5. **Dynamic-construction grep**, dedicated pass: `importlib`, `__import__`,
   `getattr(`, `globals()`, `locals()`, `dir(`, f-string/`.format(`/`%`
   patterns building attribute or module names.
6. **Test/mock grep**, dedicated pass: `mock`, `Mock`, `patch`, `MagicMock`,
   `monkeypatch`, `unittest.mock`, `conftest.py` fixtures — intersected against
   the API surface found in steps 3-4.
7. Every hit gets read in context before being accepted or rejected as a true
   ground-truth site. Rejections are recorded, not silently dropped, per the
   `mcp.add_tool()` case (site exists, term matches, but that specific method
   didn't change signature — not a ground-truth site).

## Lesson 3 (first-order finding, not a footnote): dynamic construction and the actual breaking surface did not intersect, anywhere

Across all 9 repos, three separate structural axes came back empty for
Target B: `dynamic/reflection`, `decorator/registration`, and
`helper-wrapped` are all **zero true-positive sites**. Every real Target B
breaking site is either a depth-0 literal (import/construction/type-annotation
line), one client-side field-access site, or one test-mock site. This was
checked, not assumed — full-tree grep against all 13 categories of the
confirmed migration guide, on every repo.

This is being recorded as a first-order result because it bears directly on
whether an agent is expected to beat grep on this problem: for this real,
recent, unmemorized migration, on 5 real MCP server repos with real structural
variety (reflection-based loaders, imperative registration lists, layered
services, dynamic per-Lambda tool generation), **grep for the renamed import
token would have found 16 of 18 ground-truth sites outright**, missing only
the one client-side field-access rename and the one test-mock stub. If that
pattern holds at scale, the case FOR an agent-based tool over a grep/AST
linter rests on the client-side and test-mock classes (and on precision, where
tonyzorin's 20+ structurally-plausible-but-unbroken sites are the real test),
not on the dynamic/discoverability story that motivated picking MCP as
Target B in the first place.

### Two documented "I was wrong about where the hard case lives" instances

1. **tonyzorin's reflection-based tool loader** (`loader.py` using
   `dir()`/`getattr()` over 5 classes across 6+ files under `youtrack_mcp/tools/`
   and `youtrack_mcp/api/`) — claimed as "the case that decides whether this
   product has any reason to exist." Full-tree grep against all 13
   breaking-change categories: zero hits outside `main.py` (3 lines). The
   reflected methods are plain business logic; none reference `mcp`, `Context`,
   or any renamed field. Mechanism is real, doesn't reach this change.
2. **danilop's `create_lambda_tool`** — dynamically applies `mcp.tool(name=...)`
   in a loop over discovered AWS Lambda functions, proposed as the fallback
   primary case for dynamic/reflection after (1) fell through. Checked against
   the confirmed-unchanged `.tool()` decorator signature and confirmed no
   `extra=`/`get_context()` usage nearby: zero true positives. Same failure
   mode as (1), caught before being asserted as ground truth this time rather
   than after.

### Why this class resists SDK-level breaking changes structurally (not just this one)

Both dynamic-construction sites in this repo set (tonyzorin's reflection,
danilop's Lambda-name loop) operate on plain Python business-logic objects —
methods that return strings/dicts, functions that wrap Lambda invocations.
Neither touches an MCP protocol type, a `Context` method, or a decorator
argument; the SDK-facing surface is confined to the *registration boundary*
(`mcp.add_tool(...)`, `mcp.tool(...)`), which sits outside the dynamically-
generated code, not inside it. An SDK breaking change would need to touch the
registration boundary itself (decorator/`add_tool` signature, `Context`
injection contract, tool-name validation rules) to reach code discovered this
way — and the change that actually shipped in v2 left that boundary alone.
This is a structural property of "thin dynamic dispatch over an unrelated
business-logic layer," not an accident of these two specific repos.

## Lesson 4: correction to the "mcp" substring specimen, and the detection-run headline result

The Lesson 2 specimen ("`grep 'from mcp'` matches `from youtrack_mcp`") had
the wrong mechanism. Re-checked directly: `grep -rn "from mcp"` across the
whole tonyzorin tree returns exactly 1 hit — the real
`from mcp.server.fastmcp import FastMCP` line. Zero false positives from
that pattern alone. The actual false positive came from the OTHER half of
the original compound pattern, `"import mcp"`, matching
`from youtrack_mcp.api import mcp_wrappers` — the substring landed on the
module name `mcp_wrappers`, not on the `youtrack_mcp` package prefix as
originally described. Specimen still valid (a naive substring search does
produce a false positive here), mechanism corrected.

When the full detection run (agent vs. grep baseline, all 9 repos, walled
off) was scored against ground truth: **recall was 100%/100% for every
difficulty class, both targets, both methods.** Every ground-truth site that
existed was found by both the naive grep baseline and every detection
agent. The entire measured difference between the two methods was
precision — grep 21.9% vs agent 55.3% on Target B overall, driven almost
entirely by the decorator/registration class (grep: 43 false leads, agent:
0) and the client-side class (grep: 12.5% precision, agent: 100%). Full
breakdown in `results.md`.

## Lesson 5: a wrong label propagated across many artifacts because nothing re-checked the source

Line 77 of this file, written near the start of the study, already has the
correct framing: Target B is "this real, recent, unmemorized migration."
That was accurate then and is accurate now — MCP Python SDK v1→v2 is a
real migration with a real public guide (py.sdk.modelcontextprotocol.io),
released July 2026, chosen specifically because its recency rules out
memorization, not because it was made up.

At some later point, in some artifact, "unmemorized" or "this study's own
Target B" drifted into "synthetic Target B" — and once that label existed
in one file, it was copied, paraphrased, and asserted as established fact
in at least one other (`rule_test/composition_experiment/report.md`,
"this study's synthetic Target B") and then, worse, generalized into an
entire paragraph of a later external-facing report (`REPORT.md`'s first
draft: "an *invented* migration... it doesn't exist") without anyone
re-deriving it from the original source or checking it against the live
guide. Caught only when a reader who knew the guide was real asked the
report to show its work, and a direct fetch of the actual URL confirmed
the guide's details — including specific ones (the `httpx`→`httpx2`
dependency swap, `NoBackChannelError`, the `2026-07-28` protocol-version
marker) that had been assumed too oddly specific to be real, and were
exactly the details that would have disconfirmed the wrong label fastest
if anyone had checked.

This is the same mechanism as the reconstruction-from-memory failures
documented elsewhere in this study (`results.md` revision 5's silent
data corruption, the circular precision reconstruction) — not a copy-paste
accident but the general failure mode: a claim gets asserted once without
being freshly re-derived from its source, and every subsequent artifact
that cites it is citing the claim, not the source, so the error compounds
invisibly instead of surfacing. The fix pattern is the same one already
in place for run data (`validate_run_file()` refusing to trust anything
not read fresh from disk): treat any claim about the study's own setup —
not just its results — as something to re-verify against the primary
source before repeating it in a new document, especially an
external-facing one.

## Difficulty class taxonomy (fixed for the whole study)

- `literal` — direct call, textually obvious
- `helper-wrapped` — reached through 1+ intermediate user-defined functions
- `decorator/registration` — `@mcp.tool()`, `add_tool()`, etc., where the
  registration mechanism itself is a site (not just the object it registers)
- `dynamic/reflection` — `getattr`/`dir()`, string-built names, config-driven
- `test/mock` — mocked or patched call sites
- `client-side` — consumer of an SDK client (vs. server/producer side)
