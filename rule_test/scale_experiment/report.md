# Scale experiment: search-space dilution, not entanglement

**Read this framing before the numbers below, not after — a good precision
result here is not evidence this detector "works at scale."** This
experiment tests exactly one variable: what happens to precision/recall
when the same 20 ground-truthed sites are buried inside a much larger
codebase that has NOTHING TO DO with the MCP SDK. The host
(`host/django/`) is a real, unrelated, un-mangled subset of Django's own
source — it does not import, subclass, wrap, monkey-patch, or otherwise
interact with `mcp` in any way. That is a **dilution** test: more
haystack, same needles, needles and haystack causally disconnected.

It is explicitly NOT an **entanglement** test. A real production monorepo
of this size would typically have the target library's abstractions woven
through the host's own code — a wrapper class that subclasses `Context`,
a DI container that passes SDK objects through three layers of
indirection, a re-export of `FastMCP` under a local alias, a base class
that both the host and the integration inherit from. None of that exists
here. The one decoy this host does contain —
`django/template/context.py:135`, a genuine `class Context(BaseContext)`
with zero relationship to the MCP SDK — is a **name collision**, which is
the easy kind of decoy (resolved by checking the import path, one grep
away). It is not a **structural** collision (shared base class, wrapped
object, re-exported symbol), which would be the actual test of whether
detection degrades when the target library's own shapes are entangled
with the host's. This experiment says nothing about that harder case.
Do not generalize the results below past what was actually varied.

## Setup

- **Host**: `host/` — 675 `.py` files, 109,231 LOC. `host/django/` (524
  files, 72,724 LOC) is a curated, unmodified subset of Django 5.1.16
  (commit `84d09a5`, see `build_host.sh` for the exact reproduction
  script — the host itself isn't committed to this repo, only the script
  that rebuilds it byte-for-byte). `host/integrations/` embeds the same 5
  Target B repos used throughout this study, each at its original
  relative path (e.g. `integrations/QAInsights_jmeter-mcp-server/main.py`),
  so every ground-truth line number is unchanged from `ground_truth.md`.
- **Ground truth**: the same 20 corrected Target B sites (B8b already
  removed — see `results.md` revision 5), rewritten with the
  `integrations/<repo>/` path prefix in `score_scale.py`.
- **Detector prompt**: `detector_prompt_v2.md` — same breaking-change
  facts and counting convention as `spec_reinstated/target_b_spec.md`
  (untouched, per the standing hold on convention wording), plus a new
  prospective PROPOSE / FLAG-UNCERTAIN / REJECT output contract and a
  task framing that tells the detector the host is large and mostly
  unrelated, without saying where the 5 integrations live.
- **Runs**: 3 independent, walled-off, cold-start agents, each given the
  full host path and nothing else (no ground truth, no knowledge of each
  other). Raw output persisted verbatim to `runs/run{1,2,3}.json` before
  any scoring, then validated through `validate_run.py` (hard-fail
  validator — see below) before `score_scale.py` computed anything.

## Results

| run | proposed | TP | FP | GT | recall | precision | flag_uncertain used |
|---|---|---|---|---|---|---|---|
| 1 | 17 | 17 | 0 | 20 | 85.0% | **100%** | 0 |
| 2 | 17 | 17 | 0 | 20 | 85.0% | **100%** | 0 |
| 3 | 17 | 17 | 0 | 20 | 85.0% | **100%** | 0 |
| **aggregate** | 51 | 51 | 0 | 60 | **85.0%** | **100%** | **0 / 60** |

**Precision: 100%, unanimous, zero false positives across all 3 runs** —
including on the one incidental `Context` name collision. Diluting the
search space 20-30x (109k LOC vs. the ~5-30k LOC of the five repos alone)
did not induce a single false positive in any run. That is a real,
positive result, and it is also exactly the limited claim the framing
above says it is: this host doesn't give the detector any structural
reason to get confused, only a volume reason.

**Recall dropped from ~97-100% (small-repo `spec_reinstated` experiment)
to a flat 85.0% (17/20) — identically, in all 3 runs.** Every single miss,
in every run, is the same 3-line cluster: `QAInsights_jmeter-mcp-server/
tests/test_jmeter_server.py:11,21,22` — the `sys.modules` stub that fakes
the `mcp.server.fastmcp` module tree. This is the same site cluster that
was the sole source of recall variance in the small-repo experiment
(where the miss count varied 1/1/4 across three runs on the standalone
repo). Two things changed:

