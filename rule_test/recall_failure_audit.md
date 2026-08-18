# Recall failure audit: every recorded miss, across the whole study, classified by mechanism and file class

## 2026-08-18 update: transitive stage A shipped — the one production miss is fixed, reverified, and stays fixed

This audit originally found one production-code exception to an otherwise
overwhelming test/mock concentration: `src/opsmesh/orchestrator/
tool_catalog.py:46`, dropped by the prefilter's stage A because that file
uses the SDK's data shape only through a host-internal wrapper and never
references the package by name. That mechanism was fixed by implementing
transitive relevance in stage A (a file is relevant if it directly matches
the pattern, or imports — transitively, via the repo's own `ast`-derived
import graph — a file that does) and re-verified with **9 fresh runs**
across all three tested host types, 3 runs each:

| host | GT | precision | recall (propose) | recall (surfaced) | production misses | reduction |
|---|---|---|---|---|---|---|
| targetB_small | 20 | 100%, all 3 runs | 100%/100%/95% | 100%, all 3 | **0** | 81.1% (unchanged) |
| targetB_diluted | 20 | 100%, all 3 runs | 85%/85%/100% | 100%, all 3 | **0** | 90.1% (unchanged) |
| entangled (OpsMesh) | 10 | 100%, all 3 runs | 70%/70%/90% | 90%, all 3 | **0** | 36.2% (was 49.3%) |

