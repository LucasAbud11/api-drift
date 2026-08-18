# Reinstated real spec + explicit counting convention: results

9 repos, 3 fresh walled-off runs each (27 total), the recovered original
9-item migration guide verbatim, plus one new paragraph — the explicit
counting convention — added to the spec text the agents actually read (not
just the methodology notes). Raw output: `runs/*/run{1,2,3}.json`. Scoring:
`score_reinstated.py`, full output in `score_output.txt`.

## Headline result: precision holds at 100%, everywhere, on the real spec

| | run1 | run2 | run3 |
|---|---|---|---|
| Recall (34 GT sites) | 33/34 = 97.1% | 33/34 = 97.1% | 30/34 = 88.2% |
| Precision | 33/33 = **100%** | 33/33 = **100%** | 30/30 = **100%** |

**Zero false positives in any of the 27 runs**, across both targets, using
the real 9-item spec (not the 6-item digest) — the one with 11 camelCase
field renames, a decorator-vs-low-level-`Server` distinction, five separate
client-SDK changes, `McpError`→`MCPError`, and a `NoBackChannelError`
behavior note layered on top of the `FastMCP`/`Context` mechanism. That's
the answer to the question this run was built to settle: **the agent's
comprehension was never the bottleneck.** Given the real spec's full
density plus one explicit paragraph resolving the one ambiguity that
caused the original 17 false positives, precision doesn't just improve —
it's perfect, on every repo, every run, including all four Target A repos
that never even touch the ambiguity in question. The 55.3%/48.5% precision
story collapses into exactly what you predicted: "write a clearer spec,"
not "improve the agent."

## The recall miss: one repo, one site class, real variance

26 of 27 repo-runs hit 100% recall. Every miss, in every run, is confined
to **QAInsights**, and specifically to the 4-line test-mock cluster (GT
sites B8a–B8d, `tests/test_jmeter_server.py:11,12,21,22` — the `sys.modules`
stub that fakes the entire `mcp.server.fastmcp` module tree so the test can
run without the real SDK installed):

| run | missed | recall |
|---|---|---|
| 1 | line 12 only | 7/8 |
| 2 | line 12 only | 7/8 |
| 3 | lines 11, 12, 21, 22 (all four) | 4/8 |

This is real, same-input variance — same spec, same repo, same convention
paragraph, three independent cold runs, and the miss count goes 1 → 1 → 4.
You're right that this is the more interesting number here: a detector
whose recall on the same input swings between 87.5% and 50% isn't
something you'd trust to open a PR unattended, independent of whatever its
average looks like.

## Diagnosis: two different mechanisms, not one, and they point in opposite directions on your two hypotheses

Per your instruction, I did not touch the convention wording. I pulled
every rejection's own recorded reasoning verbatim and checked whether it
invokes the "downstream, resolves automatically" language from the
convention paragraph, or something else entirely. **It's not one
mechanism. Runs 1–2 and run 3 are doing different things.**

### Runs 1 and 2 (miss only line 12): does NOT cite the convention

Run 1's exact reasoning for excluding line 12 (`class FastMCP:`):

> "This is just a local Python class name used to build the mock; it can
> remain named FastMCP internally and still be assigned to a
> differently-named module attribute (e.g. `mcpserver_mod.MCPServer =
> FastMCP`), so this line's own text does not have to change to fix the
> migration."

Run 2, independently, same conclusion, same argument shape:

> "purely a local mock class name with no import-path significance; the
> mock could keep this identifier and just expose it under a renamed
> attribute (see line 21), so this line's own text is not strictly
> required to change — flagged here with low confidence rather than
> silently dropped."