1. **The miss got bigger.** In the small-repo experiment (post-B8b-
   correction), 2 of 3 runs hit 8/8 on this file and only 1 of 3 missed
   the full 3-line cluster. Here, diluted into the large host, all 3 of 3
   runs missed the full cluster. Recall on this exact file went from
   "usually right, sometimes badly wrong" to "reliably wrong."
2. **The miss got more silent.** Run1 explicitly discussed and rejected
   all three lines (11, 21, 22) with a stated, confident reason. Run2 and
   run3 didn't even mention lines 11 and 21 in either bucket — they went
   from "considered and rejected" to simply never coming up, which
   `score_scale.py` reports separately as "invisible" (5 of the 9 total
   misses across the 3 runs) rather than folding it into the REJECT count.

**FLAG-UNCERTAIN was used zero times, across all 3 runs, on all 60
run-repo-site combinations, despite being explicitly instructed as the
correct bucket for exactly this kind of ambiguity.** This is the direct,
prospective answer to what the retrospective three-bucket analysis in
`spec_reinstated/` couldn't settle: giving the detector the bucket ahead
of time did not make it use the bucket. Where the detector was wrong here,
it was wrong *confidently* (run1's stated reasons) or wrong *silently*
(run2/run3's unmentioned lines) — never wrong *while flagging its own
uncertainty*. The mechanism is legible in run1's stated reasoning: "Test
stubs the entire mcp module tree in sys.modules before import; never
touches the real installed SDK, so the v1->v2 change to the real package
cannot affect this line's behavior" — this is confident, well-formed, and
wrong, applying the same "self-contained, therefore unaffected" argument
across the whole 4-line stub, including lines that manipulate the exact
`sys.modules` key the production import will look up post-migration.
That is the identical over-applied-convention failure mode diagnosed in
`spec_reinstated/report.md`'s run-3 analysis — except here it fired in
3 of 3 runs instead of 1 of 3, and never once triggered the hedge
language the detector clearly has access to (see
`spec_reinstated/score_output_three_bucket.txt` for the one retrospective
instance of it firing on this exact site cluster in the earlier
experiment).

## What this does and doesn't show

**Shows:** at this scale of dilution (20-30x more unrelated code, no
structural entanglement), precision holds perfectly and recall degrades
in a way that's concentrated, reproducible, and NOT accompanied by any
increase in self-reported uncertainty — the detector doesn't get more
cautious as the task gets harder, it gets more confidently wrong on the
same known-hard cluster. A three-bucket contract offered in the prompt
is not sufficient on its own to make a detector hedge on the cases that
actually warrant it; something about task density (109k LOC to reason
about, 675 files to triage) appears to push the same site cluster from
"defensible disagreement, sometimes flagged as low-confidence" toward
"pattern-matched and dismissed," not toward "flagged as uncertain."

**Does not show:** anything about entanglement, i.e. whether recall or
precision degrades when the host's own code actually shares structure
with the target library (subclassing, wrapping, re-exporting,
dependency-injecting SDK objects through host abstractions). That is a
different and likely harder experiment, deliberately not run here. A
detector that is bulletproof against name-collision decoys in disjoint
code is not thereby shown to be bulletproof against a wrapper class that
generates the same shape of ambiguity the original 55.3%/48.5% precision
figures were about (`results.md` revisions 4-5) — this experiment simply
never puts that pressure on it.

## Hardened pipeline note

Every number above was produced by `score_scale.py`, which refuses to run
until all 3 `runs/run*.json` pass `validate_run.py`'s hard-fail
validation: all three top-level buckets (`proposed_sites`,
`flag_uncertain`, `considered_and_rejected`) must be present as keys
(missing is fatal, not defaulted), and every item in every bucket must
have non-blank `file`/`line`/`reason` (plus `pattern`/`snippet` for
`proposed_sites`). This exists because reconstruction-from-memory
corrupted run data three times earlier in this study (`results.md`
revision 5, commit `b643db3`) — see `validate_run.py`'s docstring and
`score_scale.py`'s comment for what's now structurally prevented rather
than promised.
