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
- **Target B**: MCP Python SDK v1 → v2, an *invented* migration for a real
  SDK, dated in the future (stated as "released July 2026," after any
  realistic training cutoff), applied to 5 public repos (20 sites after
  one correction — see below).

Target B is the control. Target A's migration is real and old enough that
a model could plausibly recite its facts from memorized training data
without reading a single line of code — good performance there doesn't
distinguish "reasoning about this codebase" from "recalling a famous
migration guide." Target B cannot be recalled from anywhere: it doesn't
exist. Any correct answer on Target B has to come from actually reading
the supplied spec and the actual code. Target A stayed clean (100%/100%,
no exceptions, every experiment) for the whole study; nearly everything
interesting — every reversal below — happened on Target B, which is
exactly what the control is supposed to surface.

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
production-code miss recorded anywhere in this entire study. It was
traced to the filter, not the agent (confirmed by disabling the filter
stage and re-running: the agent proposed the site correctly every time
given the chance), fixed by making that filter's relevance check follow
the codebase's own import graph instead of just the file's own text, and
re-verified with 9 fresh runs across three hosts: the fix recovered the
site with zero regressions and zero new production misses, at a real,
accepted cost in how much the filter reduces candidate volume.

## 4. Final architecture

Three stages, each doing one job:

1. **Grep** — exhaustive, coverage-tuned pattern matching. Not asked to be
   precise; a broad vocabulary derived from the public migration guide
   alone (without looking at the answer key) still found every ground-truth
   site across both targets in this study.
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

## 6. Limitations, stated plainly

**Test/mock coverage is the study's real, recurring weak spot**, via four
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
tested is either a handful of independent small repos or one large repo
with no single shared internal module most files import. A real company
monorepo with a shared internal SDK/framework layer is a structurally
different, untested case; if the filter's relevant file is central to
such a codebase, its reduction value could collapse toward zero there.
The documented fallback is dropping that filter stage entirely and
absorbing higher review volume — a cost problem, not a silent-miss one.

**Everything here is one migration per target, one SDK family per
target, and one language.** All 43 ground-truth sites across the whole
study are Python. Nothing here tests a second language, a breaking
change with no textual signature (a behavior-only change, a
config-driven default), or a codebase behind on more than one migration
at once.

**The absolute sample size is small.** 43 total ground-truth sites is
enough to find and characterize specific failure mechanisms, not enough
to claim their rates are stable. Both real gaps this study found — the
test/mock cluster and the entanglement miss — were invisible until a
host was specifically built to go looking for them; there is no
guarantee a larger, more varied corpus wouldn't surface another one the
same way.

## 7. What would have to be true for this to be a product

This measures detection accuracy on a fixed, known candidate list against
a hand-verified answer key. It does not measure: whether a real reviewer
trusts and correctly acts on a PROPOSE/FLAG-UNCERTAIN/REJECT list in an
actual workflow; whether the grep-vocabulary-derivation step holds up
against migration guides far less complete than the ones used here;
latency and cost at repository sizes and candidate volumes larger than
anything tested; a real shared-core monorepo, the one topology explicitly
flagged as untested above; a second language; a breaking change with no
grep-able signature at all; or a codebase carrying multiple overlapping,
unresolved migrations simultaneously. Turning this into a product means
closing those gaps one at a time, in the open, the same way each finding
in this report closed the gap that came before it — not asserting the
final numbers cover them.
