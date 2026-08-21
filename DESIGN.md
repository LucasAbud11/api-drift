# Design: from research pipeline to a CLI tool

This is a design document only — nothing here is built yet. It answers the
five questions asked: what's hardcoded today, whether the blind-vocabulary
result generalizes, what the tool's interface should be, what happens when
things go wrong, and which invariants must survive the refactor unchanged.

**Update, post-review**: two open questions from the first pass have since
been tested/resolved and are folded in below — whether fact-block
derivation (not just vocabulary derivation) survives contact with a third,
unseen, differently-shaped guide (§2, and full results in
`rule_test/factblock_experiment/report.md`), and whether installing the
real new package replaces fix-gen's hand-built API stub (§4).

## 1. Audit: what's hardcoded to Target A/B today

The pipeline was never one program — it's four stages, each driven by a
mix of general-purpose code and migration-specific prose written by hand
for MCP v1→v2 and OpenAI v0→v1. Going stage by stage:

### Stage 1 — grep vocabulary

- **Already general**: `blind_vocab_experiment/build_candidates.py` takes
  a `PATTERNS` dict (loaded from an arbitrary Python module) and a
  `root_dir`, and grep-walks the tree against the combined regex. Nothing
  in this file names MCP, OpenAI, or any specific symbol.
- **Hardcoded**: the `PATTERNS` dict itself. `vocab_targetB_blind.py` and
  the hand-tuned equivalents are one-off artifacts — a human (or, in the
  blind experiment, a single fresh agent) read a guide once and typed out
  a regex dict, saved as a file. **There is no repeatable step that
  produces this dict from an arbitrary guide today.** This is the main
  piece of engineering the refactor has to add, not adjust.
- **Also hardcoded, easy to miss**: the file walk is Python-only —
  `build_candidates.py` and `prefilter.py`'s `_find_py_files` both filter
  on `fn.endswith(".py")`. A non-Python target isn't unsupported by
  accident; it's unsupported by an unstated assumption baked into two
  different functions.

### Stage 2 — deterministic prefilter (`prefilter_experiment/prefilter.py`)

