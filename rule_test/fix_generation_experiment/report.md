# Fix-generation stage — first result, targetB_small (5 repos, 20 sites, 3 runs)

Detection finds sites. It has never produced a fix. This is the first test
of the second half: given a confirmed site, generate the corrected code.

## Setup

**Input**: `confirmed_sites_targetB_small.json` — 20 sites (file, line, a
short reason stating *why* the site was flagged, never the replacement
text). This is what a real pipeline hands to fix-generation: the union of
detection's PROPOSE bucket and any FLAG-UNCERTAIN a human accepted.
targetB_small's detection stage was independently measured at 100%
surfaced recall / 100% precision across 3 runs
(`rule_test/prefilter_experiment/transitive_verification/scoring_results.json`),
so the 20-site ground-truth list is what a human-confirmed detection output
for this host actually is — using it as fix-generation's input is not
circular with what's being tested here: knowing a line must change says
nothing about what it must change *to*.

**Answer key** (`fix_ground_truth.md`): built by direct source read of all
20 sites in `repos/` + the migration spec, same standard as
`ground_truth/ground_truth.md`. Flags the one real trap in the set: at
`QAInsights_jmeter-mcp-server/tests/test_jmeter_server.py:21`
(`fastmcp_mod.FastMCP = FastMCP`), only the left-hand attribute name may
change — the right side is a reference to a distinct local test class
(line 12, not itself a confirmed site) and renaming it produces a
`NameError`. Also carries forward the one open question from
`b8b_verification.md`'s side-finding (B8a's constructor-argument string,
not verified to the same standard as B8c/B8d) as a legitimate place to
hedge, not a required fix.

**Fix-generation agents**: 3 independent, walled-off, fresh agents (no
conversation context, no access to `ground_truth/`, `rule_test/` other than
the spec file, `REPORT.md`, or `methodology_notes.md` — same isolation
discipline as the original detection agents). Each given only the spec,
the confirmed-sites list, and read access to `repos/`. Per
[[feedback_isolated_adversarial_construction]]: this is exactly the
"spawn a blind agent" pattern — I did not hand-write the fixes myself and
grade my own construction.

**Scoring** (`score.py`): exact-match / semantically-equivalent / wrong,
against the answer key. A FLAG-FOR-HUMAN verdict on the one genuinely
ambiguous site (B8a) scores as a legitimate hedge, not a miss; anywhere
else it's an avoidable hedge; a SKIP anywhere is scored wrong outright
(every input site was already confirmed, so SKIP contradicts the premise
unless the agent found a real reason — none did).

**Mechanical verification** (`verify/verify.py`): apply every run's FIX
edits to a fresh scratch copy of the 5 repos, then, honestly scoped to
what's actually checkable in this environment (no `mcp` package installed,
no `boto3`/`starlette`/`uvicorn`/`dotenv`/`requests` installed either):
1. `ast.parse()` every touched file.
2. For every touched line that is itself an `import` statement, exec just
   that statement against a real, from-scratch MCP v2 stub package
   (`verify/mcp_v2_stub/`) and confirm the target name binds to a class.
   The stub has no `mcp.server.fastmcp` module at all — confirmed by
   negative control (a leftover v1 import raises `ModuleNotFoundError`
   against it; the v2 path resolves cleanly). Full end-to-end module
   execution (pulling in the repos' unrelated third-party deps) was not
   attempted and is not claimed — those packages aren't installed here.
3. `QAInsights_jmeter-mcp-server`'s real test suite (self-mocking, no
   external deps needed) run before and after the fix, comparing the exact
   failing-test-name set, not just a pass count. Baseline captured fresh
   in this session (not trusted from `b8b_verification.md`):
   `PYTHONPATH=. python3 -m unittest tests.test_jmeter_server -v` → 9 run,
   6 pass, 3 fail (`test_execute_jmeter_test_default`,
   `test_execute_jmeter_test_gui`, `test_execute_jmeter_test_non_gui` —
   pre-existing kwarg-count assertion mismatches, unrelated to the
   migration).
