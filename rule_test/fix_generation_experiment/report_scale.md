# Fix-generation at scale: targetB_diluted + entangled host

Follow-up to `report.md` (targetB_small, 20/20 exact-match, 3 runs). This
run scales to the two harder hosts and adds a risk class detection never
had to measure: a fix can be locally correct for the detected line and
globally wrong for the file. 6 more blind, walled-off agent runs (3 per
host), same isolation discipline as before (no access to `ground_truth/`,
this study's own reports, or — new this round — the entangled host's own
`entanglement_experiment/report.md`, which states its GT sites and
reasoning directly).

## targetB_diluted — same 20 sites, no new failure mode

Same 20 sites as `targetB_small`, embedded under
`rule_test/scale_experiment/host/integrations/` (byte-identical source,
confirmed by diff before use) alongside 685 unrelated Django files. Same
answer key, reused directly (not re-transcribed) from `../score.py`.

| Run | Exact-match | Parse OK | Import-boundary resolved | QAInsights suite matches baseline |
|---|---|---|---|---|
| 1 | 20/20 | 20/20 | 9/9 | Yes |
| 2 | 20/20 | 20/20 | 9/9 | Yes |
| 3 | 20/20 | 20/20 | 9/9 | Yes |

Identical result to `targetB_small`. Dilution (more unrelated code, zero
structural interaction) didn't touch fix-generation any more than it
touched detection in the original study — consistent with this study's
established finding that dilution and entanglement are different regimes.

## Entangled host (OpsMesh) — where the new risk class actually lives

Built the answer key by hand from `rule_test/entanglement_experiment/host/`
source + `spec_9fact.md` (the same 9-fact spec that host's own detection
GT used), and — per this task's explicit instruction — **verified every
claim by applying it to a scratch copy and running the host's real pytest
suite, not by reading alone.** Fresh baseline this session (unmodified
host + a from-scratch v1 `mcp` stub, `pytest`/`pytest-asyncio`/`PyYAML`/
`click` installed for this): **16 passed, 0 failed.**

### 6 of 10 sites: one correct single-line answer, confirmed exact-match, 3/3 runs