- **Already general**: `build_relevance_pattern(package_name)` takes the
  target package name as a parameter and builds every reference-form regex
  around it — nothing in stage A names `mcp` or `openai`. Stage C
  (duplicate collapse) is fully generic. The chunked-resume machinery
  (`pipeline.py`'s `ChunkPlan`) and `validate_run.py`'s hard-fail contract
  are migration-agnostic by construction — they operate on the
  three-bucket JSON shape only.
- **Hardcoded / implicit**: `package_name` is a parameter today, but
  nothing upstream currently produces it — a human typed `"mcp"` or
  `"openai"` when calling the function. For the CLI, this has to come from
  somewhere automated (see §3).
- **Language-scoped, not migration-scoped**: stage B's certainty
  guarantees (a match is "certain" only inside a `#` comment or a real
  docstring) are derived via `tokenize` and `ast` — both Python-specific.
  This stage's *safety property* (drop only on structural proof) is
  general; its *implementation* is not.

### Stage 3 — adjudication prompt (`adjudication_prompt_reduced_targetB.md`)

- **Hardcoded, almost entirely**: "THE BREAKING CHANGE" section — the
  nine numbered facts — is migration-specific prose typed directly into
  the markdown file, not a template variable. The worked example under
  "COUNTING CONVENTION" ("if `Context` is imported from a path that
  moved...") is illustrated using Target B's own symbols. `spec_9fact.md`
  (used again, near-verbatim, for fix generation) duplicates this same
  block. Nothing about either file works against a different guide without
  a human rewriting the facts section by hand.
- **Already general, and should stay fixed regardless of migration**: the
  three-bucket output contract (PROPOSE/REJECT/FLAG-UNCERTAIN), and the
  two *mandatory routing rules* — Rule 1 (name-impersonation via
  `sys.modules`) and Rule 2 (test/mock path floor). Neither rule
  references MCP or OpenAI; they're structural judgment rules about *how
  to hedge*, independent of *what changed*. `{CANDIDATE_COUNT}`,
  `{REPO_PATH}`, `{CANDIDATE_LIST_JSON}` are already real template slots.
  The refactor needs one more slot — `{MIGRATION_FACTS}` — carrying
  whatever the guide-ingestion step derived, and the counting-convention
  example either genericized or re-derived per guide rather than pinned to
  FastMCP/Context.

### Stage 4 — fix generation

- **Hardcoded**: `spec_9fact.md` is the same Target-B-specific facts block
  again, copy-pasted into its own file for this stage. The
  mechanical-rename vs. structural-refactor boundary (the thing that
  actually got verified in the study) is currently *asserted in prose*
  inside that same hardcoded spec, not expressed as a standalone,
  migration-independent rule.
- **A generality gap, mostly solved on reconsideration**: mechanical
  verification (`fix_generation_experiment/verify/verify.py`) checked that
  a migrated import resolves by executing it against `verify/mcp_v2_stub/`
  — a hand-built stub of the *new* MCP API, written by hand for this one
  migration, with no general equivalent. Revisited in §4: in real use the
  new version is a real, published, installable release, so installing it
  replaces the stub outright for import/shape verification — the stub
  becomes a last-resort fallback for the (real but narrower) case where
  installation itself isn't possible. What real install does *not* fix —
  verification bounded by the customer's own mocked tests, and
  live/behavioral checks beyond static shape — is unchanged and stays
  documented as a real limitation, not solved by this reconsideration.

### Not part of the tool at all

`ground_truth/`, `gt.py`, `score.py` — these grade the pipeline against a
hand-built answer key for the two studied migrations. They have no
equivalent when the tool is pointed at a repo nobody has already solved.
The CLI has no ground truth to check itself against; the human reviewing
its output *is* the check, every time, forever. Worth stating plainly so
nobody goes looking for a scoring step that isn't supposed to exist in
production.

## 2. Does the blind-vocabulary result generalize?

**Confirmed, with the exact scope the study actually tested.**
`blind_vocab_experiment/report.md`: a fresh agent given *only* the
official guide text — no repo access, no counting convention, no task
framing, no output contract, no knowledge this was a study — derived a
`grep -E` vocabulary that achieved 100% candidate-set recall on both
targets, at both scales (13/13 and 20/20 ground-truth sites, plus the
diluted-host variants). That is the real "no human writes the vocabulary"
condition, not a reconstruction — it's the key unlock, and it's real.

What would have to be true for it to hold on a guide the study never saw:

- **The guide has to actually state the fact.** This isn't a caveat about
  vocabulary quality, it's a hard ceiling already observed *inside* the
  study: the entangled host's one grep-invisible site (a mock-assertion
  call-chaining idiom) was missed because no fact in the guide described
  it — not because the derivation was sloppy. A vocabulary derived from a
  guide can only be as complete as the guide. An incomplete, vague, or
  informal guide (a changelog bullet, a Slack message, a partial diff)
  gives the derivation step nothing to work from for whatever it omits.
- **Recall generalizing does not mean candidate-set *size*
  generalizes — and size is the thing that actually breaks things.** The
  report's own vocabulary diff shows why: Target A's guide text is fully
  namespace-qualified (`openai.ChatCompletion.create`), so any faithful
  vocabulary stays naturally scoped. Target B's guide states several
  changes as bare, unqualified identifiers (`extra=`, `data=`,
  `.error()`), and a faithful vocabulary can't scope those down without
  inventing a qualifier the guide never states — hence 5x more candidates
  than the hand-tuned version, at both scales. A guide written entirely in
  bare-identifier prose (common in informal, internal migration docs)
  could produce a candidate set well past 1121 — already the volume where
  this study measured real completion failures (2 of 3 adjudication runs
  failed outright; see §4). The unlock is real for *recall*; it says
  nothing about *cost*, and cost is guide-shape-dependent, not
  agent-skill-dependent.
- **The derivation step itself has never gone through the mechanical
  pathway.** It was a one-shot "agent reads guide, hand-types a Python
  dict, human saves the file" — never an automated call whose own output
  gets validated before being trusted. Wiring that up, and giving its
  output the same hard-fail contract every other stage has
  (non-empty, syntactically valid regexes, at least one pattern per
  guide-stated fact or an explicit "uncovered facts" list — see §4), is
  new engineering with no existing test coverage.
- **Two guides, both well-written, both official, both Python.** Never
  tested against a guide that's vague, structurally messy, or in a
  language other than Python. The 100% number is a real result about two
  real, unmemorized, well-documented migrations — not yet evidence about
  guides in general.

Net: treat "an agent can derive a working vocabulary from a guide alone"
as validated. Treat "the resulting candidate set will be a manageable
size" as an open, guide-dependent question the tool has to detect and
handle at runtime, not assume.

### 2a. The other half: does the same hold for deriving the *fact block*?

The blind-vocabulary result only ever validated one of the two things a
guide has to produce. Everything downstream of grep — the adjudication
prompt's "THE BREAKING CHANGE" section, fix generation's spec — depends on
a *fact block* (numbered facts, old-vs-new, explicit non-scope statements),
and that step had never been measured in isolation. Tested it the same
way, on a third migration neither of us had touched: redis-py's "Unified
Responses" change (real, published, currently shipping, a different
library, a guide chosen to be structurally unlike either prior one — a
dense internal spec table, no narrative framing). Ground truth built by
hand (25 facts); three fresh, walled-off agents, given only the guide text
and no access to this project's other specs, each derived a fact block
independently. Full setup and per-fact scoring:
`rule_test/factblock_experiment/report.md`.