4. **Negative control**: a deliberately incomplete migration (B8a/B8d
   migrated, B8c left as `fastmcp_mod.FastMCP = FastMCP`) was run through
   the same harness and produced `ImportError: cannot import name
   'MCPServer' from 'mcp.server.mcpserver'` on the first line of
   `jmeter_server.py` — reproducing the exact failure
   `b8b_verification.md` documented. The harness discriminates a real
   break; it isn't just passing regardless of input.

## Results

| Run | Exact-match | Semantic-equiv | Hedge | Wrong | Parse OK | Import-boundary resolved | QAInsights suite matches baseline |
|---|---|---|---|---|---|---|---|
| 1 | 20/20 (100%) | 0 | 0 | 0 | 20/20 | 9/9 | Yes |
| 2 | 20/20 (100%) | 0 | 0 | 0 | 20/20 | 9/9 | Yes |
| 3 | 20/20 (100%) | 0 | 0 | 0 | 20/20 | 9/9 | Yes |

All 3 runs: 20/20 FIX verdicts, 0 FLAG-FOR-HUMAN, 0 SKIP. Every proposed
replacement line was byte-identical to the hand-derived answer key,
including the trap site (B8c) — all 3 independently rejected renaming the
right-hand side, each explaining (unprompted, since the reason field given
to them never mentioned this) that the local class at line 12 is a
distinct identifier the SDK's import resolution never inspects. Every FIX
edit parses, every mcp-related import resolves against the real v2 stub,
and the one repo with a runnable test suite produces an identical
pass/fail signature to the pre-migration baseline.

## Reading these numbers

**This result is clean in the same way the study's early "reinstated
spec" runs were clean — and that history says to distrust a first clean
number until it's stress-tested, not to report it as final.** Two things
make it a real result rather than a construction artifact this time:
(a) the confirmed-sites input withheld the answer (reason fields state only
*why*, never *what*), and (b) mechanical verification (parse + import
resolution + a real test-suite run against a negative-control-tested
harness) confirms the output actually works, not just that it string-matches
an answer key I wrote myself. But the sample is the smallest, easiest host
in the study by design (`targetB_small`'s own detection numbers were
already 100%/100%) and every fix here is one of two mechanical patterns
(rename an identifier on an import/construction line, or rename one
attribute access). Fix-generation hasn't yet been tested against anything
requiring judgment about surrounding code — a fix that has to reformat a
multi-line call, thread a change through multiple lines, or choose between
two structurally different but both-plausible edits. Section "what's
untested" below is not a checklist for later; it's the reason this number
alone doesn't establish the stage works.

## What's untested

- **Every site in this run is a single-line, single-token rename.** No
  site required touching more than one line, reformatting a multi-line
  call, or resolving a genuine two-way ambiguity in what the correct edit
  is. `targetB_diluted` and the entangled host both exist already and
  would raise the difficulty; neither has been run through fix-generation.
- **The FLAG-FOR-HUMAN path is unexercised.** 0 hedges across 60
  site-verdicts (3 runs × 20 sites) means the "flag instead of guess" rule
  fired zero times here. `b8b_verification.md`'s own side-finding (the
  B8a ambiguity) was available to hedge on and no run took it — worth
  knowing whether that's genuine confidence or under-hedging, which
  requires a host where the correct edit is truly split between two
  defensible answers, not just formally open.
- **Import-boundary checking is real but partial.** It confirms the
  specific `mcp`-related import in each touched file resolves against a
  correct v2 surface. It does not execute the rest of any file, so a fix
  that's locally correct but breaks something a few lines away (unlikely
  for this site shape, untested for anything less mechanical) wouldn't be
  caught by this harness as built.
- **Semantic-equivalent-but-different rate is 0% because nothing exercised
  it.** The category exists in `score.py` for cosmetic variation
  (quote-style, whitespace) that this run's site shapes didn't produce any
  of. Unconfirmed whether it's a useful bucket or a dead one until a host
  produces some.

Next: run fix-generation against `targetB_diluted` and/or the entangled
host, where detection's own numbers show real strain, before treating this
stage as validated at any scale.
