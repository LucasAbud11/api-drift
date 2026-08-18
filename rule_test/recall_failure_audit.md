# Recall failure audit: every recorded miss, across the whole study, classified by mechanism and file class

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

2. **(Narrow, single occurrence, mechanistically understood, fix already
   measured)** Production code that references the target SDK's data or
   behavior *exclusively* through the host's own internal abstraction
   layer, in a file with zero direct textual reference to the SDK
   package. Caused by file-local relevance filtering in the prefilter's
   stage A, which cannot distinguish "this file doesn't need the SDK"
   from "this file gets the SDK's data through a wrapper and never says
   so." A transitive-import-graph replacement for stage A is measured
   (not shipped) and recovers this exact site in the one host it's been
   tested against.

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
silent-and-shipped — is the actual argument for why this concentration,
even though it isn't perfectly clean, still describes a real and useful
risk ordering: a team relying on this pipeline should worry far more
about the one narrow, already-diagnosed production gap than about the
much larger test/mock miss count, precisely because CI is a second net
under the test/mock misses and there is no equivalent second net under
the production one.