**Result: 25/25 ground-truth facts recovered in all 3 runs, zero invented
facts.** Including the one deliberately tricky case (a command family
where the guide's RESP2 and RESP3 tables describe the *opposite* direction
of shape change) — all three runs caught the reversal explicitly rather
than pattern-matching past it. This validates fact-block derivation as
real, not just vocabulary derivation — the "no human writes the spec"
unlock extends to both halves of what a guide has to produce, at least for
guides that state their facts clearly.

**What it doesn't settle, same shape of caveat as above**: this guide was
unpolished in *framing* (no prose, an internal spec doc) but not in
*organization* — a well-formed table gives every fact a hard, checkable
boundary, which makes transcription easier than derivation from ambiguous
prose would be. A guide where facts have to be *inferred* — unstated
exceptions, assumed reader context, an incomplete changelog — is a
different and still-untested failure surface. Treat "derivation is
reliable given a guide that states its facts" as validated twice now
(vocabulary and fact block); treat "reliable regardless of how badly the
guide is written" as still open.

## 3. Proposed interface

A single CLI, `api-drift`, local-repo-only for v1 (no cloning, no PR
integration). Runs are always resumable from a workdir on disk.

```
api-drift run --repo <path> --guide <path> [options]

Required:
  --repo <path>     local path to the target repository
  --guide <path>    the migration guide, as a text/markdown file

Optional:
  --package <name>  override the inferred primary import name; if omitted,
                     the guide-ingestion step must state one or the run
                     hard-fails (§4) — never silently guessed
  --workdir <path>  default ./.api-drift-run/<timestamp>/
  --interactive     pause after vocabulary derivation and before
                     adjudication if candidate volume crosses a threshold,
                     for a human sanity check (default in a TTY)
  --no-interactive  never pause; for CI (default when not a TTY)
  --no-relevance-filter   skip prefilter stage A outright (see §4, monorepo case)
  --skip-fix-generation   stop after detection
  --resume <workdir>      continue a previous run from its saved state
```

**What it prints** — stage-by-stage progress and a final summary, not just
a log dump:

