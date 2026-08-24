# Fact-block derivation experiment: does the blind-vocabulary result extend to fact-block derivation?

The blind-vocabulary experiment (`rule_test/blind_vocab_experiment/report.md`)
validated that an agent can derive a working **grep vocabulary** from a
migration guide alone. It never tested the other thing the whole pipeline
depends on: deriving the **fact block** — the numbered "here's what changed,
here's old vs. new, here's what's explicitly NOT affected" spec that the
adjudication and fix-generation prompts are built around
(`rule_test/prefilter_experiment/adjudication_prompt_reduced_targetB.md`,
`rule_test/fix_generation_experiment/spec_9fact.md`). This experiment tests
that step, in isolation, the same way: build ground truth by hand, run
fresh walled-off agents blind, and check what they got right, missed, or
invented — scored separately, because they have different downstream
consequences (a missed fact causes a missed site later; an invented fact
causes a wrong fix later).

## Setup

**Target**: redis-py's "Unified Responses" migration
(`legacy_responses=False`), a real, currently-shipping opt-in breaking
change — different library from MCP/OpenAI, real Python SDK, neither of us
had touched it before this experiment. Source:
`specs/unified_responses_migration_guide.md` in `redis/redis-py`, fetched
fresh via `gh api` (not from memory) at commit
`0ed4b69ccc14f081bfbbb6232b04b9d113db02c5` on `master`, 2026-08-20. Verbatim
copy at `guide_redis_unified_responses.md` in this directory.

**Why this guide, specifically for "less polished"**: it's an internal
`specs/` companion doc in the repo, not a docs-site page — no narrative
framing, no worked examples, no counting-convention paragraph like the
MCP/OpenAI guides had. It's two dense tables (RESP2-legacy→unified,
RESP3-legacy→unified) covering ~40 Redis commands across 18 subsystem
areas, plus a short activation section and one standalone caveat section.
Structurally nothing like either prior guide's numbered prose.

**One honest caveat on "less polished" stated up front**: this guide is
unpolished in *framing* (no prose walking a reader through it) but not in
*organization* — it's a complete, well-formed table, which makes each row
individually unambiguous to transcribe. That's a different, real kind of
"less polished" than a *vague or badly organized* guide would be (bullet
points assuming reader context, prose with unstated exceptions, an
incomplete changelog). This experiment stress-tested a real,
narratively-unpolished, structurally-different, densely-detailed guide. It
did not yet stress-test a guide where facts have to be *inferred* rather
than *transcribed*. See "What this doesn't settle" below.

**Ground truth** (`ground_truth_factblock.md`): built by direct reading of
the guide, 25 facts at "Area" granularity (the guide's own grouping
column), before any blind agent ran. Flags one deliberately tricky case
(fact 18, Geo) where the guide's RESP2 and RESP3 tables describe the
*opposite* direction of shape change for the same command family
(`GEOSEARCH`/`GEORADIUS`/`GEORADIUSBYMEMBER`) — a real test of whether
derivation catches subtlety or just pattern-matches "structural change =
tuple/list/dict swap."

**Derivation agents**: 3 independent, fresh `general-purpose` agents, each
launched cold with no conversation history, explicitly instructed not to
use any tool (no Read/Grep/Glob/Bash, no repo exploration) and given
*only* the guide text pasted into the prompt — no access to this project's
existing specs, prompts, reports, or the ground truth file. Same isolation
discipline as the blind-vocabulary experiment, and per
[[feedback_isolated_adversarial_construction]]: the agent building the
detector's downstream input is not the same agent (or process) that grades
it. Raw output for each run: `derived_run1.md`, `derived_run2.md`,
`derived_run3.md`.

## Result: 25/25 facts recovered, 3/3 runs, zero invented facts

| Run | Facts recovered (of 25 GT facts) | Missed facts | Invented facts |
|---|---|---|---|
| 1 | 25/25 | 0 | 0 |
| 2 | 25/25 | 0 | 0 |
| 3 | 25/25 | 0 | 0 |

