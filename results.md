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

**2026-08-18 update (revision 8) — blind vocabulary experiment: the
composition result was not an artifact of insider knowledge. Zero
ground-truth sites are structurally invisible to a vocabulary derived
blind from the public guide text, at either target or either scale — but
the blind vocabulary is 5x larger for Target B, and that volume is what
finally exposed a real operational failure mode this study hadn't seen
before.** The prior composition experiment's grep vocabulary was hand-
built with full knowledge of ground truth (including a bare `Context`
term added *because* the decoy was already known) — not the production
condition. Fix: spawned two fresh agents, each given only the same
verbatim "official migration guide" facts block this study has used
throughout (no counting convention, no task framing, no repo access, no
tool use — pure text reasoning), asked to derive a coverage-tuned grep
vocabulary from that document alone. Ran the full composition pipeline
(grep candidates -> agent adjudication with the two approved mandatory
rules) using each blind vocabulary, both targets, both scales (small =
the repos alone; diluted = embedded in the same 675+-file host, plus a
newly-built equivalent diluted host for Target A), 3 runs each — 12 runs
total, all persisted and validated through the same hardened validator.

Result: **candidate-set recall (grep alone, before any adjudication) is
100% for both targets at both scales** — every one of the 33 total GT
sites (13 Target A + 20 Target B) is in the blind candidate list. End-to-
end recall matched (100%) in 3 of 4 scale/target combinations; Target B
small hit 98.3% (59/60) only because one run flagged a true site as
uncertain instead of proposing it outright — still surfaced, not lost
(100% surfaced rate everywhere, every run). **The honest ceiling this
study set out to measure is zero sites, in this study** — not a
foregone conclusion; it held because Target A's guide is fully
namespace-qualified (`openai.ChatCompletion`, etc. — nothing to derive
that isn't already scoped) and Target B's guide, while it does contain
several bare, unqualified terms (`extra=`, `data=`, `cursor=`, `.error()`)
that any faithful reading turns into broad, over-matching patterns, still
never *loses* a real site to that broadness, only inflates the candidate
list around it (587 vs. 118 candidates small-scale, 1121 vs. 214
diluted — a 5x cost, not a coverage loss).

**That 1121-candidate volume — the first time this study actually landed
in the range flagged as untested — did not reproduce a recall ceiling,
but it did surface a new, previously-unseen failure mode: 2 of 3 Target B
diluted runs failed outright before completion** (one hard server error
mid-response, one silent truncation at 569/1121 with no continuation),
and the run that did complete on its first non-retried attempt dropped
the `snippet` field from all 1121 entries as a side effect of an internal
compact-format workaround — caught by the hardened validator, repaired
by backfilling from the independently-generated candidate list (a
mechanical fact, not agent judgment), not silently passed through. The
two failed runs were re-run from scratch, never patched. **The
adjudication-volume ceiling this study was built to find is not a
recall ceiling — every run that finished was accurate — it's a
completion-reliability ceiling**, one a production pipeline would need
to design around (batching, incremental persistence, retries) before
recall itself becomes the limiting factor. Full vocabulary diff, per-
run breakdown, and failure-mode detail: `rule_test/
blind_vocab_experiment/report.md`.

**2026-08-18 update (revision 6) — primary scale experiment: precision
holds at 100% under dilution, recall drops from ~97-100% to a flat 85.0%,
and the prospective FLAG-UNCERTAIN bucket was never used. This tests
search-space dilution only, NOT entanglement — see the framing caveat
below before reading the numbers as "works at scale."** Two
prerequisites landed first, both structural rather than promised: (1)
`rule_test/scale_experiment/validate_run.py` hard-fails scoring if any
run file is missing the `proposed_sites`/`flag_uncertain`/
`considered_and_rejected` keys or has a blank required field — this
exists because reconstruction-from-memory silently corrupted persisted
run data three separate times earlier in this study (see revision 5 and
commit `b643db3`); (2) `detector_prompt_v2.md` gives the detector the
PROPOSE/FLAG-UNCERTAIN/REJECT contract prospectively, before it searches,
with FLAG-UNCERTAIN defined as the correct bucket when the spec is silent
or ambiguous, replacing the earlier retrospective hedge-language scan
that had almost nothing to score.

The experiment: the same 5 ground-truthed Target B repos (20 corrected
sites) embedded under `integrations/` inside a 675-file, 109,231-LOC host
built from a real, unmodified, unrelated subset of Django's own source —
not fabricated, not adversarially constructed, and containing one
genuine incidental decoy the detector didn't need to be warned about:
`django/template/context.py` defines its own real `class Context`, no
relationship to the MCP SDK. 3 independent walled-off runs against the
full host.

**Precision: 100%, unanimous, zero false positives across all 3 runs**
(51/51) — the decoy `Context` collision never produced one. Diluting the
search space 20-30x over the standalone-repo experiment did not induce
any false positives. **Recall: a flat 85.0% (17/20) in all 3 runs** — down
from ~97-100% in the small-repo `spec_reinstated` experiment. Every miss,
every run, is the identical 3-line cluster:
`QAInsights_jmeter-mcp-server/tests/test_jmeter_server.py:11,21,22`, the
`sys.modules` stub — the same site cluster responsible for all prior
recall variance in this study. What changed under dilution: the miss went
from "usually right, sometimes badly wrong" (1/1/4 misses across 3 runs
on the standalone repo) to "reliably wrong" (3/3/3 misses, all 3 runs,
under dilution) — a detector that fails the same way every time is
arguably worse for trust than a noisy one, since re-running doesn't catch
it. **FLAG-UNCERTAIN was used zero times across all 60 run-site
combinations**, despite being explicitly instructed as the correct bucket
for exactly this kind of ambiguity. Where the detector was wrong, it was
wrong confidently (run1 gave a full stated reason: "the test... never
touches the real installed SDK, so the v1->v2 change... cannot affect
this line's behavior" — the same over-applied "self-contained, therefore
unaffected" reasoning diagnosed as run3's failure mode in revision 4) or
wrong silently (run2/run3 never mentioned 2 of the 3 missed lines in
either bucket at all — an "invisible" miss, 5 of 9 total misses across
the 3 runs). A prospective three-bucket contract offered in the prompt
was not, on its own, sufficient to make the detector hedge on the case
that most needed it; task density appears to push this exact cluster
toward confident dismissal rather than toward self-flagged uncertainty.

**What this does and doesn't show, explicitly:** this is a
**dilution** test — more unrelated haystack, same needles, haystack and
needles causally disconnected; the host doesn't import, subclass, wrap,
or otherwise interact with `mcp` anywhere. It is NOT an **entanglement**
test — a real large monorepo of this size would typically weave the
target library's abstractions through the host's own code (a subclassed
`Context`, SDK objects passed through host DI layers, a re-exported
`FastMCP` alias), which is a structural kind of ambiguity this experiment
never applies pressure to. The one decoy here is a name collision, the
easy kind (one grep on the import path resolves it), not a structural
collision. **The clean 100% precision above must not be read as "this
detector works at scale"** — it shows precision survives volume alone;
whether it survives entanglement is a different, harder, and still-open
question. Full writeup, per-run breakdown, and the exact host
reproduction script (the 16MB host itself isn't committed, only
`build_host.sh`, pinned to Django commit `84d09a5`):
`rule_test/scale_experiment/report.md`.

**2026-08-18 update (revision 7) — two diagnostics on the recall drop,
then the composition experiment it implied, which eliminated the
coverage ceiling entirely.** Before touching entanglement, two questions
about revision 6's 85%-recall dilution result needed answers.

*Diagnostic 1: is the 9-miss recurrence judgment or search?* Pulled the
actual tool-call history (not just final answers) from all 3 dilution
subagent transcripts. The file was read in full in all 3 runs, so none
of the 9 misses is a retrieval failure. They split into two mechanisms:
4/9 are judgment failures (reached, individually reasoned about,
explicitly wrong — the same "self-contained stub, therefore unaffected"
argument already diagnosed at small scale); 5/9 are a third thing with
no small-scale analogue at all — content read into context but never
converted into a verdict in any bucket, no reasoning trace anywhere.
Full evidence: `rule_test/scale_experiment/cluster_diagnosis.md`.

*Diagnostic 2: redesign FLAG-UNCERTAIN around something observable.*
Approved: name-impersonation (site is part of building a `sys.modules`/
`types.ModuleType` stand-in for an SDK path — mechanical, anchored to
concrete syntax) as primary, test/mock-path floor as a mandatory backup,
dropped the "matches a worked spec example" option as reintroducing the
same self-assessment problem it was meant to fix.

*The composition experiment diagnostic 1 implied: grep for recall, agent
for judgment only.* Grep produces a coverage-tuned candidate set
(precision irrelevant); the agent adjudicates every candidate into the
three buckets using the two approved mandatory rules, searching for
nothing. Run 3x at small scale (118 candidates) and 3x on the diluted
host (214 candidates, 96 of them Django noise). Result:
**100% recall, 100% precision, zero closed-world violations, in all 6
runs, at both scales, identically.** The exact 3-site cluster that was
missed 9 times under search-based dilution was confidently and correctly
proposed in all 6 adjudication-only runs — the mandatory rules didn't
even need to divert it to FLAG-UNCERTAIN. Separating search from
judgment removed the coupling that caused mechanism B: the same
reasoning pass being asked to both find every relevant line in a large
host and individually justify a verdict on each one. Not established:
an adjudication-volume ceiling (214 candidates was comfortably handled;
where a much larger candidate list would break down is untested), or
anything about entanglement, or that this study's known-in-advance grep
vocabulary generalizes to a real migration where nobody has already
enumerated the exact breaking terms. Full report: `rule_test/
composition_experiment/report.md`.

**2026-08-18 update (revision 9) — deterministic pre-filter cuts the
1121-candidate host to 111 with zero GT loss, and that reduction alone
fixed the reliability problem: 5/5 clean runs vs. 2/3 failures at full
volume. Idempotent chunked resume built and verified regardless.** This
follows on revision 8 (blind vocabulary), which is the block above
headed "revision 8" earlier in this file — it landed out of
chronological order in the text due to an edit-anchor mistake; the
content is correct, only its position in this log is off.

*Candidate-set reduction.* Three mechanical, LLM-free filter stages
between grep and the agent: (A) drop candidates in files that never
actually reference the target package (module-qualified check — a
real `import mcp`/`mcp.server.`/`mcp.client.` reference or the
sys.modules-registration form the QAInsights test stub uses — not a
bare substring, which the first version wrongly used and which passes
trivially for any file merely living in a repo named `youtrack_mcp`);
(B) drop matches entirely inside a comment/docstring/unrelated string
literal, keeping a narrow whitelist for the two load-bearing string
forms this study's own spec cares about (`types.ModuleType(...)`
arguments, `sys.modules[...]` keys); (C) collapse byte-identical
repeated lines within one file into one adjudication, expanded back to
every original line before scoring. **Constraint: zero GT loss,
absolute** — verified after every single stage, both targets, both
scales. The first version of stage B failed this constraint outright
(dropped 7 real GT sites by treating "any string exists on this line"
as grounds to drop the whole line, e.g. `mcp = FastMCP("jmeter")` has a
real code match *and* an unrelated string argument) and was fixed, not
shipped anyway, before being trusted. Result: Target A 13->9 (30.8%),
Target B small 587->111 (81.1%), **Target B diluted 1121->111
(90.1%)** — the exact host that was unreliable at full volume.

*Batch reliability.* Ran the diluted Target B pipeline 5 independent
times on the reduced 111-candidate set: **5/5 completed cleanly on
first attempt**, zero retries, 100% surfaced rate in every run (one
run's single recall dip was a site correctly flagged uncertain, not
lost). Direct comparison, same host, same spec, same rules, same
model, only candidate count changed: 1121 candidates -> 2/3 failures;
111 candidates -> 5/5 clean. Reduction, not chunking, is what fixed
reliability here. Built the idempotent chunked pipeline anyway, since
5/5 at 111 doesn't guarantee 111 is what a different target's
vocabulary will always reduce to: `pipeline.py` treats each ~40-
candidate chunk as an independent, atomically-persisted unit; a chunk
only counts done if its output validates through the same hardened
validator AND its adjudicated (file, line) set exactly matches what it
was given; resuming a run calls `pending_chunks()`, which returns only
what's not done, so a partial failure costs one chunk, not the run.
Verified against real data, not a synthetic example: replayed one of
the 5 actual completed runs as 3 chunks, simulated the middle chunk
failing to persist (the same failure shape seen twice earlier in this
study), confirmed only that chunk was reported pending, resumed, and
confirmed the merged result exactly reproduces the original single-shot
run's (file, line, bucket) set. Full detail: `rule_test/
prefilter_experiment/report.md` (reduction) and `rule_test/
prefilter_experiment/report_reliability.md` (batch reliability +
pipeline).
