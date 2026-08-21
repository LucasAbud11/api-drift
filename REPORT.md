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
