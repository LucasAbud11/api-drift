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

**2026-08-18 update (revision 1, superseded below) — this was an untested
prediction; it was tested by reconstructing "agent output" as ground truth
∪ the 17 documented false positives, then applying the rule to that
reconstruction. Reaching 100% precision was therefore guaranteed by
construction, not measured — flagged as circular and redone.**

**2026-08-18 update (revision 2) — 9 fresh, walled-off detection agents
were actually re-run from scratch (raw output persisted to
`rule_test/agent_runs/*.json` before scoring). See `rule_test/rule_test.md`
for full detail. The real run does not reproduce the 55.3% figure at all:
zero false positives on either target, 100%/100% recall and precision
across the board — every agent independently rejected all 17 `ctx: Context`
sites with correct reasoning.** This can't cleanly be attributed to "the
rule works" vs. "the fresh migration spec already stated the fact that
made the mistake possible" (item 3 of the reconstructed spec says outright
that `Context` keeps its name) — the original spec text was never
persisted, so which explanation is right can't be settled here. Either way,
**the 48.5%→100% figure this recommendation was built on has not
reproduced under independent re-run and should not be cited as a stable
property of the agent.** Grep's side is unaffected by this correction
(14.9%→17.1% under the rule, deterministic, confirmed by re-running the
grep script twice) and remains dominated by decorator overmatch and
keyword collisions the rule has no leverage on. Ship the rule anyway — it
is provably safe (zero recall cost, both the circular reconstruction and
the real run) and costs nothing when there's nothing to filter — but stop
citing the specific percentage as justification.