Neither of these says "downstream of the import fix" or invokes automatic
repair. This is a **self-generated technical argument**, not an
application of the stated convention: the agent is reasoning correctly
about actual Python semantics — a class's own bound identifier (`class
FastMCP:`) genuinely does not need to match the name it gets exposed under
on the fake module (`fastmcp_mod.MCPServer = FastMCP` would work fine).
That's not wrong as a claim about what's *strictly necessary for the code
to run*. It disagrees with `ground_truth.md`'s own stated inclusion
criterion instead, which counts the line because it's a **literal
occurrence of the old class name in a construct standing in for the
renamed class** — a consistency standard, not a pure runtime-necessity
standard. Both runs even flag their own uncertainty ("low confidence,"
"flagged here... rather than silently dropped") — this is an agent
correctly identifying that it's making a judgment call on genuinely
underspecified territory, and landing on the wrong side of a convention
question the spec text never actually addresses: *what to do with a name
that's redefined/faked to impersonate the renamed symbol, as opposed to a
name that's imported and simply resolves once its import is fixed.*

### Run 3 (misses all four lines): explicitly cites downstream/automatic-repair language, over-applied

Run 3's reasoning for the same file is categorically different — and does
invoke the convention, incorrectly, on lines where nothing is actually
automatically repaired:

> Line 11 (`fastmcp_mod = types.ModuleType('mcp.server.fastmcp')`): "...
> Its own text isn't broken by the real SDK's v1→v2 change; it only
> becomes stale if jmeter_server.py's import is separately fixed, which is
> **a downstream consequence, not a migration-broken site itself**."

> Line 21 (`fastmcp_mod.FastMCP = FastMCP`): "Part of the same
> self-contained sys.modules stub; functions correctly regardless of real
> SDK version since it's never reached by real imports."

> Line 22 (`sys.modules['mcp.server.fastmcp'] = fastmcp_mod`): "...this
> continues to satisfy jmeter_server.py's **current (unfixed)** import
> regardless of what the real installed mcp package version is."

This is a materially different — and more damaging — error. The agent
reasons that because the stub currently mirrors the *unfixed* production
import, the stub isn't "broken" yet; fixing it is framed as a knock-on
effect of fixing `main.py`/`jmeter_server.py`'s import elsewhere, exactly
the "downstream, resolves automatically" shape the convention describes
for `Context`. But it doesn't resolve automatically here — nothing about
fixing the production import line changes what string literal is sitting
inside the test file. All four of these lines require their own
independent text edit no matter what order you do the work in. Run 3's
agent conflated "this file's brokenness is *triggered by* fixing something
else" with "this file's brokenness is *repaired by* fixing something else"
— the second is the convention's actual claim, the first is not, and nothing
in the stated convention marks that distinction for a case where a name is
**redefined to impersonate** the moved symbol (as opposed to merely
**referencing** it).

### Answer to your either/or

Both of your hypotheses are correct, for different runs, on different
sites:

- **Run 3, all four lines**: your hypothesis 1 — the convention wording
  *is* over-broad in exactly the way you described, and it's costly here:
  it wiped out 4 of 8 GT sites in one run by misclassifying an entire
  independent-edit test fixture as "downstream." The fix you named —
  an explicit carve-out for names that are **redefined or faked** rather
  than **imported and referenced** — targets this mechanism directly.
- **Runs 1–2, line 12 only**: your hypothesis 2, but not quite "attention
  dilution." It's not that the site went unnoticed in a denser spec — both
  runs explicitly considered and reasoned about line 12, flagged their own
  uncertainty, and made a real judgment call that happens to disagree with
  `ground_truth.md`'s inclusion philosophy. This is a **ground-truth
  definitional gap**, not a convention-wording bug: "is a literal
  occurrence of the old name in a stand-in construct a site, even when
  it's not technically required to change for the code to run?" The
  convention as written doesn't answer that question one way or the other,
  and can't be blamed for an agent answering it differently than
  `ground_truth.md` did.

A convention fix aimed only at run 3's mechanism (redefined/faked names
carve-out) would likely raise run 3 back to 8/8 without touching runs 1–2
at all, since those runs never invoked the downstream-repair language in
the first place — the miss would persist. That's a genuinely separate
decision, and it's the reason I didn't touch the wording: fixing one
doesn't fix the other, and you may want different answers for each (e.g.
accept the runs 1–2 disagreement as reasonable and only patch the run-3
mechanism, or decide `ground_truth.md`'s consistency standard should be
loosened to match the stricter runtime-necessity reading these agents
independently converged on).

## Nothing else moved

- All 4 Target A repos, all 3 runs: 100%/100%, no misses, no false
  positives — the counting convention correctly had zero effect where
  there's no analogous mechanism.
- tonyzorin, securityfortech, m0xai, danilop: 100%/100%, all 3 runs each.
  m0xai (14 `ctx: Context` sites) and danilop (their `Context`/`ctx.info`/
  `ctx.error` sites) — the exact repos that produced the original 17 false
  positives — are clean across all 9 combined runs with the real spec.

## 2026-08-18 addendum: the runs 1–2 "miss" above was ground truth being wrong

The "Runs 1 and 2 (miss only line 12): does NOT cite the convention"
section above was superseded, not just annotated. Runs 1–2's own
argument — the stub's exposed attribute name is what has to match, not
the `class FastMCP:` statement's own bound identifier — was verified
empirically (real migration + test run + negative control; see
`b8b_verification.md`) and found correct. `ground_truth.md` was wrong,
not the agent. Corrected GT: runs 1–2 are **8/8 (100%) recall**, not
7/8. Only run 3's 4/7 miss (the over-applied-convention mechanism,
unaffected by this correction since none of its four lines was B8b)
survives. A three-bucket PROPOSE/FLAG-UNCERTAIN/REJECT reclassification
of all 27 runs against the corrected GT found all 3 remaining misses
landed in a confident REJECT, none in FLAG-UNCERTAIN — full results in
`results.md`'s revision 5 update and `score_output_three_bucket.txt`.