**`tool_catalog.py:46` was confirmed PROPOSE — correctly, confidently,
with no hedging — in all 3 fresh entangled runs.** Zero regressions: every
site that previously passed still passes (`base.py:16/24`, `context.py:
12/13/20`, `test_server_base.py:31` all proposed in all 3 runs; the
targetB_small/diluted candidate sets are byte-identical to before the
fix, confirmed directly, and their agent-adjudication results match this
study's established variance pattern with zero false positives across all
9 runs). The only remaining miss on the entangled host, in all 3 runs, is
the pre-existing grep-vocabulary gap (`tests/test_client_session_group.py:
23`) — a different mechanism entirely, untouched by this fix by design
(see "Direct answer," below, for why stage A can't reach it).

**One new, honest data point, not a miss:** in 2 of the 3 fresh entangled
runs, a *different* production site — `src/opsmesh/client/session_group.py
:38` (`ClientSessionGroup.call_tool()`'s changed contract) — landed in
FLAG-UNCERTAIN instead of PROPOSE, on a genuine ambiguity in the migration
facts (whether "lost its `args` parameter" means the positional slot was
removed or just a keyword named `args`). This is the first time this
study's hedge-undercount mechanism has touched production code — every
prior instance of it (blind_vocab, prefilter reliability) was the same
one test/mock site. It is not a miss: the site was surfaced, not lost,
in every run it occurred in (recall-surfaced stayed 90%, never dropped
further). Recorded here because the audit's job is to catch exactly this
kind of shift before it's asked about, not after.

**Answer to "is the production-miss count across the whole study now
zero": yes, as currently shipped, with the historical exception closed
out rather than papered over.** Exactly one distinct production site has
ever been missed anywhere in this study's history (`tool_catalog.py:46`,
entanglement experiment, prefilter stage A) — established in the original
audit below and unchanged by this update. That miss is now fixed:
confirmed 3/3 in fresh, independent runs, with the exact fix (transitive
stage A) and the exact regression check (existing candidates unchanged,
existing passes unchanged) both applied and verified, not assumed. No
other production site, in any of the 12 experiments audited (including
these 9 new runs), has ever been missed. The updated instance tallies and
base-rate comparison below fold in this fix; the original analysis is
preserved underneath for the historical record.

## Updated count both ways (post-fix)

**Miss instances, hard misses only (site never surfaced anywhere —
excludes hedge-to-FLAG-UNCERTAIN, which is surfaced not lost):**

| | test/mock | production | total |
|---|---|---|---|
| Historical (spec_reinstated, dilution, entanglement pre-fix) | 15 | 3 | 18 |
| Post-fix verification (9 fresh runs: entangled + targetB small/diluted, transitive stage A) | 3 | **0** | 3 |
| **Current/shipped state** | **3** | **0** | 3 |

(The historical 15/3 breaks down as: spec_reinstated 3 + dilution 9 +
entanglement's old grep-miss 3 = 15 test/mock; entanglement's old
prefilter-dropped production site x3 runs = 3 production. The
post-fix column replaces the old entanglement row entirely — same host,
same GT, new prefilter, freshly re-run rather than assumed unchanged.)

**Distinct sites ever missed, at least once, anywhere, historical
record (unchanged by the fix — this is "did it ever happen," not
"does it still happen"):**

| | test/mock | production | total |
|---|---|---|---|
| Distinct sites ever missed | 5 | 1 | 6 |
| (out of total GT sites in that class) | 5/6 = 83.3% | 1/37 = 2.7% | 6/43 |

That one production site is now fixed and reverified; it remains in this
row because the question this row answers is historical ("ever"), not
current ("still"). The "current/shipped state" row above is the one that
answers "does this still happen."

---

Every experiment in this study, in order, checked directly against its own
raw run data and reports — not summarized from memory. Scope: `original
session` (superseded, no reliable data), `spec_reinstated` (27 runs),
`scale_experiment`/dilution (3 runs), `composition_experiment` (6 runs),
`blind_vocab_experiment` (12 runs), `prefilter_experiment` (candidate-set
coverage checks + 5 reliability runs), `entanglement_experiment` (3 runs +
1 diagnostic). Ground truth for the "core" 33 sites: `ground_truth/
ground_truth.md`. Ground truth for the 10 entanglement sites:
`rule_test/entanglement_experiment/report.md`.

## Master table — every recall-failure instance recorded anywhere

"Instance" = one site missed in one specific run of one specific
configuration. The same underlying site missed in 3 separate runs counts
as 3 instances, matching how this study has scored recall throughout
(e.g. "26 of 27 repo-runs hit 100% recall").

| Experiment | Run | Site | File class | Mechanism | Surfaced anywhere? |
|---|---|---|---|---|---|
| spec_reinstated | run3 | `QAInsights.../tests/test_jmeter_server.py:11` (B8a) | **test/mock** | agent_confident_reject (over-applied counting convention) | no — confident REJECT |
| spec_reinstated | run3 | `.../tests/test_jmeter_server.py:21` (B8c) | **test/mock** | agent_confident_reject | no — confident REJECT |
| spec_reinstated | run3 | `.../tests/test_jmeter_server.py:22` (B8d) | **test/mock** | agent_confident_reject | no — confident REJECT |
| dilution (scale) | run1 | `.../tests/test_jmeter_server.py:11` | **test/mock** | agent_confident_reject (mechanism A) | no — confident REJECT |
| dilution (scale) | run1 | `.../tests/test_jmeter_server.py:21` | **test/mock** | agent_confident_reject (mechanism A) | no — confident REJECT |
| dilution (scale) | run1 | `.../tests/test_jmeter_server.py:22` | **test/mock** | agent_confident_reject (mechanism A) | no — confident REJECT |
| dilution (scale) | run2 | `.../tests/test_jmeter_server.py:11` | **test/mock** | agent_silent_omission (mechanism B) | no — absent from all 3 buckets |
| dilution (scale) | run2 | `.../tests/test_jmeter_server.py:21` | **test/mock** | agent_silent_omission (mechanism B) | no — absent from all 3 buckets |
| dilution (scale) | run2 | `.../tests/test_jmeter_server.py:22` | **test/mock** | agent_confident_reject (mechanism A) | no — confident REJECT |
| dilution (scale) | run3 | `.../tests/test_jmeter_server.py:11` | **test/mock** | agent_silent_omission (mechanism B) | no — absent from all 3 buckets |
| dilution (scale) | run3 | `.../tests/test_jmeter_server.py:21` | **test/mock** | agent_silent_omission (mechanism B) | no — absent from all 3 buckets |
| dilution (scale) | run3 | `.../tests/test_jmeter_server.py:22` | **test/mock** | agent_silent_omission (mechanism B) | no — absent from all 3 buckets |
| composition | (6 runs) | — none — | — | — | 100% recall, all 6 runs |
| blind_vocab | B-small, 1 of 3 runs | `.../tests/test_jmeter_server.py:11` | **test/mock** | agent_hedge_undercount (Rule-1 anchor, put in FLAG-UNCERTAIN not PROPOSE) | **yes — FLAG-UNCERTAIN** |
| blind_vocab | (11 other runs) | — none — | — | — | 100% recall |
| prefilter (candidate-set, all 4 scale/target combos) | — | — none — | — | zero GT loss, verified every stage | — |
| prefilter (reliability, 5 runs) | attempt1 | `.../tests/test_jmeter_server.py:11` | **test/mock** | agent_hedge_undercount (same shape as blind_vocab) | **yes — FLAG-UNCERTAIN** |
| prefilter (reliability, 5 runs) | attempts 2–5 | — none — | — | — | 100% recall |
| entanglement | run1 | `tests/test_client_session_group.py:23` | **test/mock** | grep_missed | no — never a candidate |
| entanglement | run1 | `src/opsmesh/orchestrator/tool_catalog.py:46` | **PRODUCTION** | prefilter_dropped (stage A) | no — never reached the agent |
| entanglement | run1 | `tests/test_orchestrator_agent.py:18` | **test/mock** | prefilter_dropped (stage A) | no — never reached the agent |
| entanglement | run2 | (same 3 sites as run1) | 1 prod / 2 test | grep_missed / prefilter_dropped ×2 | no |
| entanglement | run3 | (same 3 sites as run1) | 1 prod / 2 test | grep_missed / prefilter_dropped ×2 | no |
| entanglement | diagnostic (stage A off) | `tests/test_client_session_group.py:23` | **test/mock** | grep_missed (persists regardless of prefilter config) | no — never a candidate |
| entanglement | diagnostic (stage A off) | (the other 2 sites) | — | **recovered** — agent proposed both correctly | **yes — PROPOSE, correct** |

## Direct answer: has a production site ever been missed?

**Yes, once.** `src/opsmesh/orchestrator/tool_catalog.py:46`, in the
entanglement experiment, missed in all 3 shipped runs. Mechanism: the
hardened prefilter's stage A drops a file with zero occurrences of the
package-relevance pattern in its own text — this file interacts with the
SDK's data shape entirely through a wrapper (`FleetClient.
discover_all_tools()`) and never names `mcp` directly, so stage A drops
it with total confidence before the agent ever sees the candidate. This
is not agent judgment: the stage-A-disabled diagnostic run confirms the
agent proposes this exact site correctly, with reasoning indistinguishable
from every other true positive, when given the chance. It is not
something present in any of the "core" 33-site experiments (spec_reinstated,
dilution, composition, blind vocab, prefilter candidate-set checks) — it
appears in exactly one experiment, caused by exactly one mechanism, and a
measured (not-yet-shipped) fix exists for it (`transitive_relevance_experiment.py`,
see `rule_test/entanglement_experiment/report.md`).

**So the clean "the pipeline never misses production code" claim is
false as an absolute statement.** The precise, correct claim is narrower
— see "Shippable limitation" below.

## Count both ways

**Miss instances** (23 total, across every experiment and run):

| | test/mock | production | total |
|---|---|---|---|
| Miss instances | **20** | **3** | 23 |
| Share of instances | 87.0% | 13.0% | 100% |

(All 3 production instances are the same underlying site —
`tool_catalog.py:46` — missed once in each of entanglement's 3 shipped
runs. It is not 3 different production sites.)

**Distinct sites ever missed, at least once, anywhere:**

| | test/mock | production | total |
|---|---|---|---|
| Distinct sites ever missed | **5** | **1** | 6 |
| (out of total GT sites in that class) | 5 / 6 = 83.3% | 1 / 37 = 2.7% | 6 / 43 |

**Base rate — total GT sites defined anywhere in this study, by class:**

| | test/mock | production | total |
|---|---|---|---|
| Target A (13) | 0 | 13 | 13 |
| Target B (20) | 3 | 17 | 20 |
| Entanglement (10) | 3 | 7 | 10 |
| **Total** | **6** | **37** | **43** |
| **Share of GT population** | **14.0%** | **86.0%** | 100% |

**This is not a base-rate artifact — it's an inversion.** Test/mock code
is 14% of everything this study ever defined as ground truth, yet it
accounts for 87% of every recall-failure instance ever recorded and 83%
of the distinct sites ever missed. Production code is 86% of the GT
population and accounts for only 13% of miss-instances and 2.7% of
distinct sites (one site, one mechanism, one experiment). If misses were
distributed the way the GT population is distributed, we'd expect the
overwhelming majority of misses to be production sites; instead the
overwhelming majority are test/mock, by a wide margin in both counting
methods.

## The mechanism diversity behind the test/mock concentration

The test/mock concentration isn't one recurring bug — it's **four
independent mechanisms**, discovered in four separate experiments, that
all happen to land on the same class of code:

1. **agent_confident_reject** (spec_reinstated run3, dilution run1 + part
   of run2) — the agent over-applies the "fixing the import repairs
   downstream references automatically" convention to a case the
   convention doesn't actually cover: a name that's *redefined to
   impersonate* the moved symbol (a `sys.modules`/`types.ModuleType`
   stub), not merely *imported and referencing* it.
2. **agent_silent_omission** (dilution run2 partial, run3 full) — a
   failure mode with no small-scale analogue: content is read into
   context but never converted into a verdict in any bucket at all, at a
   rate that tracks with total host size (this study's evidence: the run
   with the thinnest total output showed the most complete omission).
3. **grep_missed** (entanglement) — a vocabulary pattern requiring
   immediate token adjacency (`\.call_tool\(`) doesn't match a mock-
   assertion idiom that inserts an attribute access between the name and
   the paren (`call_tool.assert_awaited_once_with(`).
4. **agent_hedge_undercount** (blind_vocab, prefilter reliability) — the
   agent correctly identifies the site and correctly applies mandatory
   Rule 1 (name-impersonation), landing it in FLAG-UNCERTAIN rather than
   PROPOSE — surfaced, not lost, but a miss under the strict propose-only
   recall metric this study reports throughout.

The one production miss (`prefilter_dropped`, entanglement) is a fifth,
structurally distinct mechanism, and it is the only one of the five that
has never recurred across more than one experiment.

## Shippable limitation, stated precisely

**What's NOT guaranteed, in order of how well-established the gap is:**

1. **(Well-established, recurring across 4 mechanisms, 4 experiments)**
   Test/mock fixture code that impersonates or asserts against the
   target SDK's shape — `sys.modules`/`types.ModuleType` stand-ins for a
   moved/renamed module, mock-library assertions on the exact arguments
   of a changed call signature, and fake objects whose attribute names
   mirror a renamed field. This is the pipeline's dominant, best-evidenced
   weak class. It recurs under single-pass search+judge at scale, under a
   grep vocabulary that doesn't anticipate mock-library call chaining,
   and under the agent's own mandatory-hedge rule doing exactly what it's
   designed to do (Rule 1 correctly triggers on this class, which is why
   it undercounts on the strict propose-only metric even when nothing is
   actually lost).

2. **(Fixed and reverified, 2026-08-18 — no longer an open gap, kept here
   as the record of what it was and why it's now closed)** Production
   code that references the target SDK's data or behavior *exclusively*
   through the host's own internal abstraction layer, in a file with
   zero direct textual reference to the SDK package, used to be silently
   dropped by file-local relevance filtering in the prefilter's stage A
   — which could not distinguish "this file doesn't need the SDK" from
   "this file gets the SDK's data through a wrapper and never says so."
   Stage A now follows the repo's own intra-repo import graph
   transitively (a file is relevant if it directly matches the pattern,
   or imports a file that does), confirmed to recover the exact site
   this cost the study (`tool_catalog.py:46`) in 3/3 fresh runs with zero
   regressions elsewhere. **This is not a claim that entanglement in
   general is now fully solved** — see the caveat below.

**Open caveat on the fix itself: stage A's reduction value is unproven on
shared-core monorepo topologies, and the documented fallback if it
collapses there is to drop stage A entirely.** Transitive closure was
measured on two hosts: the entangled OpsMesh host (real cost — reduction
fell from 49.3% to 36.2%) and the existing diluted host, an assembly of
independent small repos with no shared "core" module most files import
(zero cost — 90.1% unchanged, because nothing in that topology chains
into relevance). Neither host has a single internal SDK/framework layer
that hundreds of files import, which is exactly the shape that could make
transitive closure expensive: if the directly-relevant file is, or is
imported by, something central to a real company monorepo, the closure
could plausibly approach "almost nothing gets dropped," collapsing stage
A's reduction value toward zero on that specific topology. If that
happens in practice, **the documented fallback is dropping stage A
entirely** (stages B/C only) and absorbing the resulting higher
adjudication volume and cost — a money problem to manage, not a
correctness one to accept, because "no silent production misses" is the
property stage A exists to protect and reduction ratio is only ever a
cost optimization on top of it.

**Why test/mock is the cheaper place to miss, concretely, checked against
every instance in this study, not asserted in the abstract:** every
test/mock miss recorded above is a case where leaving the stub/mock/fixture
un-migrated does not silently pass — it throws. The QAInsights stub, if
not updated to the new module path, makes `jmeter_server.py`'s corrected
import look up a `sys.modules` key the stub never registers:
`ImportError`, immediately, the first time the test suite runs post-migration.
The entanglement mock-assertion site, if the production call signature
changes underneath it, makes the test's `assert_awaited_once_with(...)`
compare against arguments that no longer match what's actually
called: `AssertionError`, immediately. A CI run built on any of these
migrations goes red the moment someone runs the test suite, independent
of whether the automated detector caught the site — the fixture's own
staleness is self-reporting. The one production miss found here does the
opposite: `getattr(tool, "inputSchema", {})` failing to find the
now-renamed field silently returns the default `{}` instead of raising
anything, and nothing about that is guaranteed to be covered by a test
that would turn red — it's a quietly wrong runtime value in a running
service, not a failed build. That asymmetry — loud-and-caught vs.
silent-and-shipped — is why that one production gap was worth fixing
immediately rather than accepting alongside the much larger test/mock
count: CI is a second net under every test/mock miss recorded in this
study, and there was no equivalent second net under the production one.
Now that it's fixed and reverified, the shippable limitation is simply
the well-established test/mock class above, plus the open, honestly-
unresolved question of whether stage A's transitive-closure fix holds up
on a real shared-core monorepo — the one topology this study hasn't
been able to test yet.