```
[1/4] Deriving vocabulary from guide...        12 patterns, package "mcp"
      2 guide facts have no corresponding pattern — see vocabulary.json "uncovered"
[2/4] Searching repo (247 files)...             1,842 raw candidates
[3/4] Prefiltering...                           dropped 1,203 (A: 1,050, B: 153) → 639 remain
      stage A reduction: 57% (within normal range)
[4/4] Adjudicating (16 chunks of 40)...         [====......] 9/16, 1 chunk retried
      PROPOSE: 31   FLAG-UNCERTAIN: 8   REJECT: 600
      Fix generation: 27 FIX, 4 FLAG-FOR-HUMAN, 0 skipped
Done. Report: .api-drift-run/2026-08-20T14-03/report.md
```

Any hard-fail condition (§4) stops the run at that line with the specific
reason — never a downgraded pipeline that continues silently.

**What it writes to disk**, under the workdir:

- `vocabulary.json` — the derived patterns plus the package name and the
  "uncovered facts" list, so a human can inspect or hand-edit it *before*
  the expensive stages run
- `candidates.json` — raw grep hits
- `droplog.json` — every prefilter drop, stage + rule + reason (never
  silent, per §5)
- `adjudication/chunk_*.json`, `adjudication/merged.json` — the validated
  three-bucket verdicts
- `fixes.json` — per confirmed site, either a `FIX` (file, line, diff) or
  a `FLAG-FOR-HUMAN` with a reason
- `report.md` — the single human-readable artifact: every PROPOSE and
  FLAG-UNCERTAIN site, its fix or hedge reason, in one document meant to
  be read top to bottom

**What the user does with it**: reads `report.md`, and for each site they
accept, applies it themselves. The tool proposes; it does not push. No
git operations, no PR, no auto-apply-all. An optional
`api-drift apply-fix <workdir> --site <file:line>` can patch exactly one
file for one accepted site, on request — never a blanket apply, so a
human stays in the loop for every single edit that lands.

## 4. Failure modes

**The guide is vague or badly written.** The vocabulary-derivation step
must report which guide-stated facts it could not turn into a concrete
syntactic pattern, and print that "uncovered" list prominently rather than
silently shipping a thinner vocabulary. If it produces zero usable
patterns, that's a hard stop with the guide-ingestion agent's own
explanation surfaced, not a run that proceeds against an empty vocabulary
and reports false confidence.

**The vocabulary comes out enormous.** This already happened in-study —
Target B diluted, 1121 candidates, 2 of 3 single-shot adjudication runs
failed outright, the third silently dropped a field until the validator
caught it. The fix that already exists and works is chunking
(`pipeline.py`), not vocabulary narrowing — so the tool always chunks,
regardless of candidate count, never single-shots. Above that, an
`--interactive` run pauses and shows the candidate count before committing
to the (potentially large) adjudication cost; a hard ceiling
(configurable, default something like 5,000 post-prefilter candidates)
stops the run and requires `--force` to proceed, rather than degrading
quality to push through.

**The repo is huge.** Stage A's transitive import-graph closure is
untested at monorepo scale, and the existing code already documents the
risk honestly: on a repo with one shared internal module most files
import, transitive closure could approach "almost nothing gets dropped,"
collapsing stage A's reduction value toward zero. That's a cost problem,
not a correctness one — the fallback is `--no-relevance-filter` (stages
B/C only), which the tool should suggest automatically when it measures
stage A's own reduction ratio falling below a threshold (e.g. <10%),
surfaced as a visible message, not a silent internal switch.

**The adjudication batch fails partway.** Already solved, not a new
design problem: `ChunkPlan` writes one validated file per chunk, atomically,
and `pending_chunks()` only re-offers what isn't done. The CLI's
adjudication stage is a thin wrapper over this — `api-drift run --resume
<workdir>` re-enters at exactly the chunks that never completed.