E1/E2/E3 (`FastMCP`→`MCPServer`, import + base class + `Context` import),
E7 (`inputSchema`→`input_schema` field read), E8 (a `mock.patch()` dotted-
path string), E10 (a test fixture's keyword field name) — all 3 runs
produced byte-identical, correct replacements for all 6. Composed with a
hand-verified correct resolution of the other 4 sites (below) and run
against the real suite: **16 passed, 0 failed — identical to baseline**
(`evidence/composed_check_run1_plus_handverified_hard_sites.diff`). The
generated fixes aren't just textually right, they integrate.

### 4 of 10 sites: no correct single-line answer exists — this is the risk class the task asked to isolate

**E4/E5 (`context.py:13,20`, the removed `mcp.get_context()`
mechanism):** `current_context()` — built around the now-entirely-removed
`get_context()` — is imported and called from **4 separate tool files**
(`deployments.py` ×2, `runbooks.py`, `service_catalog.py`, `incidents.py`)
and monkeypatched in **5 tests** in `test_tools.py`. Verified two ways, not
asserted:
- **Naive fix** (swap only the import path, the locally-plausible edit a
  pattern-matcher would produce): applied to a scratch copy →
  `ImportError: cannot import name 'get_context' from 'mcp.server.mcpserver'`,
  killing `test_tools.py` at collection. `evidence/naive_fix.diff`.
- **Actual correct fix**: not a line edit. Requires deleting
  `current_context()`, adding `ctx: Context` as an injected parameter on 5
  handler functions across 4 files, and rewriting 5 tests to pass the
  context explicitly instead of monkeypatching a function that no longer
  exists. 6 files, ~15 lines, from 2 detected sites. Verified: 16/16 pass.
  `evidence/correct_fix.diff`.

**E6/E9 (`session_group.py:38` + its test assertion):** fact 5 says
`ClientSessionGroup.call_tool()` "lost its `args` parameter" without
saying what replaced it. Two structurally different, individually
self-consistent edits were each applied (with the test assertion updated
to match) and **both passed**: passing `arguments` as a keyword vs.
dropping it entirely. `evidence/site6_keyword_variant.diff`,
`evidence/site6_dropped_variant.diff`. **This is the sharper finding**:
the host's own test suite cannot tell these apart, because it tests the
wrapper against a `MagicMock`, not the real v2 `ClientSessionGroup` — the
mock accepts whatever shape it's called with. Mechanical verification
proves self-consistency here, never correctness against the real SDK.
E9's correct form is entirely contingent on which way E6 resolves; scoring
it independently doesn't make sense, which is why the two are paired.

### All 3 runs, scored 3 ways as requested

| Run | Exact-match (6 sites) | Locally-plausible-but-globally-wrong (4 sites) | Legitimate hedge (4 sites) |
|---|---|---|---|
| 1 | 6/6 | 0/4 | 4/4 |
| 2 | 6/6 | 0/4 | 4/4 |
| 3 | 6/6 | 0/4 | 4/4 |

**Zero locally-plausible-but-globally-wrong fixes were produced by the
actual agents, across all 3 runs.** Every one of the 4 hard sites was
correctly routed to FLAG-FOR-HUMAN, every time — 12/12. The risk class
itself is real and empirically confirmed (the naive-fix and both-variants-
pass demonstrations above prove it exists and would ship a bug if guessed)
but the agents tested here never fell into it; they recognized the
boundary of their own confidence instead of guessing. That's a
capability result, not a non-finding — a weaker or differently-prompted
generator could easily land in this category, and the scoring
infrastructure (`score.py`'s `NO_SINGLE_LINE_FIX` category) is now built
to catch it if one does.

## Does FLAG-FOR-HUMAN fire on the harder hosts? Yes — and only where it should

`report.md` (targetB_small) flagged this as unvalidated: 0 hedges across
60 site-verdicts, no evidence either way on calibration. This round settles
it in both directions:

- **targetB_diluted: 0/60 hedges** (20 sites × 3 runs) — consistent with
  targetB_small, dilution doesn't manufacture ambiguity that isn't there.
- **entangled, the 6 easy sites: 0/18 avoidable hedges** — the mechanism
  doesn't over-fire on sites that do have one confident correct answer,
  even on the hardest host tested.
- **entangled, the 4 hard sites: 12/12 legitimate hedges** — it fires
  every time there's a real reason to, on a host built by a separate,
  walled-off agent with no knowledge of this study, independently
  containing exactly this failure shape.

Across all 3 hosts and both fix-generation experiments: **138 single-line-
correct site-verdicts, 0 avoidable hedges, 0 wrong fixes; 12 genuinely
ambiguous site-verdicts, 12 legitimate hedges, 0 guesses.** The hedge path
is not unvalidated anymore — on the evidence gathered so far, it's
correctly calibrated in both directions on the one host built to contain
real ambiguity.

## What this does and doesn't establish

Establishes: fix-generation, like detection before it, is not equally
reliable everywhere — dilution doesn't touch it, entanglement does, and
the specific way it bites (a helper reached from multiple files, a
contract change the digest spec doesn't fully specify) is exactly the
shape this task predicted before any data existed. The FLAG-FOR-HUMAN path
works as designed on the one host built to test it.

Does not establish: that 0% locally-plausible-but-globally-wrong is a
stable rate. This is 3 runs, one prompt, one model, on one entangled host
built once by one other agent. The naive-fix demonstration proves the trap
is real and would be scored correctly if any run fell into it; it doesn't
prove no fix-generation agent, ever, under any prompting, would guess here.
Also unestablished: how a human reviewer actually resolves a
FLAG-FOR-HUMAN in practice (this measures whether the flag fires
correctly, not what happens downstream of it), and whether E6-shaped
ambiguity (a spec digest under-specifying a real API contract) is common
or rare outside this one constructed example.