**2026-08-18 update (revision 3, resolved) — the original session's
transcript was located on disk and read directly; see
`rule_test/ablation_and_root_cause.md` and
`rule_test/original_session_recovered/`.** "Spec text was never
persisted" (above) is now wrong — it was found. The recovered original
Target B spec is 9 dense items (vs. this session's 6-item simplification)
and its item 1 explicitly states that a *type annotation referencing
`FastMCP`* is broken while staying silent on whether a downstream
*`Context`* reference counts the same way — an asymmetry my reconstruction
accidentally resolved (in both ablation conditions) by never dwelling on
import-failure mechanics the way the original does. The original agents'
own recorded reasoning confirms this directly: not confusion about
whether `Context` was renamed, but a defensible-but-wrong argument that
"the import fails, so every line depending on it is broken too" — exactly
the "depends on" mechanism this file described from the start, now
confirmed in the agents' own words rather than inferred. A 20-run ablation
on the two repos that can actually show the effect (m0xai, danilop; the
other three have zero `ctx: Context` sites and can't) produced zero
variance and zero false positives in both conditions — the sentence about
`Context`'s name was never the operative variable. Grep's real, recovered
baseline command was also re-run verbatim: 21.0% precision (vs. the
reported 21.9%, matching almost exactly) confirming the earlier
reconstruction was directionally right, and its vocabulary never searches
for bare `Context` at all — the rule removes zero candidates from the
real grep baseline, not just "barely helps." This session's own
simplified spec, not the rule or the agent, is why the benchmark now
reads as saturated; see `ablation_and_root_cause.md` for the proposed
fix (reinstate the real 9-item spec, then scale repo/fan-out size).

**2026-08-18 update (revision 4, decisive) — the original 55.3%/48.5%
precision figures were a convention-disagreement artifact, not a
comprehension failure, and this is now a corrected finding, not a
hypothesis. Full report: `rule_test/spec_reinstated/report.md`.** Re-ran
all 9 repos, 3 fresh walled-off runs each (27 total), on the real
recovered 9-item spec — not the 6-item digest — with one addition: an
explicit counting convention paragraph, stated in the spec text the agents
actually read (not just in `methodology_notes.md`), spelling out that a
line only counts as a site if fixing an earlier line does not repair it
automatically. Result: **zero false positives across all 27 runs, on
both targets** — including m0xai and danilop, the exact two repos that
produced the original 17 false positives, and including the full weight
of the real spec's extra decoy surface (`McpError`, the low-level `Server`
class, `NoBackChannelError`, five separate client-SDK changes) that the
6-item digest never exposed agents to at all. Precision is not "improved
by the rule" — it is 100%, unconditionally, once the one governing
sentence the original spec omitted is stated once. **The original
finding that this was "the agent's one real, systematic mistake" was
wrong as originally framed.** It was a spec-completeness gap: the guide
told agents that a `FastMCP` type annotation is broken but never said
whether a `Context` annotation counts the same way, and the agents'
own recorded reasoning shows they reasoned toward the wrong answer on a
genuinely unstated question, not that they failed to understand a stated
one. The clearest piece of evidence for this, preserved verbatim in
`rule_test/original_session_recovered/danilop_original_result.txt`: the
original danilop agent, explaining why it counted a `ctx: Context`
annotation as its own site — *"Since Python evaluates parameter
annotations at function-definition time... and the import already fails,
this name would be unresolved. Flagging as affected via the broken import
chain, **though the root cause is line 6**."* That is not confusion. The
agent identified the actual root cause correctly, in the same sentence,
and made a defensible, wrong-by-this-study's-convention judgment call
about whether to count the downstream effect separately — precisely the
kind of ambiguity a stated convention resolves and an unstated one does
not.

**One real, separate finding survived this correction and is unresolved:
recall variance on test-mock fixture sites.** 26 of 27 repo-runs hit
100% recall; every miss across all three runs is confined to one repo
(QAInsights) and one site cluster — the `sys.modules` stub in
`tests/test_jmeter_server.py` that fakes the SDK's module tree. Miss
count: 1, 1, 4 across the three runs — real same-input variance, not a
tail. Reasoning-level diagnosis (not yet acted on) found two distinct
mechanisms, not one: two of the three runs made a defensible,
low-confidence technical argument that disagrees with this repo's own
inclusion philosophy (a stub class's own name doesn't have to match its
exposed attribute name); the third run explicitly misapplied the new
counting convention itself, reasoning that a test fixture requiring an
independent edit was merely a "downstream consequence" of fixing the
production import — the same class of misreasoning the convention
exists to prevent, just triggered on a case (a redefined/faked name) the
stated wording doesn't carve out. See `rule_test/spec_reinstated/
report.md` for the full quotes and diagnosis. Convention wording was
deliberately left unchanged pending a decision on which failure mode to
target.

**2026-08-18 update (revision 5) — the "low-confidence" recall miss above
was ground truth being wrong, not the agent. Corrected; also formalized
a third output bucket to check whether misses are silent or self-flagged.**
Two follow-ups on revision 4's unresolved recall-variance finding, run
before any convention-wording change or scale work, per instruction to
verify ground truth empirically before trusting it further.

*B8b was not a required edit.* `ground_truth.md` counted
`tests/test_jmeter_server.py:12` (`class FastMCP:`, the mock's own local
class statement) as a required site. Runs 1–2's argument — that a
`sys.modules` stub's exposed attribute name is what has to match, not the
class statement's own bound identifier — was tested empirically, not
argued: performed the real migration on a scratch copy of the repo,
changed only the import path, the constructor call, and the two lines
that set/register the stub's exposed attribute name, left the `class
FastMCP:` statement itself untouched, and ran the test suite. Identical
pass/fail result to the unmigrated baseline (6/9, matching pre-existing
unrelated failures). A negative control — reverting the actually
load-bearing line (the exposed attribute name) instead — broke the
import as expected, confirming the test harness does discriminate real
breaks from non-breaks. Ground truth was wrong; corrected. Target B's
GT total drops from 21 sites to **20** (`ground_truth.md`, full
before/after and mechanism explanation in
`rule_test/spec_reinstated/b8b_verification.md`). Re-scoring the 27 runs
against the corrected GT moves QAInsights run1 and run2 from 7/8 (87.5%)
to **8/8 (100%) recall** — they were never wrong. Only run3's 4/7
(57.1%) miss survives, unchanged, since none of its four excluded lines
was B8b.

*Three-bucket reclassification (PROPOSE / FLAG-UNCERTAIN / REJECT),
applied to all 27 runs.* Every `considered_and_rejected` entry across
all 27 runs (649 entries) was scanned for explicit hedge language
("low confidence," "flagged here... rather than silently dropped,"
"not strictly required," etc.) to separate sites the agent correctly
flagged its own uncertainty about from sites it silently, confidently
excluded. Method and script: `rule_test/spec_reinstated/
score_three_bucket.py`; full output in `score_output_three_bucket.txt`.
Against the corrected GT: **precision on proposed-only is 96/96 = 100%**,
**recall on proposed-only is 96/99 = 97.0%**. All 3 remaining GT misses
are QAInsights run3's lines 11/21/22 (the run-3-only over-applied-
convention mechanism from revision 4) — **zero of the 3 landed in
FLAG-UNCERTAIN; all 3 were silently missed via a confident REJECT
reason**, and zero were "invisible" (i.e. the detector always discussed
every eventual miss and gave a stated reason for excluding it — it never
simply failed to notice a site). Only one entry in the entire 649-entry
corpus used hedge language at all: QAInsights run2's rejection of line
12 — the exact B8b site just removed from ground truth. So the single
clearest self-flagged-uncertainty signal this detector produced across
27 runs was about a site that, empirically, turned out not to need
editing — a data point of one, but suggestive that when this detector's
hedge language does fire, it may be tracking something real, while its
confident-REJECT language (used for the run-3 misses) currently carries
no such signal. **Limitation, stated plainly rather than glossed over:**
this is a purely retrospective free-text scan against a detector that
was only ever given a binary propose/reject contract — it was never
asked to self-report confidence, so a near-total absence of hedge
language mostly reflects that no bucket for it existed, not that the
detector has no calibration. A prospective run with an actual
three-bucket contract in the prompt is the real test of whether
self-flagged uncertainty is a usable signal; this analysis only
establishes that it's rare and, in its one occurrence, was right.
Convention wording and the scale experiment remain on hold pending both
of these landing.