**Mechanical fix verification has no "new API" to check against — reconsidered.**
The study's verification stub (`verify/mcp_v2_stub/`) was hand-built for
one migration. The original design treated that as a permanent gap. It
isn't, for the part that actually matters most: **in real use the new
package version is a real, published release — install it, and use the
real thing instead of a stub.** A stub is only ever a stand-in for
something installable; where installation is possible, the stub is
strictly worse (it encodes only what the guide's text described, which can
lag or omit real API details) and should never be built. Concretely:

1. `ast.parse()` every touched file (always — no dependency).
2. **Real install, default tier**: `pip install` the new version (pinned,
   in an isolated venv/container so it can't collide with the repo's other
   deps) and exec every touched import statement against it directly. This
   fully replaces the stub for import/attribute/signature-shape checks —
   it's exact, not an approximation, and it can go further than the study
   ever did (`inspect.signature` on touched calls, real attribute-existence
   checks), because it has the whole real API surface, not just the
   symbols someone bothered to hand-write into a stub.
3. If the repo has a runnable test suite, run it before/after against the
   real installed package and compare the failing-test set.
4. Text-derived stub (only the symbols the fact block actually names),
   used only when real install fails — not installable in this
   environment (private/internal package, incompatible Python pin,
   unbuildable native extension, no network) — and reported as a
   downgraded tier when used, never presented with tier-2 confidence.

**What real install does *not* fix — two independent gaps, only one of
which installation touches:**

- **The mocked-test blind spot is untouched by this change.** `REPORT.md`
  §6's limitation stands exactly as before: if the repo's own tests mock
  away the exact boundary the migration changed, running those tests
  against the real package still can't distinguish a correct fix from a
  plausible-but-wrong one — the entangled host's `session_group.py:38`
  case (two structurally different, mutually exclusive edits, both passed
  the suite) failed because the *test* mocks `ClientSessionGroup`, not
  because the verifier lacked a real package. Installing the real
  dependency doesn't make a mock stop being a mock. Tool output should
  keep saying this plainly, not imply real-install verification is
  stronger than the customer's own tests support.
- **Live/behavioral/network correctness is still out of reach.** A real
  install confirms the Python-level API shape (imports resolve, signatures
  match, attributes exist) — it does not confirm wire-level or service
  behavior (e.g., "does the server still accept the old field") without an
  actual integration test against a live/faked service, which is a
  different, heavier verification tier this design doesn't attempt.
- **Availability is still not universal**, which is why tier 4 (scoped
  text-derived stub) stays in the design rather than being deleted — it's
  now explicitly the fallback of last resort, not the default.

Net: real install becomes the default and replaces the stub for
everything the stub was trying to approximate. It does not touch the
test-mock limitation, which is a property of the customer's tests, not of
what backs the import check.

## 5. Non-negotiables

These survive the refactor unchanged, and the code that already enforces
each of them is the code the CLI should wrap, not reimplement:

- **Three-bucket contract.** `validate_run.py`'s `REQUIRED_TOP_LEVEL`
  check already treats a missing bucket key as fatal, not defaulted to
  `[]`. Every adjudication call in the CLI goes through
  `validate_run_file()` before its output is trusted, exactly as today.
  Fix generation keeps its own two-bucket analogue, FIX / FLAG-FOR-HUMAN.
- **Prefilter never drops on ambiguity.** The fail-safe principle stated
  at the top of `prefilter.py` — drop only when the reason is provably,
  syntactically certain — does not get relaxed to buy more reduction at
  scale. Parameterizing `package_name` and the vocabulary per-migration
  must not touch this guarantee; the existing AUDIT NOTEs about stage A's
  residual uncertainty (entanglement via a channel the import graph can't
  see) stay honestly stated in the tool's output, not quietly dropped from
  the docstring on the way to a CLI.
- **Hard-fail rather than silently default.** This principle currently
  covers the three-bucket shape; it has to extend to the two new
  automated steps that don't exist yet — vocabulary derivation (fail on
  empty/unusable output, surface uncovered facts rather than hiding them)
  and package-name inference (fail rather than guess when the guide is
  ambiguous about what's actually being imported).
