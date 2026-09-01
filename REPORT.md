# Can an LLM agent find code broken by an API migration more reliably than grep?

## 1. The problem

When a library or SDK ships a breaking change, every call site that depends
on the old behavior needs to be found and fixed. Grep can search a codebase
in seconds, but a regex either over-matches (flags decorators, unrelated
namesakes, coincidental substrings) or under-matches (misses aliased
imports, indirect usage, mock/stub code) — and there's no way to know in
advance which failure mode a given pattern will hit without already
knowing the answer. Manual review doesn't scale to a real codebase.

The hard part isn't finding text that matches a keyword. It's telling
apart two lines that look identical or near-identical but have opposite
fates: `ctx: Context` as a type annotation (fine, once the one import
line above it is fixed) versus `from mcp.server.fastmcp import Context`
(the actual break); `ClientSession.call_tool()` (unaffected) versus
`ClientSessionGroup.call_tool()` (broken) — same method name, different
class. A tool that can't make that distinction is either too noisy to
trust or too cautious to be useful. This project measured whether an
LLM-based detection agent can make it reliably, where reliably means:
recall (does it find the real sites) matters more than precision (does
it avoid false leads), because a missed site becomes a bug and a false
lead costs a human a few seconds.

## 2. Method

Two "targets," each a real Python SDK with a defined breaking-change
migration, each with an independently constructed answer key (file, line,
and why) built by direct code reading — never by asking the detector and
checking its own answer.

- **Target A**: OpenAI SDK v0.x → v1.x, a real, well-documented migration,
  applied to 4 public repos (13 ground-truth sites).
- **Target B**: MCP Python SDK v1 → v2, a real migration with a real
  public guide (py.sdk.modelcontextprotocol.io), released July 2026,
  applied to 5 public repos (20 sites after one correction — see below).

Target B is the control, and the reason is its recency, not its
existence. Target A's migration is real and old enough that a model
could plausibly recite its facts from memorized training data without
reading a single line of code — good performance there doesn't
distinguish "reasoning about this codebase" from "recalling a famous
migration guide." Target B's migration is equally real, but it shipped
after any realistic training cutoff for the models used in this study —
nothing about it could have been memorized, so a correct answer can only
come from reading the supplied guide and the actual code. (The one
invented artifact anywhere in this study is a synthetic test application
built later for one experiment, Section 3 below — the migration itself
was never fictional.) Target A stayed clean (100%/100%, no exceptions,
every experiment); nearly everything interesting — every reversal below
— happened on Target B, exactly what the control is supposed to surface.

## 3. Findings, in the order they were found

**Recall looked like a wash; the whole story looked like precision.** The
first full run reported grep and the agent tied on recall (100%/100%,
both targets) with the agent 33 points ahead on precision (55.3% vs
21.9% on Target B). The prescribed fix — separate import/definition
sites from downstream usage sites — was predicted to push Target B
precision to 100%.

**That prediction was circular.** It was tested by reconstructing "agent
output" as ground truth plus the 17 documented false positives, then
applying the fix to that reconstruction. Reaching 100% was guaranteed by
construction, not measured. Flagged and redone.

**The 55.3%/48.5% figures never reproduced.** Nine fresh, walled-off
agents were actually re-run from scratch. Zero false positives on either
target, 100%/100% recall and precision across the board — every agent
independently rejected all 17 `ctx: Context` sites the original run had
flagged. Whether this was "the rule working" or "this session's spec
already stating the fact that caused the original mistake" couldn't be
settled, because the original spec text hadn't been persisted anywhere.

**The original spec was recovered from disk, and it explained everything.**
It was a 9-item document, not the 6-item digest this study had been
reconstructing from, and it told agents that a `FastMCP` type annotation
is broken while staying silent on whether a downstream `Context`
annotation counts the same way — an asymmetry the reconstruction had
accidentally resolved. Re-running on the real 9-item spec, with one added
paragraph making that counting convention explicit, produced zero false
positives across 27 runs (9 repos × 3), including the two repos that had
produced the original 17. The 55.3% story was a spec-completeness gap,
not a reasoning failure — the agents' own recorded language showed
correct diagnosis of the root cause paired with a defensible-but-wrong
judgment call on a question the spec never actually answered.

**Ground truth was wrong, twice, and both times the correction survived
scrutiny.** First: a QAInsights test file's `class FastMCP:` statement
was counted as a required-edit site. An agent disagreed, arguing the
mock's *exposed* attribute name is what matters, not the local class
identifier. Instead of arguing, the migration was actually performed on
a scratch copy and the test suite run — identical pass/fail to the
already-migrated baseline, with a negative control confirming the harness
discriminates real breaks. Ground truth was wrong; the site was removed,
20 sites replaced 21. Second, much later: while independently deriving
ground truth for a new synthetic host, one real site (a call to a
function the spec says is removed entirely) was missed on the first pass
because the derivation leaned on a stale, simplified guide instead of the
authoritative one. All three agents scoring against it caught the site
correctly; the ground truth, not the agents, was corrected before
scoring.

**A new failure mode appeared only at scale, with no small-scale
analogue.** Diluting the search space (5 real repos embedded in a
675-file, unmodified chunk of Django source) held precision at 100% but
dropped recall to a flat 85% in all 3 runs — the same 3-line test-mock
cluster, missed every time. Pulling the actual tool-call transcripts (not
just final answers) showed the file being read in full in every run: not
a retrieval failure. The misses split into two mechanisms. One was
familiar — reached, reasoned about, explicitly and wrongly rejected. The
other, "mechanism B," was new: content sat in the agent's context and
simply never turned into a verdict in any bucket — not proposed, not
rejected, not flagged, no reasoning trace anywhere. Total output length
tracked with which mechanism dominated, consistent with a per-item
accounting budget that doesn't scale with host size. Separating the
agent's two jobs — grep does exhaustive, low-precision search; the agent
adjudicates only a fixed, closed candidate list, one verdict each,
nothing to search for — eliminated mechanism B completely: the identical
cluster that failed 9 times under combined search-and-judgment was
proposed correctly in 6 of 6 separated-role runs.

**Entanglement broke something dilution never touched.** Every host up to
this point tested dilution — more unrelated code, zero structural
interaction with the target SDK. A separate, walled-off agent (given only
the public migration guide, no access to this project's detector prompt,
vocabulary, or filtering code) built a small application that used the
SDK entirely through its own subclasses and wrapper classes. Grading it
against independently-derived ground truth found three distinct failure
mechanisms in one host: one real site invisible to the grep vocabulary
itself (a mock-assertion call-chaining idiom no pattern anticipated); two
sites dropped by a deterministic candidate-reduction filter that assumed
"no reference to the package anywhere in this file" was safe to treat as
certain irrelevance — wrong here, because the file touched the SDK's data
shape only through the app's own wrapper and never named the package.
One of those two was production code, not a test file — the only
production-code miss recorded anywhere in this study. Traced to the
filter, not the agent (confirmed by disabling the filter and
re-running: the agent proposed the site correctly every time given the
chance), fixed by making the filter's relevance check follow the
codebase's own import graph instead of just the file's own text, and
re-verified with 9 fresh runs across three hosts: the fix recovered the
site with zero regressions and zero new production misses, at a real,
accepted cost in how much the filter reduces candidate volume.

## 4. Final architecture

Three stages, each doing one job:

1. **Grep** — exhaustive, coverage-tuned pattern matching. Not asked to be
   precise; a broad vocabulary derived from the public guide alone
   (without looking at the answer key) found all 33 ground-truth sites in
   the core study — but not universally: the same vocabulary missed one
   site on the entangled host (Section 3), a mock-assertion idiom no
   pattern anticipated. Grep is exhaustive relative to the vocabulary
   someone wrote, not exhaustive by construction.
2. **A deterministic, LLM-free prefilter** — cuts candidate volume (raw
   candidate counts in the thousands caused outright completion failures
   before this existed) using rules built to fail toward *keeping*: a
   candidate is dropped only when the reason is structurally provable
   (a comment, a real docstring, a byte-identical duplicate), never
   because positive evidence merely wasn't found. Every drop is logged
   with its exact reason, so a miss is auditable, not silent by default.
3. **LLM adjudication** — given only the fixed candidate list, sorts each
   one into PROPOSE / FLAG-UNCERTAIN / REJECT. Two mandatory routing
   rules override the agent's own confidence when a structural marker is
   present (code that impersonates an SDK symbol via `sys.modules`; any
   test/mock file path), forcing a hedge instead of a guess.

The separation between stage 1/2 and stage 3 is not incidental — it's the
direct fix for the only failure mode in this study that had no small-scale
warning sign. An agent asked to both find everything and judge everything
in one unconstrained pass degraded in a way invisible until the search
space got large; an agent asked only to judge a list someone else already
found did not.