Scored by reading each of the 25 ground-truth facts against all three
derived fact blocks. Every fact — including the deliberately scattered
ones (ACL's behavior is split across 5 separate table rows; RediSearch's
across 12) — appears correctly in every run. **The hardest single fact in
the set, the Geo asymmetry (fact 18), was caught precisely by all three
runs**, each one explicitly noting that `GEOPOS` changes on the RESP2 path
but not the RESP3 path, while `GEOSEARCH`/`GEORADIUS`/`GEORADIUSBYMEMBER`
do the reverse — the exact subtlety ground truth flagged as "watch
closely." No run pattern-matched its way past this; all three stated the
direction-reversal explicitly and correctly.

**Invented facts: none.** No run asserted a behavior, scope statement, or
shape that isn't actually in the guide text. The one blemish, and it's
minor: run 3's fact 5 states "the guide does not explicitly state which of
its two delta tables governs the diff for the default `Redis()` case" —
this slightly overstates a real ambiguity (the guide's own RESP2/RESP3
table headers track wire protocol, which the Response Mode Matrix already
disambiguates for that exact case). It's a labeled uncertainty, not an
asserted false fact, and its failure direction is the safe one: it would
make a downstream system hedge on an already-clear case, not propose a
wrong fix. No other candidate inventions found across any run.

**Minor completeness gap, not a miss**: runs 2 and 3 correctly capture
`FT.SYNDUMP`'s behavior (grouped with `FT.INFO`/`FT.CONFIG GET` in the
RESP3 table) but don't flag that `FT.SYNDUMP` has no RESP2-table row at
all — run 1 does flag it explicitly. This doesn't cause a missed or wrong
fact (the actual behavior is stated correctly in all three), just a
difference in how much cross-table structure gets annotated. Noted for
completeness, not counted against recall.

## What this validates

The blind-vocabulary result generalizes to the fact-block-derivation step,
under the same "guide states it, agent can transcribe/derive it precisely"
condition — and with a stronger invention result than recall alone would
suggest: three independent runs, zero false facts, on a real guide neither
of us had built anything around before. This directly answers the open
question the design doc raised in §2 ("the derivation step itself has
never gone through the mechanical pathway") for the fact-block half of
that pathway specifically — it can.

## What this doesn't settle

- **Only one guide, tested once (with 3 reruns for variance, not 3
  different guides).** A second, differently-shaped guide — especially a
  genuinely vague one — would be needed before treating "guide in, correct
  fact block out" as guide-shape-independent. This guide's *table*
  structure means each fact had a hard, checkable boundary (a row); a
  prose guide with unstated exceptions or ambiguous scope requires the
  agent to *infer* fact boundaries, not just transcribe them, which is a
  different and untested failure surface.
- **All three runs converged on similar granularity** (Area-level, roughly
  matching ground truth's own grouping) without being told the guide's own
  grouping column existed. That convergence is itself informative — it
  suggests the guide's own structure, not agent idiosyncrasy, drives
  granularity — but a genuinely unstructured guide (a paragraph, not a
  table) hasn't been tested and might show more inter-run variance in
  where facts get split or merged, which is exactly the kind of variance
  that caused downstream problems for vocabulary breadth in the earlier
  experiment.
- **Guide completeness is still an unfixable ceiling, not something this
  step can compensate for** — same limit the blind-vocabulary experiment
  already established for vocabulary derivation (the entangled host's one
  grep-invisible site, missed because no fact in the guide described it).
  A fact-block derivation agent can only be as complete as its source; this
  experiment measured transcription fidelity given a complete source, not
  robustness to an incomplete one.

Net for the design: fact-block derivation is validated as the second
mechanically-automatable step (alongside vocabulary derivation) for guides
of this shape and completeness. The residual open question is guide
*quality* variance (vague/incomplete/unstructured prose), not agent
capability on a guide that states its facts clearly — worth flagging as
the next thing to test before shipping, not a blocker to designing around.