**A fourth stage, fix generation, sits downstream of detection and draws
its own boundary.** Given a confirmed site, it either proposes the exact
corrected line or declines and flags the site for a human — and the line
it draws between those two outcomes is the central fact about this stage:
breaking changes split into **mechanical renames** (an import path moves,
an identifier is renamed, a field changes case) and **structural
refactors** (a function is removed with no drop-in replacement, and the
fix has to change how a call site is shaped, not just what it's called).
The first category gets an automatic single-line fix. The second gets
declined outright, not guessed at. This boundary was not asserted — it was
verified by construction, on a host (`OpsMesh`) built by a separate,
walled-off agent with no knowledge of this study, then checked by actually
running that host's real test suite before and after each candidate fix,
not by reading. Two of its ten confirmed sites reference `mcp.get_context()`,
a function removed entirely in v2 with no path-only substitute; the
correct fix touches 6 files and ~15 lines, because the SDK's stated
replacement is injecting `ctx: Context` as a handler parameter, not
renaming an import. A pattern-matching fix generator that tried the naive
single-line edit anyway — tested directly — throws `ImportError` at import
time. Across 3 independent runs on that host, the stage proposed a
confident, exactly-correct single-line fix on every site that actually has
one (18/18 across the 6 such sites) and declined every site that doesn't
(12/12 across the 4 such sites, 0 wrong guesses) — the auto-fix/flag
boundary landed in the right place every time it was tested against a host
built to contain both kinds of change. Full methodology, per-site answer
key, and mechanically-verified evidence (diffs, negative controls, a real
pytest run before and after each fix) in
`rule_test/fix_generation_experiment/report.md` and `report_scale.md`.

## 5. Results, current architecture, across every host tested

| Host | GT sites | Precision | Recall (surfaced) | Recall (propose-only) | Production misses | Candidate reduction |
|---|---|---|---|---|---|---|
| Target A, 4 repos | 13 | 100% | 100% | 100% | 0 | 30.8% |
| Target A, diluted (685-file host) | 13 | 100% | 100% | 100% | 0 | 30.8% |
| Target B, 5 repos | 20 | 100% | 100% | 95–100% (3 runs) | 0 | 81.1% |
| Target B, diluted (1121→111 candidates) | 20 | 100% | 100% | 85–100% (3 runs) | 0 | 90.1% |
| Target B, entangled host (built blind) | 10 | 100% | 90% | 70–90% (3 runs) | 0 | 36.2% |

"Surfaced" recall counts a site as found if it appears in PROPOSE or
FLAG-UNCERTAIN — nothing silently vanished. "Propose-only" recall, the
stricter number, dips when the agent correctly hedges on a genuinely
ambiguous fact rather than guessing. The entangled host's 90% surfaced
ceiling is the one number here that isn't a hedge: it's the single
real site the grep vocabulary never turned into a candidate at all.

Every row is one consistent, fresh, end-to-end run of the current
three-stage pipeline: the same prefilter code, the same candidate list
shown, adjudicated 3 times per host, 15 runs total. No row mixes in a
result from before this exact pipeline existed.

**Fix-generation results**, run separately on top of each host's confirmed
detection output, 3 runs per host:

| Host | Sites with one correct fix | Exact-match | Sites with no single-line fix | Legitimate hedge | Locally-plausible-but-globally-wrong |
|---|---|---|---|---|---|
| targetB_small, 5 repos | 20 | 100% x3 (60/60) | 0 | n/a | n/a |
| targetB_diluted | 20 | 100% x3 (60/60) | 0 | n/a | n/a |
| entangled (this host) | 6 | 100% x3 (18/18) | 4 | 100% x3 (12/12) | 0% x3 (0/12) |

"Locally-plausible-but-globally-wrong" is a confident single-line fix on a
site that has no correct single-line answer — the failure mode that would
actually ship a bug, as opposed to a false positive costing a reviewer a
few seconds. It never fired: on the 4 entangled sites where no such answer
exists, every run flagged instead of guessing. Every fix proposed anywhere
in this table was also mechanically verified — parses, the specific
migrated import resolves against a from-scratch v2 SDK stub, and (where a
host had a runnable test suite) that suite's pass/fail signature was
compared before and after the fix — not just scored against the answer key.
Detail, per-site answer keys, and raw agent output:
`rule_test/fix_generation_experiment/`.

## 6. Limitations, stated plainly

**Mechanical verification proves self-consistency, not correctness.**
Every "verified by running the host" claim for the fix-generation stage
means the codebase parses, the migrated import resolves against a stub,
and existing tests still pass after the fix — not that the fix matches
the real v2 SDK's actual behavior. This gap is not hypothetical: the
entangled host's `client/session_group.py:38` has two structurally
different, mutually exclusive edits (pass the removed argument as a
keyword vs. drop it entirely) that were each applied, together with a
matching update to the one test that exercises that call, and **both
passed** the host's real test suite. The suite can only confirm the
wrapper and its test agree with each other — it tests the wrapper against
a `MagicMock`, never against the real `ClientSessionGroup`, so it has no
way to know which interpretation the shipped v2 API actually implements.
The verification harness inherits the quality of the customer's own
tests: a repo with strong, non-mocked coverage at the exact boundary a
migration changed gets a real correctness signal from this stage; a repo
whose tests mock away that boundary gets none, and "the tests still pass"
is not, by itself, evidence the fix is right. This is a property of
testing against mocked wrappers in general, not a defect specific to this
study's harness — but it means the tool's confidence should never be
allowed to exceed the confidence already present in the customer's own
test suite.

**Test/mock coverage is the study's real, recurring weak spot** — four
independently-discovered mechanisms, not one recurring bug: an agent
over-applying "fixing the import repairs downstream usage" to code that
*impersonates* a moved symbol rather than merely referencing it; the
scale-only silent-omission mechanism above; a grep vocabulary gap on
chained mock-assertion syntax; and the mandatory hedge rule correctly
firing on this exact class of code, which lowers strict recall without
losing anything. Across every recorded miss in this study, test/mock
sites account for the large majority of instances despite being a small
minority of all ground-truth sites — a real concentration, not an
artifact of where sites happen to live. It is asymmetric in a way that
matters: every test/mock miss recorded here would throw immediately in
CI (`ImportError`, `AssertionError`) if shipped unmigrated — a second
safety net a missed production site doesn't have.

**The candidate-reduction filter's fix is unproven on a shared-core
monorepo.** It now follows a codebase's own import graph to avoid
dropping files that touch an SDK only through the host's own wrapper —
fixed and verified on the one host that exposed the bug. Every host
tested here is either a handful of independent small repos or one large
repo with no single shared internal module most files import. A real
company monorepo with a shared internal SDK/framework layer is
structurally different and untested; if the filter's relevant file is
central to such a codebase, its reduction value could collapse toward
zero there. The documented fallback is dropping that filter stage and
absorbing higher review volume — a cost problem, not a silent-miss one.

**Everything here is one migration per target, one SDK family per
target, and one language.** All 43 ground-truth sites across the whole
study are Python. Nothing here tests a second language, a breaking
change with no textual signature (a behavior-only change, a
config-driven default), or a codebase behind on more than one migration
at once.

**The absolute sample size is small.** 43 ground-truth sites is enough
to find and characterize specific failure mechanisms, not enough to
claim their rates are stable. Both real gaps found here — the test/mock
cluster and the entanglement miss — were invisible until a host was
specifically built to go looking for them; a larger, more varied corpus
could easily surface another one the same way.

## 7. What would have to be true for this to be a product

This measures detection accuracy, and now fix-generation accuracy, on a
fixed, known candidate list against hand-verified answer keys. It does
not measure: whether a real reviewer trusts and acts correctly on a
PROPOSE/FLAG-UNCERTAIN/REJECT (or FIX/FLAG-FOR-HUMAN) list in an actual
workflow; whether grep-vocabulary derivation holds up against guides far
less complete than these; latency and cost at repository sizes larger
than anything tested; a real shared-core monorepo, flagged above as
untested; a second language; a breaking change with no grep-able
signature at all; or a codebase behind on several overlapping migrations
at once.

One gap on an earlier version of this list has since closed, in the open,
worth naming because it's the pattern the rest of this list is asking for.
The first fix-generation run observed zero FLAG-FOR-HUMAN hedges across
60 site-verdicts and could only report that the hedge path was
unexercised — genuinely unknown whether it was well-calibrated or simply
never firing. Measured against a host built specifically to contain real
ambiguity, it turned out to be calibrated in both directions: 0 avoidable
hedges across 78 site-verdicts that had one correct answer, 12/12
legitimate hedges across the site-verdicts that didn't. That's a real
answer to a question this report couldn't answer before, obtained by
building the host that could answer it rather than asserting the earlier
silence was fine. Turning the rest of this into a product means closing
the remaining gaps the same way, one at a time — not asserting the final
numbers already cover them.

## 8. From research pipeline to a CLI tool

Everything above measured detection and fix-generation accuracy against a
fixed candidate list and a hand-verified answer key — the answer key
existed before the run did. This section covers what happened when the
same pipeline (fact block → vocabulary → grep → prefilter → chunked
adjudication, per `DESIGN.md`) got packaged as `api-drift`, an installable
CLI a user points at an arbitrary repo and guide, with no answer key
waiting on the other side. That's a materially different artifact, and it
found problems the study, by construction, never could.

**Packaging surfaced three bugs on first contact with the live API that no
amount of re-running the study would have found, because a study built by
construction always exercises the happy path.** The structured-output
schema for the vocabulary stage used an open `additionalProperties`
object, which the real API rejects outright (patterns are now returned as
a `[{name, regex}]` list and converted to the dict every downstream stage
expects). `RepoReader.list_py_files()` used `os.walk` without
`followlinks`, silently finding zero files against the acceptance test's
own symlink-based repo fixture. And fact-block derivation could return
`package_name` as a prose description instead of a bare import identifier
— which breaks the prefilter's relevance regex in a way that doesn't
crash: it drops every single candidate, so the pipeline completes cleanly
and reports nothing wrong on a codebase that has real, unfixed breaking
changes. That's the dangerous shape of failure this whole project is
about avoiding, and it was hiding in the tool's own onboarding step.
Fixed with a hard-fail structural check (`validate.py`'s
`validate_factblock`: `package_name` must fullmatch a bare Python
identifier or the run stops) rather than a tighter prompt alone — per
`DESIGN.md`'s own "fail rather than guess" rule, this is exactly the kind
of gap a prompt can regress on any given call, so the check has to live
in code, not in phrasing.

**Two acceptance cases pin the study's own numbers as regression tests,
not just a memory of them.** `test_acceptance_targeta.py` and
`test_acceptance_targetb.py` re-run Target A and Target B through the
packaged CLI's real code path against the live API and assert the exact
same bar the study used — 100% surfaced recall, 100% precision — with a
third, offline replay tier (`test_replay_targetb.py`) that re-plays a
recorded cassette through the identical pipeline code with no network
call, to catch a plumbing regression for free between real runs. Current
recorded cost: Target A, 12 patterns, $0.1639 for 3 API calls; Target B,
13 patterns, $0.2046 for 3 API calls. Both numbers moved during this
phase's own work — cassettes had to be re-recorded five separate times as
the vocabulary-derivation prompt changed — and both landed back at
100%/100% every time, which is the actual point of having them: a
regression test that can't be beaten by construction here, because the
answer key is the same one the study already earned.

**The first cold run against a codebase this pipeline had never been
shaped around — closeio/tasktiger, migrating to redis-py's Unified
Responses — found two more failure modes no test path could reach, because
every existing test already passes a valid input and a working (real or
mocked) client.** A missing `ANTHROPIC_API_KEY` produced a ~40-line SDK
traceback ending in a `TypeError` from httpx header encoding, not a
usable error — fixed by `preflight.py`, which checks the API key and the
`--repo`/`--guide`/`--workdir` inputs before any network call or repo
access happens, wired into `pipeline.run()` itself so every caller
inherits it. Separately, a response truncated by the `max_tokens` ceiling
was being reported as "not valid JSON" — blaming the model for something
the token ceiling did. `llm.py` now checks `response.stop_reason` and
raises a `TruncatedResponseError` naming the real cause before ever
attempting to parse the (correctly incomplete) text. Neither bug is
subtle in hindsight; neither was reachable by a test suite where every
path already has a valid key and a response that finishes.

**That same guide is the first time this pipeline produced a result with
no answer key to check itself against — the actual product condition, not
a rehearsal of it.** redis-py's Unified Responses guide runs 67–73 facts
depending on the exact derivation (guide-ingestion is not perfectly
deterministic call to call — see below), against a real, unmodified
library's real test suite and application code. A representative full run:
67 facts, 34 vocabulary patterns, 71 raw grep candidates, 37 kept after
prefilter (34 collapsed as duplicates), landing at 21 PROPOSE / 35
FLAG-UNCERTAIN / 15 REJECT after duplicate expansion. Every PROPOSE site
was the same shape — a `redis.Redis(...)` construction point needing
`legacy_responses=False` added — because that's the one place in this
migration where the fix is textually local to the candidate line; every
downstream site whose fate depends on how a caller consumes an
already-returned value is a judgment call this pipeline correctly declines
to guess at, not a design defect.

**The coverage chain grew a third guard, closing the last unchecked link
— and by the end of one day's work, two of the three had each caught
something real.** `check_factblock_coverage` (guide → fact block) and
`check_vocabulary_yield` (does one grep pattern dominate the candidate
set) already existed; `check_vocabulary_coverage` (fact block →
vocabulary — does every fact that names a concrete identifier actually
have a derived pattern behind it) was added specifically because a
keyword-argument pattern was observed vanishing between one vocabulary
derivation and the next with zero signal anywhere in the pipeline.
`check_vocabulary_yield` fired for real, twice, on legitimate grounds: a
correctly-scoped `zrange`-family pattern accounted for 39–54% of raw
candidates across different derivations of the same guide, because
tasktiger's own test suite calls `zrange(..., withscores=True)` dozens of
times testing its Lua scripts — real domain-driven volume, not vocabulary
overmatch, confirmed by inspection before proceeding with `--force` each
time. `check_vocabulary_coverage` caught something real the day it was
built — a systematic vocabulary regression, detailed two findings below.
`check_factblock_coverage` has not yet fired in practice
in this phase — every guide ingested so far has produced a fact block
naming enough of the guide's own symbols to clear its floor. That's worth
stating plainly rather than quietly dropping: one guard in the chain is,
so far, an unexercised safeguard, not yet a proven one.

**The hedge-rate investigation: a 47% flag rate that was 72% artifact, 26%
real, and one bad narrowing fix that briefly made the real number worse
before a guard caught it.** A full tasktiger run initially flagged 66 of
140 expanded candidates (47%) as FLAG-UNCERTAIN — three times the rate
either acceptance target showed. Categorizing all 39 pre-expansion
FLAG-UNCERTAIN verdicts by hand: 28 (72%) were candidates the model itself
judged confidently irrelevant (a plain `import redis`, a `.get()` call
governed only by `decode_responses`) that got forced into
FLAG-UNCERTAIN purely by the mandatory test/mock-path floor rule, because
they lived in a test file — not because the migration made them
ambiguous. Only 10 (26%) were genuine shape-consumption ambiguity (a
`ZRANGE` call whose returned pairs might or might not be compared/indexed
downstream in a way this pipeline can't see from one line). The dominant
72% traced to one root cause: a bare, unqualified vocabulary pattern
(`.get(`, `.range(`, `.search(`) sweeping in irrelevant test-file noise
that the test-path floor then blanket-hedged regardless of relevance.
Narrowing the vocabulary — requiring a namespace or dot-anchor qualifier
instead of a bare generic verb, enforced by a new structural check in
`validate_vocabulary` — cut the same run's pre-expansion hedge count from
39 to 13 and shifted the mix to 5 (38%) artifact / 8 (62%) genuine: the
fix moved the needle in the right direction without weakening the
test/mock-path floor rule itself. The genuine 26–62% core is a real,
structural property of response-shape migrations (as opposed to rename
migrations, where the break is visible at the call site) that no amount
of prompt work removes — it needs a fundamentally different adjudication
design, not a bigger vocabulary, to close.

**That same narrowing pass caused a real regression, silently, and the
guard built the same day caught it before it shipped.** Deriving the
vocabulary three independent times from the identical redis fact block, all
three derivations missed the exact same 7 facts — not variance across
runs, a systematic blind spot. Every one of the 7 named a response
attribute or dict key (`flags`, `total`, `age-seconds`, `client-info`),
never a callable command; one derivation covered `warnings` but not the
adjacent `total` named in the same sentence of the same fact. Confirmed
coverable, not structural: an earlier, pre-narrowing vocabulary this same
session had correctly derived patterns for every one of these exact
tokens. The cause was the narrowing prompt itself — heavy new emphasis on
never emitting a bare unqualified pattern, with no parallel instruction
that attribute/dict-key facts are a distinct category needing a different,
still-non-bare anchor (the dot or the subscript, not a namespace, since
there is nothing being called). `check_vocabulary_coverage` caught this
the first day it existed, on one of its first real uses, by disagreeing
with a plausible-looking 100%/100% acceptance result rather than
confirming it. Fixed with an explicit rule requiring dot- or
subscript-anchored patterns for this fact category; re-derivation closed
6 of the 7 facts, leaving one (`LCS`'s `IDX` keyword argument, a
call-argument fact rather than an attribute/dict-key one) as a known,
understood, still-open gap outside this fix's scope.

**Real per-run costs, not estimates.** Cost reporting did not exist in the
CLI itself for part of this phase — only the test harness could report
it — so the very first live runs against tasktiger have no recorded
dollar figure at all, an honest gap rather than a reconstructed one.
Once wired into `cli.py` (printed on success and on a guard/error stop
alike, since those calls are billed regardless of outcome): Target A
acceptance, $0.1639; Target B acceptance, $0.2046; a full tasktiger run
(fact block + vocabulary + one adjudication chunk of 37 candidates),
$0.5603. A side investigation into vocabulary-derivation variance — three
independent derivations from one fact block, to measure run-to-run
stability — cost $0.5541 for the three vocabulary-only calls alone,
roughly $0.18 each; that number matters beyond this one experiment,
because it's what a future union-of-N derivation strategy would cost per
extra sample, and — per the systematic-regression finding just above — it
would have bought nothing against the 7-fact gap while only helping with
genuinely stochastic ones.

## 9. Fix generation joins the CLI

Section 8 covered detection reaching the packaged tool. This section
covers the other half `DESIGN.md` deferred: a sixth pipeline stage,
`apidrift/stages/fixgen.py`, that takes detection's confirmed sites and
either proposes an exact one-line fix or declines and flags the site for a
human — plus the mechanical checks meant to back that decision, and what a
real, independently-built answer key found wrong with the first version.

**The stage.** Chunked LLM calls, the same idempotent-per-chunk-file design
`adjudicate.py` already used (one validated file per chunk, so a partial
failure costs only the chunks that failed), consuming detection's
`proposed_sites` — never `flag_uncertain`, since nothing has confirmed
those yet. The output contract is a two-bucket analogue of adjudication's
three-bucket one, `fixes` / `flagged_for_human`, hard-failed on a missing
key exactly like every other artifact this pipeline produces
(`validate.validate_fixgen_dict`). `fixgen_system.md` states the same
boundary `DESIGN.md` §4 specifies in prose — a **mechanical rename**
(import path moved, identifier renamed, field case changed) gets a
confident single-line **fix**; a **structural refactor** (no drop-in
replacement at that exact spot, a fix that would touch more than one line,
a genuine judgment call the facts don't settle) gets **flagged for a
human**, not a guess — and tells the model explicitly that a confident
wrong fix is worse than an honest hedge.

**Verification, stated as honestly as `DESIGN.md` states the target: two
of the three tiers it specifies, not three.** Tier 1 (`apidrift/verify.py`,
always runs, no dependency) applies every fix for a file together and
`ast.parse()`s the result, and separately confirms each fix's claimed
`original_line` actually matches the real source at that file:line — a
guard against a hallucinated target line, not just a broken replacement.
Tier 2 (best-effort, on by default, `--no-verify-install` to skip)
pip-installs the migration's target package into an isolated venv under
`--workdir` and execs every import-shaped `proposed_line` against it,
confirming the named symbol resolves to a real class in the real installed
package — this is `DESIGN.md`'s "real install, default tier," and it
degrades to `available: False` with the reason recorded on any failure (no
network, no matching version, an unbuildable extension) rather than
crashing the run or being silently presented with tier-2 confidence when
it didn't actually run. **`DESIGN.md`'s tier 3 — running the repo's own
test suite before and after each fix and comparing the failing-test set —
is not implemented.** That's the tier that actually caught something in
the original study: the entangled host's `session_group.py:38` case, two
structurally different, mutually exclusive edits that both parsed, both
resolved their imports, and both passed the suite, distinguishable only by
running the tests (§6). Its absence here means the CLI's fix-generation
stage verifies less than the study that validated the same design did —
a real, current gap, not a hypothetical one, and it is the direct reason
the "zero wrong fixes" numbers below need the qualification given after
them, not just the headline.

**Acceptance results, both targets, before and after one prompt fix.**
`test_acceptance_fixgen_targetb.py` and `test_acceptance_fixgen_targeta.py`
run the full pipeline for real (detection, then fix generation) and score
every fix the model actually returned against a hand-derived answer key,
using the same categories the original fix-generation experiment used
(§4, `rule_test/fix_generation_experiment/report.md`) — exact-match,
semantic-equivalent-but-different, and what that report called "locally-
plausible-but-globally-wrong": a confident fix that doesn't match the
answer key, the failure mode that would actually ship a bug, as opposed to
an avoidable hedge that only costs a reviewer a look. Target B's answer key
(`fix_ground_truth.md`) is the one the original fix-generation study built.
Target A had none — `fix_ground_truth_targetA.md` was derived for this
work by a fresh, walled-off agent given only the real OpenAI migration
guide and read access to the four repos, no access to `apidrift/` or the
fixgen prompt being graded, the same isolated-construction discipline this
project applies to anything that would otherwise grade a detector against
its own construction.

| Host | exact-match | semantic-equivalent | avoidable-hedge | locally-plausible-but-globally-wrong |
|---|---|---|---|---|
| targetB_small, 20 sites (both runs) | 20/20 | 0 | 0 | 0 |
| targetA_small, 13 sites — before the fix | 2/13 | 0 | 11/13 | 0 |
| targetA_small, 13 sites — after the fix | 12/13 | 0 | 1/13 | 0 |

(Landing on a clean targetB_small run took three real attempts — the first
two hit detection-stage vocabulary variance already documented in §8,
missing the `test_jmeter_server.py` name-impersonation trap site once and
re-tripping the `class FastMCP:` local-class trap once, neither a
fix-generation problem. Their cost went unlogged by a test-ordering bug,
fixed the same session so a failing run can no longer lose its cost
report.)

**The over-decline is the finding here, not a footnote — an
independently-built answer key caught a limitation the tool could not see
in itself, and that is exactly what made the fix precise instead of a
guess.** Target A's first real run hedged 11 of 13 sites. Reading the
actual output: the model, asked to migrate a module-level
`openai.api_key = ...` assignment and its paired `openai.ChatCompletion
.create(...)` call site into a client object, assumed doing so required
adding a new `from openai import OpenAI` line — and, having assumed that,
correctly (given its own false premise) concluded the fix wasn't
self-contained to the one line it was given, and declined. It never
considered the alternative the answer key actually uses: every one of
these files already has a bare `import openai`, so `openai.OpenAI(...)`,
fully qualified through the module already in scope, reaches the same
class on the same one line with no new import at all. Nothing in the
pipeline's own output — no validator, no guard, no verification tier —
flagged this; a confident, well-reasoned hedge looks the same on disk as a
correct one. Only grading against an answer key built independently, by an
agent that never saw the fixgen prompt or code, surfaced that the hedges
were avoidable. The fix was one instruction block in `fixgen_system.md`:
check what's already imported (including another confirmed site's own
context, when several share a file in the same batch) before declining for
"needs an import"; reaching a symbol through an already-imported module,
fully qualified, counts as self-contained; adding an actual new import
line still disqualifies a fix, exactly as before. Re-run for real after
the change: targetA_small's exact-match rate went from 2/13 to 12/13 with
zero new wrong fixes, and targetB_small's 20/20 was unchanged, confirming
the mechanical-rename boundary the fix was scoped not to touch actually
held. The one remaining hedge (`franalgaba_chatgpt-telegram-bot-serverless
/app.py:41`) is the answer key's own hardest site, flagged in its own notes
as a genuine wrinkle: no client-construction site exists anywhere in that
file to qualify through, so declining there is a legitimate hedge, not a
miss.

**Zero wrong fixes across all 33 known sites, both targets, both before
and after the fix, is reassuring — and is not proof the verification tiers
are strong enough to have caught a real error on their own.** Tier 2 (real
install) only had signal on import-shaped `proposed_line`s: 9 of Target
B's 20 fixes, 0 of Target A's 13 — none of Target A's confirmed sites are
themselves import statements; they're client constructions, call-site
migrations, and exception-name renames, shapes tier 2 as built cannot
check at all. That means 24 of the 33 fixes scored across both targets
were verified at tier 1 only: the file still parses, and the line the
model claims it started from matches real source. Neither check inspects
whether the *content* of the replacement is actually correct — tier 1
would pass a confident, well-formed, wrong rename exactly as readily as a
right one. The requested cross-check — a site where verification passed
but the fix disagreed with the answer key — found nothing to flag in
either run, but with 24 of 33 fixes never reaching a tier that checks
content at all, that absence is a property of this run, not a property
established about the verification tiers in general. This is exactly the
gap `DESIGN.md`'s tier 3 (real test-suite diffing) exists to close, and
it remains the honest reading of these results: the headline number is
clean, the verification behind it is real but partial, and dropping the
test-suite tier is a known, named risk, not a solved problem.

## 10. Findings against a real, unmodified guide

Everything through §9 ran against guides this project had already shaped
itself around — official, well-formed, and (for Target B) the same
686-word condensed spec the acceptance tests and cassettes are pinned to.
The first run against a guide nobody had touched — the real, published
MCP Python SDK v1→v2 migration guide, 23,000 words, 116 top-level `##`
sections, 819 facts once derived — found problems none of the prior work
could have, because none of it had ever pointed the packaged tool at a
guide this large or this real. (Fact count is a property of how a guide
was derived, not of the guide itself — see §10's redis equivalence check
below, which yielded 68 facts derived whole and 84 derived in 6 chunks
from identical content, with no fact present in one and absent from the
other.)

**Stage 1 could not complete in one call, and raising max_tokens was the
wrong fix twice before it was the right diagnosis.** The first run
truncated at the default max_tokens=8000; raising it to 32000 truncated
again. Both were real, paid derivations that produced nothing usable.
The actual problem wasn't the ceiling — it was that a 23,000-word guide
asks for a fact block sized for a document that big in a single call, and
that fact block is itself input to every downstream call (vocabulary
derivation, every adjudication chunk), so pushing the ceiling higher
again would have made every one of those calls more expensive on every
repo, not just fixed stage 1. Stage 1 now chunks by guide section instead
— split on `##` headings, never mid-section, an oversized section
subdivided on its own `###` subheadings — mirroring the chunked,
idempotent-per-chunk-file design `adjudicate.py` already used for
adjudication.

**Raising max_tokens to 32000 crossed a different ceiling than the one
being aimed at.** The Anthropic API refuses non-streaming requests that
could run past ten minutes, and 32000 output tokens crossed that
threshold — the failure surfaced as `Streaming is required for
operations that may take longer than 10 minutes`, not as another
truncation. The fix was moving every completion call onto the streaming
API and reading the accumulated final message, which introduced a
genuinely new failure path that didn't exist before: a connection can now
drop *during* the body read, after tokens (and billing) have already
happened, distinct from a connection ever being established at all.

**The vocabulary-coverage guard's substring bug (fixed this session,
above) degrades exactly where it matters most.** It isn't a fixed-severity
bug — its blind spot scales with how central the package name is to the
vocabulary's own naming. A short, common package name like `mcp` shows up
as a substring inside a large fraction of a real vocabulary's own pattern
identifiers (`fastmcp`, `mcpserver`, `mcperror`, ...), so the guard's
false-COVERED rate is worst on exactly the packages a migration tool
spends the most time on. A guide for a package with a long, distinctive
name would have shown this bug far less, which is part of why it survived
until a real, large, `mcp`-named guide exercised it. `_pattern_tokens`
(the function underneath this guard) has since had a third bug found in
it the same way this one was — by inspecting real output on this same
819-fact block, not by reasoning about the code in the abstract: escape
fusion. `re.split` on non-alphanumeric runs let a regex escape's own
letter glue onto the identifier sitting next to it (`\bMcpError\b`
tokenized to `bmcperror`, never `mcperror`), silently suppressing
coverage for any `\b`-anchored pattern regardless of vocabulary quality —
57 of the real vocabulary's 115 patterns were affected, 34 of them losing
every real token. All three bugs found in this function (a lowercasing
mismatch, this substring bug, then escape fusion) share the same
direction of error — each made coverage look worse than it actually was,
never better — but each still had to be found by inspecting real numbers,
not by review; none was caught by an example test until it had already
shipped. With both the substring and escape-fusion bugs fixed, the same
819-fact block measures 323 covered, 356 partial, 58 uncovered, 35
non-breaking, 47 no-identifier — 414 facts flag a genuine gap, down from
the substring-fix-only figure this section originally reported before the
escape-fusion bug was found. `_pattern_tokens` is now covered by
property-based tests over generated regexes (an embedded identifier must
survive any surrounding regex syntax; tokenization must be invariant to
`\b` anchoring; no token may contain a character that came from regex
syntax rather than the pattern's own text) instead of another set of
hand-picked cases, precisely because hand-picked cases missed this bug
three times.

**Insufficient fix set — `tonyzorin/youtrack-mcp`.** All three sites this
migration touched in this repo were found, and each individual fix was
correct in isolation. But the repo's `MCPServer(...)` construction call
passes `host=` and `port=` as keyword arguments, and v2 moves both off
the constructor entirely — applying only the three independently-correct
renames produces code that imports cleanly and then raises `TypeError` at
construction, which is worse than not migrating the repo at all: the
break moved from an import-time signal a developer would catch
immediately to a runtime one. The mechanism is structural, not a one-off
model mistake: this pipeline generates fixes line by line, and a
single-line fix to the *opening* line of a multi-line call satisfies
fixgen's own "self-contained" test for a mechanical rename while leaving
the rest of that same call broken — the boundary that correctly
distinguishes a mechanical rename from a structural refactor for a single
line doesn't see across the whole call it's a part of. The correct
verdict for this site was FLAG-FOR-HUMAN, not three separate FIXes. Tier
1 (parse + line-match) and tier 2 (real install) verification both passed
every one of the three fixes, because both check whether each fix is
internally self-consistent, never whether the *set* of fixes touching one
call site is jointly sufficient — a gap neither tier is built to see.
This was caught by hand, reading the diff, not by the tool.

**The first merged PR, and what the maintainer's correction revealed.**
`tonyzorin/youtrack-mcp#41`, opened against the repo above, was merged by
the maintainer on 2026-08-26 — the first of three opened PRs to get a
response (`m0xai/trello-mcp-server#29`, opened 2026-08-19, and
`RafaelCartenet/mcp-databricks-server#11`, opened 2026-08-26, remain open
with zero comments; three PRs is too small a sample to support any claim
about maintainer receptivity in either direction). The PR's description
stated three parts with distinct provenance: two mechanical renames
generated end-to-end from the published guide (the import path, the
`create_server` return annotation); a dependency floor bump to
`mcp>=2.0.0,<3`, added after CodeRabbit's automated review flagged the
unbounded `mcp>=1.11.0` pin; and one hand-written change — moving
`host`/`port` off the `MCPServer` constructor to `run()` — covering the
exact site the multi-line span guard above had flagged instead of fixing.
The maintainer confirmed the first two parts as correct and corrected the
third on merge: the hand-written fix guarded `host`/`port` on the `sse`
transport only, but v2 also changed the default HTTP bind address to
`127.0.0.1`, so the `streamable-http` path needed the same guard — without
it, a container would listen on localhost inside itself and be unreachable
from Docker Compose. That fact follows from how the project is deployed,
not from the migration guide, and was not among the facts the tool (or the
human who wrote the hand-fix) had surfaced. This inverts the failure mode
recorded earlier from the same repo: there, the tool's individually-correct
fixes were collectively insufficient, and a human caught it; here, the
tool's mechanical output was correct and the human-judgment portion — the
part the span guard had deliberately declined to automate — was the part
that was wrong. Both failures are real; neither the tool nor the human is
reliably the safer half. The span guard behaved correctly in both cases —
it declined to fix a site it could not safely judge, which is what put a
human in the loop rather than a wrong automatic fix.

**Model refusal — `securityfortech/secops-mcp`.** Fix generation stopped
outright with `stop_reason=refusal`, reproducibly, on a repo that wraps
offensive-security tooling. The migration itself is a mechanical class
rename with nothing sensitive about it; the refusal appears to be tripped
by the surrounding code context fixgen sends along with the site (the
repo's own subject matter), not by anything about the task asked of the
model. This is a failure mode specific to an LLM-based tool: it can be
refused service based on what the target repository *is*, independent of
whether the migration being performed is itself benign, and it's
deterministic — the same site refuses every time, so no retry strategy
recovers it. A purely deterministic tool (grep and a hand-written fixer)
would have no equivalent failure mode here at all.

**Cost shape doesn't track how much of the migration a repo actually
uses.** `youtrack-mcp`'s entire exposure to this migration was one import
line, but fact-block and vocabulary derivation still ran the full cost of
covering everything the guide describes — OAuth flows, client
construction, the low-level `Server` class, transports — because those
stages depend only on the guide, not on the repo. Adjudication cost, by
contrast, scales with guide size × repo size: the 819-fact block (a
225KB `factblock.json`, a figure that describes this particular
derivation rather than a fixed property of the guide — see the caveat in
§10 above) is input to every adjudication chunk regardless of how many
candidates that chunk actually contains. Separately,
prompt-cache accounting across three runs against this guide wrote
144,795 tokens to the cache on *every* run and read zero back — the
cache-write premium was paid three separate times for zero read-side
benefit any of those times. The cause hasn't been investigated yet; noted
here rather than quietly ignored.

**Stage 1's chunking has no defense against an unstructured guide.**
`factblock.plan_chunks()` splits only on `##`/`###` Markdown headings —
a guide with none is returned as a single whole-guide chunk
unconditionally, regardless of `--factblock-chunk-size`; the budget only
subdivides an oversized *section*, it never subdivides a guide that has
no sections to begin with. Both the Target A and Target B guides have
zero `##` headings, which is why neither one ever exercised the
multi-chunk merge / global-renumbering / duplicate-fact-flagging /
package_name-consensus path this stage was built for — every acceptance
and replay test that used either guide only ever ran stage 1 as a single
chunk. A large real guide with no heading structure at all would
therefore still hit the same max_tokens truncation stage 1 was chunked
to avoid, with no remedy available at the CLI. Coverage of the
multi-chunk path was added separately using `rule_test/
factblock_experiment/guide_redis_unified_responses.md` (6 real `##`
sections, already in the repo) — a chunked (6-call) and a single-chunk
(headings stripped, 1-call) derivation of that same guide content were
compared fact-by-fact, cross-checked against its
`ground_truth_factblock.md`, and found equivalent: every table row and
scope statement in one derivation had a matching counterpart in the
other. The two runs differ only in how finely they group facts (84 vs.
68, e.g. one combined "response mode matrix" fact vs. seven granular
ones) — no fact present in one was absent from the other. No
chunk-boundary fact loss on this guide.

**Not every real-guide result was a new failure mode.** `QAInsights/
jmeter-mcp-server` produced seven correct fixes across two separate entry
points, including one genuine test-mock edge case handled right: a
mock's *exposed* attribute name needed renaming while the local stub
class's own identifier correctly did not change — the same
name-impersonation-vs-real-reference distinction `DESIGN.md`'s Rule 1 and
the original study's ground-truth correction (§3) both turn on, holding
up again on a guide and a repo neither had been built around.

**The Target A/B benchmark repos cannot measure a large class of
detection improvement, and this was not visible until tested directly.**
269 of the 320 searchable-but-uncovered identifier spans in the real MCP
v1→v2 vocabulary are real, guide-stated API surface — `ClientSession`,
`RootModel`, `TypeAliasType`, `ErrorData`, OAuth grant-type constants,
and more — that stage 2 never wrote a pattern for: zero token overlap
with any of the 115 derived patterns, not near-misses. That's a
detection ceiling, not a precision problem — grep cannot generate a
candidate for an identifier no pattern covers, regardless of what
downstream filtering or adjudication does with what grep finds.
Grepping all five Target B repos, plus two later ones run against the
same guide (`bangumi-analysis`, `databricks-analysis`), for the top-40
uncovered spans found exactly one genuine occurrence:
`danilop/MCP2Lambda`, one file, `ClientSession` construction and
`.initialize()`. Everything OAuth-shaped (`client_credentials`,
`client_secret_basic`, `private_key_jwt`, ...) and everything
protocol-internals-shaped (`RequestId`, `RequestT`, `lifespan_context`,
`related_request_id`, ...) is absent from all seven repos, production
and test code alike. The reason is architectural, not coincidental: all
seven repos are the same shape — a thin FastMCP server wrapping one
external API. The missing facts describe client-side surface: session
construction, capability negotiation, request-context internals, OAuth
grant types — none of which has any reason to appear in code whose job
is to be a server rather than drive one. This means the 100%/100%
figures reported for Target A/B (§5) characterize performance on thin
server wrappers specifically, not on the migration as a whole, and
should be read with that scope attached.

**Coverage overstates the detection gap — `cisco-ai-defense/mcp-scanner`.**
The first fixture that exercises client-side surface: a real MCP client,
not another thin FastMCP server. The OAuth sites the coverage guard
reports as gaps are found anyway — `auth.py:30` (`OAuthClientProvider`)
and `auth.py:31` (`OAuthClientInformationFull`) both surface as
candidates, 84 candidates total across `p81_oauthprov`/`p84_authcode`/
`p85_authmeta`/`p86_authfields`. Coverage is computed fact-side: a fact
can register "partial" because some of its backtick-quoted spans are
unsearchable spec literals, even while the code site it describes is
still reached by a different pattern covering a different span from the
same fact. The 269-fact gap counted earlier in this section therefore
overstates the detection gap — an upper bound on what stage 2 might be
missing, not a count of missed sites.

**One confirmed detection miss, in production code.** `ClientSession`
produces zero candidates out of 815 on this same repo, despite three
production sites in `mcpscanner/core/scanner.py` — a type annotation at
line 1382, and constructions at lines 1536 and 1864. 22 facts reference
`ClientSession`; no derived pattern covers it. This is the first
measured instance of the stage-2 gap costing real detection rather than
only a coverage-metric count.

**The model refusal above (`securityfortech/secops-mcp`) reproduced on a
second, independent security repo.** `mcp-scanner` is defensive tooling
— Cisco AI Defense's scanner for MCP server misconfiguration — and
adjudication returned `stop_reason=refusal` again. The repo vendors a
corpus of deliberately malicious MCP servers as scan fixtures, which
makes the refusal explicable, but two refusals on two unrelated repos
whose only shared property is "security tooling" confirms the failure
mode is domain-driven, not a one-off.

**Gap-fill result, measured — the pre-registered test passes.** The
finding above stated a specific, checkable prediction: `ClientSession`
produces zero candidates out of 815 despite three production sites in
`mcpscanner/core/scanner.py`. After one gap-fill pass against this same
guide and vocabulary, all three appear — lines 1382, 1536, 1864 — plus
the import at line 34, none of which grep could reach before. Over the
run's 323 target facts, the three-bucket split was 206 patterns, 124
explicit declines, 0 unresolved. The decline channel was the actual
point of the design, not a side effect of it: before it existed, "the
model chose not to write a pattern" and "the model never got to this
fact at all" were indistinguishable, which is exactly how 269 real gaps
sat silent in the original diagnostic.

**Cost ran above estimate, and prompt caching paid for itself for the
first time on this project.** $3.03 across 11 chunks, against a
pre-call estimate of $1.20–$1.60 — the gap was output volume, not input:
74,934 output tokens, well past what the estimate (input-token-only, by
design — see gapfill.py's `estimate_cost_report`) could see coming.
`cache_read` hit 852,490 tokens on this run, the first time cache reads
actually registered anywhere in this project's cost reporting (§10
above records three prior runs against this same guide writing
144,795 tokens to the cache and reading zero back). Rough accounting:
the same run without a cache to read from would have priced the shared
system-prompt prefix at full input rate on each of the 11 chunks instead
of once, on the order of triple the actual cost.

**Two problems the run exposed, both about redundancy chunking
introduces rather than about coverage.** First: chunks are derived
independently, with no visibility into what an earlier chunk already
wrote, so the same symbol can get patterned more than once — six
separate patterns exist for `ClientSession` alone (`gf_clientsess` plus
three suffixed variants, `gf_clisess` plus one). Merge only renames a
colliding id (see gapfill.py's `_merge_patterns`); it was never designed
to notice that two differently-named patterns match the same thing, so
none of the six collapsed. Second, and downstream of the first:
candidates went from 815 to 2,795, with 908 collapsed as duplicates
during prefilter versus 118 in the pre-gap-fill baseline — the same
lines are being matched repeatedly by redundant patterns rather than
once each. Prefilter's stage C absorbs the duplication before
adjudication sees it, so detection output isn't wrong, but adjudication
cost scales with candidate count, and this run paid for matching
`ClientSession` six times over instead of once.

**The two anti-Goodhart checks' track record, including the run that
finally succeeded.** Across four consecutive `chunk_000` responses, both
checks hard-failed on valid output — $2.88 spent before either was
downgraded to a warning (§10 above documents each case: `|`-counting,
symbol-counting on a two-symbol pattern, a dotted path with a spelling
variant). On the merged output that eventually produced the 206/124/0
split above, both checks — now warnings, still computed, still
reported — flagged nothing. Four hard-fails, zero warnings, on a run
whose actual defects (six redundant `ClientSession` patterns) were
exactly the kind of thing an anti-Goodhart check might have caught and
didn't, because duplication across chunks was never what either check
looked for. The distinction that held up: the checks on this project
that have earned a permanent place test a fact about an artifact
(a regex compiles, a fact block is non-empty, a candidate has a
verdict); these two tried to infer intent from naming and grouping, and
were wrong every time they fired.

**Correction to the finding above: dedup proves the redundancy
explanation for the candidate jump was wrong.** Deduplicating the 206
merged patterns collapsed 23 of them across 16 redundant groups — and
candidate count did not move, 2,795 before and 2,795 after. Stated
plainly, this had to be true: merging `(?:a)|(?:b)` preserves the full
union both members already matched, so dedup can only shrink pattern
count and prompt size, never candidate volume. "Redundant patterns are
matching the same lines repeatedly," the explanation the previous entry
gave for 815 → 2,795, does not survive contact with this test. Something
else produces that volume, and deduplication never touches it.

**Where the 2,795 candidates actually come from: four patterns, not
chunking redundancy.** Per-pattern counts from the real run's
`candidates.json`: `gf_tpdecor` 745 (26.7% of all candidates),
`gf_uristrlit` 489 (17.5%), `gf_mcpenv` 355 (12.7%), `gf_textmime` 77
(2.8%) — 1,666 candidates, 60% of the run's total, from four patterns.
The comparison point: `p1_fastmcp`, the largest pre-existing (stage-2)
pattern, produces 423, every one a real `FastMCP` usage. All four
gap-fill patterns match a content SHAPE rather than a migration-relevant
symbol — by the run author's own inspection: `gf_uristrlit` matches any
`https://` string literal, including `BEACON_URL =
"https://attacker.com/beacon"` in the vendored eval corpus this scanner
ships as test fixtures; `gf_mcpenv` matches any `MCP_*`-shaped
environment variable name, including invented ones like
`MCP_BYPASS_AUTH`; `gf_textmime` matches `"text/plain"`/
`"application/json"` wherever they appear; `gf_tpdecor` matches
`@app.tool()`, present in essentially every MCP server ever written.

**This is the Goodhart failure the anti-Goodhart checks were built to
catch, aimed at the wrong shape.** Both the symbol cap and the id check
test whether one pattern spans too many SYMBOLS. The actual cheat here
is the opposite shape: one pattern naming a single thing that appears
everywhere, satisfying the coverage checker for whichever fact it was
written against while generating candidates by the hundreds.
`check_vocabulary_yield` exists specifically to catch an overbroad
single pattern, and its own two trip conditions split cleanly on this
run: the absolute ceiling (2,795 > `max_total`=2000) is crossed, but
that alone never identifies a culprit; the single-pattern-dominance
check, which does, never fires — `gf_tpdecor`'s 745 candidates clear the
guard's floor (25) but land at 26.7% of the pool, under its 35% share
threshold, and the other three overbroad patterns dilute the same
denominator further, each individually staying under the line while
collectively accounting for most of the run's volume. This is exactly
the failure mode `check_vocabulary_yield`'s own docstring names for a
different run (`max_single_pattern_floor`/`share` "sized to the study's
diluted-host worst case... a floor that high means the guard can never
fire no matter how lopsided the vocabulary is") arriving in practice
rather than in the abstract, on a pool inflated by gap-fill's own output
volume rather than a diluted host.

**The one-pass gap-fill result is two-sided, and the earlier entry
recorded only the positive half.** It found the confirmed missing
symbol — `ClientSession` went from zero candidates to all three
production sites plus the import. It also introduced four patterns
that, on this candidate breakdown, would roughly triple adjudication
cost (1,666 of 2,795 candidates, against a pre-gap-fill baseline of 118
total) while contributing nothing migration-relevant. Both are true of
the same run, and the entry recording only the first is incomplete.

**Fixed `check_vocabulary_yield`'s dominance check, offline, against the
recorded run-scanner-dedup artifacts above.** Replaced the fixed
share-of-total threshold (0.35) with a fair-share multiple: a pattern's
share of candidates, multiplied by the number of patterns that actually
fired. Fixed share had a diluted-denominator hole — as more patterns
fire, each one's share of the same total shrinks even when its absolute
overmatch doesn't, so a run with several simultaneously-overbroad
patterns can dilute all of them under the line at once. Multiplying by
`n_firing` undoes exactly that dilution: `gf_tooldecor`'s 26.7% of 2,795
candidates across 70 firing patterns becomes 18.7x fair share, not a
diluted 27%.

**Verified on real data, not reasoned in the abstract.** Precise
fair-share multiples, run-scanner-dedup (2,795 candidates, 70 firing
patterns): `gf_tooldecor` 745 candidates, 18.7x; `gf_uristrlit` 506,
12.7x; `p1_fastmcp` 423, 10.6x; `gf_mcpenv` 344, 8.6x; `gf_textmime` 76,
1.9x. `max_fair_share_multiple=12` sits in the only valid window
(10.6, 12.7] — flags the two gap-fill patterns above `p1_fastmcp`,
spares `p1_fastmcp` itself. Confirmed silent on `run-youtrack-v2` (top
multiple 4.7x, 8 firing patterns) and `run-jmeter` (top multiple 1.9x,
6 firing patterns).

**The measure cannot separate `gf_mcpenv`/`gf_textmime` from
`p1_fastmcp`, and no volume-based measure can.** Both have fewer
candidates than `p1_fastmcp` (344 and 76, against 423) in the same run,
on every volume-derived scalar — share, this multiple, ratio-to-median,
raw count. Flagging a 344-or-76-candidate pattern without also flagging
a 423-candidate one in the same run isn't a threshold, it's a
contradiction: any measure that's a monotonic function of candidate
count preserves that ordering. This holds for all three measures this
task set out to compare (ratio-to-median, ratio-to-fair-share,
absolute-count-with-lower-share) — they're all directly proportional to
raw count within one run, so they rank patterns identically and differ
only in what constant they divide by. Separating a shape-matching
pattern (`gf_mcpenv`: any `MCP_*`-shaped env var name; `gf_textmime`:
`"text/plain"`/`"application/json"` anywhere) from a genuinely dominant
symbol match (`p1_fastmcp`: real `FastMCP` usages) needs a signal this
guard doesn't have — e.g. whether the pattern's regex is anchored to a
specific symbol or built from an open wildcard/alternation over a class
of literals. Not built; flagging this rather than tuning the threshold
until it looked solved.

**Bonus finding: the old check was already misfiring in production.**
`run-youtrack-adjudicate.log` shows the guard had already flagged
`p64_modeldump` on `run-youtrack-v2` — 76/130 candidates, 58% share —
and required a `--force` bypass to proceed. `p64_modeldump` matches
`.model_dump()`/`.model_validate()`, real pydantic call sites central to
that migration guide; every one of its 76 candidates is legitimate. The
old fixed-share check couldn't tell a genuinely common symbol in a
small vocabulary (8 firing patterns) from an overbroad one, because a
correct pattern can legitimately cover the majority of a small
vocabulary's hits. The fair-share multiple fixes this too, incidentally:
`p64_modeldump`'s multiple is 4.7x, safely under the new 12x line, so
this run no longer needs `--force` for a false alarm.

228 offline tests pass (3 new, 1 rewritten to reflect the new measure's
semantics — the old test asserted dominance on a 2-pattern vocabulary,
where fair-share multiple is mathematically capped at `n_firing`=2 and
can never reach a threshold calibrated for the 70-pattern regime this
fix targets). 4 unrelated failures in `test_prompt_cache.py`
(`ModuleNotFoundError: anthropic`, confirmed pre-existing via `git
stash`) are an environment gap, not a regression.

**Added a structural check on pattern shape -- `check_pattern_shape` --
to catch the half `check_vocabulary_yield` provably cannot.** Runs on
the vocabulary alone, no candidates, no grep: it parses each pattern's
regex source (via `re`'s own AST, `re._parser`/`sre_parse`) and asks
whether some alternative branch can match with almost no
pattern-specific literal text, padded out by an open span -- a
quantified character class or `\w`/`.` repeated more than a couple of
times (`[A-Z_]*`, `[^"']*`, `.+`; deliberately not `\s*`, which is
formatting flexibility, and not a small bounded repeat like `{1,3}`) --
that absorbs whatever content is actually there instead of naming a
specific symbol.

**Worked the rule from the real regexes, not from the English
description of the four bad ones.** `gf_uristrlit`
(`["'][A-Za-z][A-Za-z0-9+.\-]{1,30}://[^"'\n]*["']`) requires 3 literal
characters (`://`) with open spans on both sides -- it names a string
*shape*, not a symbol. `gf_mcpenv`'s `MCP_[A-Z][A-Z_]*` requires 4
(`MCP_`) before an open suffix. `gf_textmime`'s `text/[^"'\n]*` requires
5 (`text/`). `gf_tooldecor`'s `@\s*\w+\.(?:tool|prompt)\s*\(` requires 6
(`@`+`tool`+`(`) -- the open span is on the receiver, not the method
name, and it's one character under the floor `check_vocabulary_yield`
uses in its own docstring (25/0.35) but the *right* number for this
check turned out to be a different floor entirely, on a different
scale, derived from a different set of comparisons. Held against the
comparisons the task named: `p1_fastmcp` (`\b(FastMCP|FastMCPError)\b`)
requires 7 literal characters and has zero open spans anywhere.
`p84_authcode` similarly. `p7_removedtyp` is a 24-way alternation where
one branch (`TASK_STATUS_\w+`) does have an open span, but its own
literal anchor is 12 characters -- this check evaluates every branch of
an alternation independently (not one representative path), so a
pattern combining a short-open branch with a longer-open one is judged
on its worst branch, not let off by a safer one.

**`min_literal_anchor=8` is the tightest integer the real vocabulary
supports.** `gf_tooldecor`/`gf_tooldec` sit at 7 literal characters and
must be caught; `p99_srvctor`
(`\bServer\s*\(\s*["'][^"']*["']\s*,`) sits at exactly 8 and is spared
-- it's a plausible instance of the same failure shape (any `Server(...)`
constructor call, string argument unconstrained) but it never actually
fired on this run (0 candidates), so there's no real match to check the
threshold against, and it's left alone rather than guessed at.

**Verified on all three recorded runs' full vocabularies, not just the
four patterns named.** run-scanner-dedup (298 patterns, the merged
post-gap-fill vocabulary): flags exactly the four known-bad patterns,
plus four more in the same gap-fill family never separately measured --
`gf_charset` (any string/dict-key containing "charset" -- fires on a
`{"charset": charset}` response payload in an unrelated eval fixture),
`gf_strurl` (`str(...)` on any variable merely named like a URI --
fires on `str(resource_uri)`), `gf_tasktypes` (any capitalized `Task*`
identifier -- fires on anyio's own `TaskGroup`, nothing to do with this
guide), `gf_traversal` (path-traversal string shapes -- fires correctly
on this run's own adversarial eval fixtures, i.e. exactly where it
should). Zero of the other 289 patterns flagged, including all 114
non-gap-fill ones. run-youtrack-v2 and run-jmeter (115 patterns each,
no gap-fill): zero false positives on either.

**Wired into the pipeline before grep, not after.**
`check_vocabulary_yield` can only see the problem once grep has already
paid for it (2,795 candidates against a normal run's tens-to-hundreds).
`check_pattern_shape` runs right after `check_vocabulary_coverage`, on
the vocabulary alone -- a bad pattern now stops the run (or prints under
`--force`) before a single grep pass, and `pattern_shape.txt` is written
to the workdir alongside `vocabulary_coverage.txt`.

235 offline tests pass (7 new). Note on test counts: yesterday's entry
reported 228 passed / 4 failed under a bare `python3` missing the
`anthropic` package; run through this repo's own `.venv` (which has it
installed) the same suite is 235/0 -- the 4 `test_prompt_cache.py`
failures were an interpreter-selection mistake on my part, not a real
gap. Using `.venv/bin/python3` from here on.

**Built the coupling-group increment scoped in the previous design
pass, against the real failure it targets, not a synthetic one.** The
unsolved problem: one migration fact requiring coordinated edits at
several sites, where fixing any one alone leaves the code broken --
the `tonyzorin/youtrack-mcp` insufficient-fix-set failure, reproduced
on `run-azeroth` (`azerothmcp`): `main.py:68`'s `FastMCP(...)`
constructor carries `host=`/`port=`; `main.py:153`/`170` need those
values once the constructor stops accepting them. Adjudication already
names the connection in prose -- `main.py:153`'s real, recorded reason
is *"depends on what was passed to the `FastMCP(` constructor at line
68, which is not visible here"* -- and `pipeline.py` discarded it:
`flag_uncertain` never reached fixgen.

**Grounded the design in real adjudication output, not assumption.**
`related_sites` was added to both `proposed_sites` and `flag_uncertain`
(`apidrift/stages/adjudicate.py`'s `SCHEMA`, `apidrift/validate.py`'s
`RELATED_SITES_BUCKETS`), populated by the adjudication prompt from
reasoning it already produces. Fact-citation (the existing `pattern`
field) was deliberately *not* used for grouping -- confirmed on real
data, not just reasoned about: on `run-azeroth`, `main.py:29` (a
self-contained import rename) shares facts 98/134 with `main.py:68`
(the constructor) despite depending on nothing from it, and the
actually-coupled `main.py:68`/`170` share zero fact numbers. The same
shape repeats on `run-youtrack-v2` (`main.py:10`/`25`/`27` all share
fact 98 despite two of the three being self-contained) -- confirming
over-grouping is not a one-off. `pattern` also proved unstable: the
structurally identical constructor site on `run-youtrack-v2` cites
fact 149 (the transport-param fact) while `run-azeroth`'s does not,
for the same code shape under the same guide.

**`apidrift/stages/fixgen.py` computes groups via union-find over
`related_sites`** (`_group_by_related_sites`), before the model sees
anything. A multi-member group where any member is uncertain, or was
already declined by the existing multi-line-span guard, is
deterministically declined in its entirety
(`_group_consistency_flag`, `flag_source: "group_consistency_guard"`)
-- zero model calls for a group that can never be resolved without
building the model-facing joint-generation path this increment
explicitly does not build. A group whose only confirmed member is
itself multi-line (the shape on both real runs) never produces its
own `group_consistency_guard` entry -- the existing
`multiline_span_guard` entry is enriched with the same `group_id`/
`group_members` instead, so the cross-reference is still visible
without a second, redundant flag for the same site. The post-response
bucket check (`fixgen.py`'s existing coverage-mismatch check) gained a
matching assertion: a group split across `fixes`/`flagged_for_human`
is a hard validation failure, checked per-chunk and again at the
merged level (a group split across chunk boundaries isn't checkable
until every chunk is in). `report.py` renders a new "Coupled edit
group" subsection under FLAG-FOR-HUMAN, naming every member (confirmed
or context-only) and stating plainly that the group must be applied,
or fixed by hand, together.

**Verified end to end against `run-azeroth`'s real stored artifacts,
zero API calls.** Loaded the real `adjudication/merged.json` and
`factblock.json`, transcribed `related_sites` directly from each
entry's own already-recorded reason text (`main.py:153`/`170` -> line
68; nothing invented), and re-ran `fixgen.run()` against the real repo
with a fake client that replays `main.py:29`'s own already-recorded
real fix verbatim -- the only site that should reach a model call at
all. Result: exactly one model call (matching today's real run),
identical fix/flag counts and content, `main.py:68`'s
`flagged_for_human` entry now carries `group_id: "main.py:68"` and
`group_members` naming all three sites, and `report.md` gains the new
"Coupled edit group" section cross-referencing `68`/`153`/`170`
explicitly -- where today a human has to read three separate prose
paragraphs and notice they share a line number. Net cost on this real
run: zero additional API spend, exactly as the design pass predicted
for the case where the group's anchor is already span-declined.

**What this does not solve, unchanged from the design pass's own
scoping.** No model-facing joint resolution was built -- a coupled
group where the anchor is single-line and NOT independently declined
(no case exists in either real run) is still handled only by the
deterministic pre-model decline, never sent to the model together.
Grouping quality is bounded by adjudication's own `related_sites`
reasoning; a coupling adjudication never states in prose still goes
undetected. Cross-file coupling is architecturally supported by the
`{file, line}` shape of `related_sites` but unevidenced -- both real
examples are single-file. A group split across `fixgen` chunk
boundaries, while now caught at the merged-validation level, is not
cleanly resumable: the individual chunks it spans each independently
pass their own necessarily-partial per-chunk checks and are written to
disk as done, so a naive re-run reaches the identical split again
without deleting those chunk files first -- fixing that needs
group-aware chunking, out of scope here.

**One real, expected regression, left as-is rather than papered
over.** `test_replay_targetb.py` now fails with `ReplayMiss` on
`adjudicate_chunk_000` -- the adjudication prompt changed (the new
`related_sites` instructions), so the recorded cassette's request hash
no longer matches. The test's own docstring states this is correct
behavior, not a bug: *"if the pipeline's own logic changes what it
asks the model... this fails with ReplayMiss, which is correct -- it
means the cassette is stale, not that the pipeline is wrong."*
Re-recording needs a real, billed acceptance-test run
(`APIDRIFT_RECORD_CASSETTE=... pytest ... -m acceptance`) and is left
for a deliberate, confirmed step rather than done here. The four
existing recorded cassettes' stored adjudication *responses* (not
requests) were mechanically patched to add `"related_sites": []` to
every historical entry -- a pure data-shape migration matching what
those runs actually claimed (no coupling), not a re-recording; this
alone did not fix the `ReplayMiss`, which is about the request hash,
not the response shape.

18 new tests in `tests/test_coupling.py` (union-find grouping,
deterministic decline for both the span-anchored and single-line-anchor
shapes, the torn-group hard failure, the `related_sites` schema
enforcement, both report-rendering shapes) plus small updates to four
existing scripted-response fixtures. 252 passed, 1 expected/documented
`ReplayMiss`, run through `.venv/bin/python3`.

**The coupling increment, measured end to end on a real, live re-run --
not a replay, not a hand-simulated `related_sites`.** Re-ran
`run-azeroth` against the same guide, same loaded factblock/vocabulary,
same repo, this time through the coupling-aware pipeline. Adjudication
populated `related_sites` on every relevant entry on its own, with no
hand-editing: `main.py:29` (the import) -> `68`; `main.py:68` (the
constructor) -> `29`, `153`, `170`; both `153` and `170` -> `68`.
Verified directly from the run's own `adjudication/merged.json`, not
taken on faith.

**The links are semantically real, not fact-citation noise recurring by
coincidence.** `main.py:68`'s real, recorded reason for linking back to
`29`: *"fixing the import alone does not repair it -- the identifier
must become `MCPServer(`."* That's correct, and sharper than it first
reads: renaming the import to `MCPServer` while line 68 still reads
`FastMCP(` leaves `FastMCP` undefined at that point in the file --
applying the import fix alone raises `NameError` at import time, not
just an incomplete migration. This is a different flavor of the
insufficient-fix-set failure than the host/port case documented above:
not "the companion site needs a value this site can't see," but "these
two identifiers must be renamed together or neither should be,"
surfacing on a plain single-line, non-multiline, otherwise entirely
ordinary confirmed site (`main.py:29`) that the multiline-span guard
alone would never have touched.

**Result: `FIX` went from 1 to 0, `FLAG-FOR-HUMAN` from 1 to 2 --
verified from the run's own `fixes.json` and `report.md`.** The one
group (`main.py:29`) now names all four sites: `29` declined directly
(`group_consistency_guard`), `68` declined by the (unchanged)
multi-line-span guard and cross-referenced into the same group, `153`
and `170` shown as uncertain context. This is the correct outcome, not
a regression: the previous run's single fix -- the import rename alone
-- would, applied by itself, have broken the repository at import time.
The same insufficient-fix-set failure `REPORT.md` already recorded for
`tonyzorin/youtrack-mcp`, reproduced on a second, independent repo, and
this time caught by the pipeline before any output existed to review,
rather than found by hand after the fact.

**Cost: one adjudication call, $0.40. The group decline itself made
zero model calls.** Confirmed from the run's own `fixgen/` directory:
no `chunk_*.json` files exist, only `merged.json` -- the deterministic
pre-model pass left nothing confident and undeclined to send, so
`fixgen.run()`'s chunk loop never fired at all. Every dollar spent on
this run bought the adjudication call that populated `related_sites`;
grouping and decline were free, exactly as designed.

**The increment's real scope, stated as plainly as when it shipped:**
this result works because both real coupled anchors on this run --
`main.py:68`'s constructor, and now transitively `main.py:29`'s import
-- resolve to a group containing a site the multi-line-span guard (or,
for `29`, the group-consistency guard itself) already declines by other
means. A coupled group whose only members are single-line, independently
confident, and never separately declined would still be sent to the
model as ordinary, ungrouped sites -- the model-facing joint-resolution
path was deliberately not built in this increment, and still isn't,
because no run's evidence -- including this one -- has yet produced
that shape.

**The model-facing joint-resolution path named above as not-yet-built is
now built: block-level fixes, joint group resolution, and a deterministic
value-flow guard.** A fix is no longer restricted to a single line --
`end_line`/`original_lines`/`proposed_lines` let one fix cover a block
that changes line count, which a lone constructor-call rename could never
represent at all. A coupled group whose only problem is coupling itself
-- every member confirmed, at least one needing block-level treatment --
now gets one dedicated call showing every member's full statement span
and asking for a consistent set of fixes or a joint decline, instead of
the automatic decline this section previously described as the only
option.

**The value-flow guard is the piece that makes shipping a coordinated fix
safe, and it is deterministic -- no model call.** For a jointly-resolved
group, every keyword argument removed at one member must reappear, with
an AST-equal value expression, at another member; expression equality,
not name presence, so `port=port` quietly replaced by `port=8000` still
fails the check. This closes the specific failure class named when the
coupling increment first shipped: a coordinated fix that silently drops a
value parses cleanly, passes signature binding because the parameter has
a default, and looks correct in a diff -- nothing else in this pipeline's
verification tiers can see it. A group that fails the guard falls back to
`flagged_for_human` for every member, the same outcome an automatic
decline would have produced, just reached after a real attempt instead
of before one.

**Joint resolution itself has never fired on a real repo.** Every coupled
group observed so far -- run-azeroth and run-youtrack-v2, both recorded
above -- contains a member adjudication marked uncertain, and a group
with an uncertain member declines without ever reaching the model, by
design, regardless of whether the rest of it could theoretically be
resolved jointly. The capability is built and covered by offline unit
tests reproducing the shapes this section already documented, but it
remains unproven on real, paid input: no real run has yet produced a
coupled group whose only blocker is coupling itself.

**Building joint resolution surfaced a regression in the group-consistency
rule it was built next to: `related_sites` was being read as an
undirected edge.** Union-find merged an entire connected component on
one shared edge, so a single uncertain member declined every confirmed
member in the whole component, not just the ones that actually depended
on it. On `run-youtrack-joint`, adjudication produced `main.py:10`
(an import rename, no dependency), `main.py:25` (a return-annotation
rename depending on `10`), `main.py:27` (a multi-line constructor also
depending on `10`), and an uncertain `main.py:70` depending on `27` and
`25`. The undirected reading put all four in one component and declined
all three confirmed members because the component contained an uncertain
site -- taking a run that had previously produced two correct fixes
(`10`, `25`) down to zero. `related_sites` is directional: `25` states
that it depends on `10`; `70` states that it depends on `27` and `25`.
A dependent being unresolved says nothing about whether what it depends
on is safe to fix. Blocking is now a fixed-point closure over the
directed dependency graph -- a site is unsafe if it is itself uncertain
or span-declined, or if something it depends on is unsafe, and never
merely because something depends on it -- with the undirected grouping
retained only for what it was always actually needed for: joint-
resolution eligibility and the report's group roster. Verified back to
`FIX` 2 / `FLAG-FOR-HUMAN` 1 on the same four-site shape.

**Stated explicitly, not assumed: shipping those two fixes while
`main.py:27` stays on `FastMCP(` does leave the file broken if applied on
its own.** `create_server()` raises `NameError` the moment it is called,
since the renamed import no longer defines the name that `27` still
references. This is not a new risk the directional fix introduces --
`27` was unconditionally going to need a human either way, since the
multi-line-span guard declines it regardless of any grouping logic, and
this pipeline has never guaranteed that applying the `fixes` bucket alone
yields a fully migrated repo while `flagged_for_human` entries remain
elsewhere in the same file. `27`'s own flag still carries the full
undirected group roster, and `70` still appears in it as context, so a
reviewer who reads the flag sees the connection to `10` and `25` rather
than being told nothing beyond "this line is multi-line."

**The solo joint-resolution path fired on a real repo for the first
time.** `run-youtrack-solo2` made three API calls where every earlier run
on this shape made two: adjudication, the ordinary fixgen chunk
(`main.py:10`, `main.py:25`), and a dedicated call for `main.py:27` — the
span-guarded `FastMCP(` constructor that, before the grouping-split fix
above, had been declined with no model call at all purely because an
uncertain sibling (`main.py:70`) named it as a dependency, not because
anything about `27` itself required one.

**The model declined it, and the reasoning is correct.** Verified from
the run's own `fixgen/group_main.py_27.json`: *"The rename `FastMCP(` ->
`MCPServer(` is mechanical, but this constructor call also passes
`host=host` and `port=port`, which v2 removed from the constructor...
Leaving them raises `TypeError:
MCPServer.__init__() got an unexpected keyword argument 'port'`, and
removing them here would silently discard the `host`/`port` arguments of
`create_server()` since the corresponding `mcp.run(...)` call site is not
visible in this call."* `flag_source: joint_resolution_declined`. This is
the exact `tonyzorin/youtrack-mcp` insufficient-fix-set failure this
section already documented — found by hand, reading the diff, ten days
ago — reasoned about correctly by the model this time and refused rather
than shipped.

**Two limits, stated rather than claimed as a clean win.** The
value-flow guard was not exercised: the model declined before producing
any fix, so `_check_group_value_flow` was never called — the
deterministic backstop built specifically to catch this failure
mechanically remains proven only by unit test, not by a real run that
needed it. And the declining reason is largely information adjudication
already had: this same run's `adjudication/merged.json` proposed `27`
with the reason *"Transport-specific kwargs passed here (e.g. host/port)
may also need to move to run()"* — the concern the solo call's decline
restates with more specificity (the exact `TypeError`, the explicit
"not visible in this call"), not one it discovered. The solo call's own
premise is showing a site its full multi-line statement instead of one
truncated line, which solves a different problem than this one — the
missing information was never partially visible within `27`'s own
statement, it was never visible at all, because it lives at `mcp.run()`,
a site outside this call's one-member group. The call was not wasted —
it converted an unconditional, no-attempt decline into a real, deliberate
refusal grounded in a specific runtime consequence — but it did not, and
by its own one-member design could not, resolve the underlying
insufficient-fix-set case; only seeing the companion site would.

**The `targetb_small` cassette was re-recorded for the RELATED SITES
prompt tightening, and the mutual-pair structure changed shape, not just
count.** The prior recording (578a289) had one 4-member visibility group
in `test_jmeter_server.py` — `{11, 12, 21, 22}` — containing 3 mutual
(bidirectional) `related_sites` pairs, an artifact of the symmetric
phrasing the tightening removed. This recording splits that into two
2-member groups, `{11, 22}` and `{12, 21}`, containing exactly 2 mutual
pairs. Line 12 (the borderline stub-class site) itself did not move
buckets — it stayed FLAG-UNCERTAIN — so no precision regression needed
accepting here. One other site did resolve cleanly: `mcp_client.py:44`,
which had self-cited itself in `related_sites` under the old prompt, is
now REJECTed outright with a direct reason ("Fact 6: plain
`ClientSession.call_tool()` is unchanged") instead of being flagged
uncertain — the tightening fixed the one case in this host where the
symmetric-edge bug was visibly live.

**The finding worth keeping is a raw-candidate-count difference between
two recordings of the same host, with neither search-stage input file
touched.** This recording found 25 raw candidates before prefiltering
against the prior run's 28 — `tonyzorin_youtrack-mcp/main.py:39` (a
`REJECT`, not a GT site, so scoring was unaffected) simply never appeared
as a candidate this time. Fact-block and vocabulary derivation both
re-run live on every recording and are not perfectly deterministic call
to call (Section 8 already measured this for a redis-py guide's fact
count); this is the same variance showing up one stage downstream, in
the actual candidate set a real repo search produces. The acceptance
harness's 100%/100% bar held through it because the missing candidate
was never a GT site, but the harness's floor is not as fixed as "same
host, same guide, same code" implies — a future guide/repo pairing could
lose a real candidate to this same variance without any code change to
blame.

**An attempt to test gap-fill's added patterns against ordinary
server-shaped repos instead tested nothing new, and finding that out
uncovered a real naming trap in the pipeline's own output.** The intent
was to run the gap-filled vocabulary merged in `run-scanner-dedup` (298
patterns, 183 of them `gf_*`) against two repos with baseline runs
already on record against the original 115-pattern, pre-gap-fill
vocabulary: `databricks-analysis` and `bangumi-analysis`. Both new runs
(`run-databricks-gapfilled`, `run-bangumi-gapfilled`) came back
byte-identical to their own baselines — `databricks-analysis`: 4 raw
candidates, 3 after prefilter, 2 fixes; `bangumi-analysis`: 15 raw, 5
after prefilter, 2 fixes and 2 uncertain — and `check_pattern_shape`
stayed silent on both, despite the merged vocabulary containing the
eight overbroad gap-fill patterns the same check had already flagged
once (`gf_uristrlit`, `gf_mcpenv`, `gf_textmime`, `gf_tooldecor`, and
four more found alongside them).

**The cause, confirmed from each run's own `manifest.json`, not
guessed at: both runs loaded the wrong file.** `run-databricks-gapfilled`
and `run-bangumi-gapfilled` both recorded `"vocabulary_source":
"loaded:.../run-scanner-dedup/vocabulary.json"` — not
`vocabulary_after_gapfill.json`, the file that actually holds the
298-pattern merged result. Diffing `run-scanner-dedup/vocabulary.json`
against `run-youtrack/vocabulary.json` (the file the *original*
databricks/bangumi baselines loaded) shows they're pattern-for-pattern
identical: 115 patterns, zero `gf_*`. Both "gap-fill" runs reloaded the
exact same pre-gap-fill baseline vocabulary the earlier runs used, under
a different path, and so reproduced the baseline exactly — not because
gap-fill's patterns are inert on these repos, but because gap-fill's
patterns were never in the input at all.

**The guard didn't misbehave; the artifact it was pointed at was never
the merged one.** `apidrift/pipeline.py` writes `workdir/vocabulary.json`
once, immediately after load/derive (line 165) and *before* the gap-fill
block runs. Gap-fill's actual output is written separately, to
`vocabulary_after_gapfill.json` (line 198) — `vocabulary.json` is never
rewritten afterward. So in any workdir where gap-fill ran,
`vocabulary.json` permanently holds the pre-gap-fill input, and it's the
filename anyone would reach for by default in a follow-up `--vocabulary`
run — confirmed here: `run-scanner-dedup/pattern_shape.txt` (the check
run live, in-memory, during the original run) does show all eight
patterns flagged, exactly as this section already recorded; it's only
the two later runs, reloading the wrong on-disk file, that saw a clean
115-pattern vocabulary and correctly reported nothing wrong with it.
None of the three hypotheses going in were right as stated — the dedup
merge didn't strip the patterns, and the guard isn't skipped on the load
path — but the practical effect is the one flagged as worth checking: a
bad post-merge vocabulary can silently go unchecked on every subsequent
run, not because the check fails to run on it, but because the natural
filename to reload never contains it. The gap-fill-on-ordinary-repos
question this was meant to answer is still open — cost/value for
gap-fill against a thin FastMCP server hasn't actually been measured
yet, since the two runs above never touched a gap-fill pattern. (Both
the real measurement and a direct, empirical answer to the guard
question below appear further down this section, after the fix.)

**Fixed by write order, not by a load-time check.** Considered three
shapes: write the merged vocabulary to `vocabulary.json` after gap-fill
runs (keeping the pre-merge input under its own name); leave the write
order alone and just rename the pre-merge file to something unambiguous;
or have vocabulary loading refuse a `vocabulary.json` whose sibling
`manifest.json` records a gap-fill pass, redirecting to the merged file.
Took the first. The third was rejected specifically: it would need
`--vocabulary` loading to reach outside the one file it's given and
parse a co-located `manifest.json` that may not travel with it, coupling
two artifacts that are independent everywhere else in this pipeline, and
it treats the symptom (the wrong file gets loaded) rather than the cause
(the right file was never the merged one). `apidrift/pipeline.py` now
writes `workdir/vocabulary.json` once, after the `--gapfill` block, from
whatever `vocab` holds at that point -- identical to
`vocabulary_after_gapfill.json` when gap-fill merged anything, and to the
loaded/derived vocabulary otherwise. The pre-merge input, when `--gapfill`
is requested at all, is written separately to `vocabulary_pre_gapfill.json`
before the confirmation gate, so nothing observed before is lost -- a run
that stops at `GapfillNeedsConfirmation` now correctly leaves no
`vocabulary.json` at all, since nothing has been used for detection yet.
This makes the invariant unconditional rather than advisory: whatever
`--vocabulary <workdir>/vocabulary.json` loads on a later run is, by
construction, what that workdir's own run actually searched with -- no
cross-run manifest inspection required. One new test
(`test_gapfill_vocabulary_json_names_the_merged_vocabulary_not_the_pre_merge_one`,
`tests/test_pipeline_gapfill_smoke.py`) pins this by asserting
`vocabulary.json == vocabulary_after_gapfill.json` and `gf_widgetsess`
absent from `vocabulary_pre_gapfill.json` on the same scripted run this
file already exercises. 336 offline tests pass. The two stale on-disk
workdirs from the finding above (`run-scanner-dedup`, and by extension
anything loaded from it) were also repaired directly -- `vocabulary.json`
now holds the 298-pattern merged vocabulary, with the original
115-pattern input preserved as `vocabulary_pre_gapfill.json` -- so a
repeat of the databricks/bangumi test against the same on-disk artifacts
would no longer reproduce this failure.

**The gap-fill-on-ordinary-repos test, re-run against the actual
298-pattern merged vocabulary this time.** `run-databricks-gf2` loaded
the repaired `run-scanner-dedup/vocabulary.json` (confirmed 298 patterns
from its own file size and pattern count, not assumed) against
`databricks-analysis`. Raw candidates went from 4 (the original,
115-pattern baseline) to 9. `considered_and_rejected` went from 1 to 2 in
`adjudication/merged.json`, which prefilter's stage-C duplicate collapse
and `expand_duplicates` turn into the report's REJECT(1) -> REJECT(6) --
five byte-identical `@mcp.tool()` lines (`main.py:16/50/100/123/152`)
collapsed to one adjudication call, rejected once ("Fact 111: `@mcp.tool()`
is explicitly NOT a breaking change"), then re-expanded back to all five
for the report. FIX stayed at 2, identical sites and identical diffs to
the baseline. Every one of the five additional raw candidates carries
`_pattern: gf_tooldecor` -- confirmed directly from `candidates.json`,
not inferred. No other gap-fill pattern among the 298 fired even once on
this repo.

**The conclusion the earlier, wrong-file comparison couldn't reach:** on
a server-shaped repo, gap-fill's vocabulary contributes noise and an
adjudication pass to correctly reject it, not additional correct fixes.
`gf_tooldecor` is the same pattern identified earlier in this section as
the largest single contributor to `mcp-scanner`'s 2,795-candidate blowup
(745 candidates there, 26.7% of that run's total) -- the same
any-`@x.tool()`-shaped overmatch, doing the same thing here at a scale
five candidates makes affordable to absorb by hand, where at
`mcp-scanner`'s scale it wasn't. The model adjudicated it correctly both
times; the cost is candidates and an adjudication call, not incorrect
output. Whether that trade is worth it depends entirely on repo size --
five spurious candidates on a 200-line server is noise, the same pattern
on a large tool-heavy server could be a meaningfully larger fraction of
adjudication cost for zero additional fixes either way.

**The guard question, resolved empirically rather than by re-reading the
code: `check_pattern_shape` does run on the `--vocabulary` load path, and
dedup's merge did not alter `gf_tooldecor` in any way that would let it
escape the check.** `run-databricks-gf2/pattern_shape.txt` -- generated
by this same run, against the loaded (not derived) 298-pattern vocabulary
-- opens with `flagged as open-shape: 9` and lists `gf_tooldecor`
explicitly: `OPEN SHAPE -- 7 required literal char(s)`, the identical
verdict recorded for it earlier in this section when the check was first
built and run against it live. Neither hypothesis this section originally
weighed survived contact with a real run: the guard is not skipped when a
vocabulary is loaded rather than derived -- `apidrift/pipeline.py` calls
`check_pattern_shape(vocab["patterns"])` unconditionally, after vocab is
finalized, with no branch on `vocabulary_source` -- and dedup's merge
left `gf_tooldecor`'s regex untouched, character for character, from the
version the check flagged the first time. The run only proceeded past the
guard because it was invoked with `--force`, printing `GUARD BYPASSED`
exactly as designed for a deliberate, already-diagnosed case -- not
because the guard failed to fire. The earlier appearance of a silent
guard, recorded above in this same section, was entirely downstream of
the wrong-file bug: `run-databricks-gapfilled`'s loaded vocabulary
genuinely contained zero `gf_*` patterns, so the guard had nothing to
flag and correctly said so. No run in this project has ever shown
`check_pattern_shape` fail to fire on a vocabulary loaded via
`--vocabulary` that actually contained a flaggable pattern.

**A design observation, not a bug: `--force` bypasses every guard at
once, regardless of which one actually fired or why.** It exists because
`check_vocabulary_coverage` fired on facts later shown in this same
section to be largely uncoverable by construction (client-side surface a
thin FastMCP server can't exercise), and has been passed on every real
run since. `run-databricks-gf2` is the concrete case: `--force` was
needed for that run at all only because of `check_vocabulary_coverage`'s
known, already-understood limitation, but the same flag silently carried
`check_pattern_shape`'s verdict on `gf_tooldecor` past the point of
stopping anything -- correctly computed, correctly written to
`pattern_shape.txt`, and never read, because the run simply completed.
One switch covering guards with different reliability records means the
trustworthy ones inherit the noisy one's suppression; nothing about that
run distinguished "bypassing a guard whose false-positive rate is already
understood" from "bypassing a guard that just caught something real." Not
changing `--force` now -- a per-guard bypass is a real design change, not
a same-session fix, and belongs in its own pass. Worth naming on its own,
though: this is the second consecutive finding in this section produced
by opening a workdir's own recorded artifacts (`pattern_shape.txt`,
`manifest.json`) rather than trusting a run's pass/fail outcome or
re-deriving the answer from reading the code -- the more durable habit to
carry forward than either individual fix.
