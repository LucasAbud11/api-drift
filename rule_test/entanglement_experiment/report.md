# Entanglement: does detection survive when a host wraps the SDK through its own layers?

Every prior host in this study tested **dilution** — more unrelated code
mixed in, no structural interaction with the target SDK. This experiment
tests something categorically different: a host that uses the SDK
*entirely through its own abstractions* (subclassing, wrapping,
re-exporting) rather than calling it directly. The methodological
constraint from the start: **I did not build this host.** I know exactly
what the detector, vocabulary, and hardened prefilter handle, so I would
unconsciously avoid building traps that defeat them. Instead, a separate,
walled-off agent built it, with access to nothing but the MCP v1 API
surface and an instruction to build something realistic — no access to
`detector_prompt_v2.md`, the vocabulary, the prefilter code, or any report
in this project.

## The host: OpsMesh

The isolated agent invented "OpsMesh," an internal developer-platform
service (deployment status, incident lookup, service catalog, runbook
search tools, plus a CLI orchestrator that fans out across a fleet of MCP
servers) — 33 Python files under `host/`. It independently chose exactly
the entanglement patterns the task asked for, without seeing any of this
study's material:

- `OpsMeshServer(FastMCP)` — the server is used everywhere in the app via
  the app's own subclass name, never `FastMCP` directly except at the one
  declaration site.
- `OpsMeshClient` wraps a single `ClientSession`; `FleetClient` wraps
  `ClientSessionGroup` — application code touches only the wrappers.
- `ToolCatalog` reads `tool.inputSchema` off discovery results without
  ever importing `mcp` directly in that file — it receives already-wrapped
  data from `FleetClient.discover_all_tools()`.

## Ground truth: 10 sites, independently derived

I read every file in the host directly (not the host-construction agent,
not the detector) and applied the same 9-fact migration spec used
throughout this study's Target B work (`adjudication_prompt_reduced_targetB.md`)
line by line. Full reasoning is in the scoring script; the 10 sites:

| # | file:line | why |
|---|---|---|
| 1 | `server/base.py:16` | `from mcp.server.fastmcp import FastMCP` — moved module path |
| 2 | `server/base.py:24` | `class OpsMeshServer(FastMCP):` — renamed identifier, not just moved |
| 3 | `server/context.py:12` | `from mcp.server.fastmcp import Context` — moved module path |
| 4 | `server/context.py:13` | `from mcp.server.fastmcp import get_context as _mcp_get_context` — moved path, and the symbol is removed |
| 5 | `server/context.py:20` | `ctx = _mcp_get_context()` — calls a function removed entirely in v2 |
| 6 | `client/session_group.py:38` | `self._group.call_tool(tool_name, arguments)` — `ClientSessionGroup.call_tool()`'s changed contract, reached only through the `FleetClient` wrapper |
| 7 | `orchestrator/tool_catalog.py:46` | `getattr(tool, "inputSchema", {})` — camelCase field read, in a file with **zero direct `mcp` reference** |
| 8 | `tests/test_server_base.py:31` | `patch("mcp.server.fastmcp.FastMCP.run")` — stale dotted path inside a mock-patch string |
| 9 | `tests/test_client_session_group.py:23` | `mock_session_group.call_tool.assert_awaited_once_with(...)` — test assertion on the exact args of the changed-contract call |
| 10 | `tests/test_orchestrator_agent.py:18` | `SimpleNamespace(..., inputSchema=schema)` — test fixture using the old field name, in a file with **zero direct `mcp` reference** |

**One correction made during scoring, disclosed rather than buried:** my
first manual pass missed site 5. I derived GT by re-reading the reduced
6-item guide I'd given the host-construction agent (which said
`get_context()` — unchanged), instead of the authoritative 9-fact spec
actually used for adjudication throughout this study, which states
`mcp.get_context()` is **removed entirely**. All 3 agent runs correctly
proposed this site; my initial manual GT was wrong, not their verdict —
confirmed by re-checking the authoritative spec text directly before
accepting the correction.

Sites 7 and 10 are the ones that matter most for this experiment: real
GT sites in files with **no textual reference to the `mcp` package
anywhere** — the file only touches SDK-shaped data through the app's own
`FleetClient`/`OrchestratorAgent` layers. This is entanglement's exact
signature, and it's not something I engineered — the isolated agent built
it without knowing what any downstream filter checks for.

## Three-way loss attribution (same for all 3 runs — grep and the prefilter are deterministic)

| GT site | grep candidate? | survives hardened prefilter (A+B+C)? | reachable by agent? |
|---|---|---|---|
| 1–6, 8 (7 sites) | yes | yes | **yes** |
| 9 — `test_client_session_group.py:23` | **no** | n/a | **no** |
| 7 — `tool_catalog.py:46` | yes | **no**, dropped by stage A | **no** |
| 10 — `test_orchestrator_agent.py:18` | yes | **no**, dropped by stage A | **no** |

**10 total GT → 1 lost to grep, 2 lost to the prefilter, 7 reachable.**
This is the same three-way split for every run, because grep and the
prefilter are deterministic — only the agent's adjudication of the 7
reachable candidates varies run to run.

### Mechanism 1 — grep/vocabulary miss (unrecoverable by anything downstream)

`tests/test_client_session_group.py:23` is
`mock_session_group.call_tool.assert_awaited_once_with("search_docs", {"query": "rollback"})`.
The blind vocabulary's pattern for this is `\.call_tool\(` — which
requires `call_tool` to be **immediately** followed by `(`. This line has
`call_tool.assert_awaited_once_with(` — the mock-assertion idiom inserts
an attribute access between the name and the paren, and no pattern in the
vocabulary anticipated that. **This is the one failure mode this
architecture cannot recover from by construction**: grep is supposed to
be exhaustive (everything downstream — prefilter, agent — assumes it is),
and here it demonstrably is not. No amount of prefilter or agent quality
matters for a site that was never a candidate.

### Mechanism 2 — hardened prefilter stage A, entanglement's structural blind spot

The other two losses are both stage A, both the same root cause: **stage
A drops a file if it finds zero occurrences of the package-relevance
pattern anywhere in that file's own text.** That rule is correct for
dilution — an unrelated file in a diluted host really doesn't reference
the package, and that absence really is informative. It is **structurally
wrong for entanglement**, because entanglement's entire premise is that a
file can use the SDK's data/behavior through the host's own abstraction
layer and never name the package itself. `tool_catalog.py` and
`test_orchestrator_agent.py` are exactly that: real GT sites, zero direct
`mcp` references, dropped with total confidence by a rule that has no way
to know it's wrong. This is the identical failure shape already flagged
during the hardening pass's audit — file-level "no reference found" being
treated as certain irrelevance — just now demonstrated on a host built by
someone (something) with no knowledge of that audit, so it isn't a
result I could have engineered by knowing what to avoid. It's also the
same "textual proximity does not imply relevance" assumption that failed
in the earlier reflection case today, showing up a second time in a
different mechanism.

Stage B and C caused **zero** additional GT loss in either configuration
(confirmed directly, not assumed) — this is purely a stage A problem.

## Runs 1–3: full pipeline (grep → hardened prefilter → agent), as shipped

35 final candidates per run, all schema-valid, zero missing/extra
candidates in any run's output (validated via `validate_run_file()`).

| run | proposed | flag-uncertain | reject | TP | FP | precision | recall (of 7 reachable) |
|---|---|---|---|---|---|---|---|
| 1 | 7 | 0 | 28 | 7 | 0 | 100% | 100% |
| 2 | 7 | 0 | 28 | 7 | 0 | 100% | 100% |
| 3 | 7 | 0 | 28 | 7 | 0 | 100% | 100% |

**Identical across all 3 runs** — same 7 true positives, same 0 false
positives, 0 items in FLAG-UNCERTAIN in every run. The agent correctly
rejected every trap present in the 35 candidates: `Context`/`ClientSession`/
`ClientSessionGroup` type annotations downstream of a fixed import,
`ctx.error`/`ctx.info` calls without `extra=`, `click.Context` (unrelated
library, name collision only), the unaffected `ClientSession.call_tool`
wrapper sitting next to the affected `ClientSessionGroup.call_tool`
wrapper despite heavy textual overlap (`call_tool` appears identically in
both), `dt.timedelta` domain fields unrelated to the SDK's timeout
representation, and the app's own `FleetClient.call_tool`/`self._fleet.call_tool`
call site (correctly attributed the fix to the wrapper's internals, not
the caller). Zero FLAG-UNCERTAIN also means Rule 1 never fired (no
name-impersonation machinery present) and the one Rule-2-eligible
candidate (the mock-patch string) was confidently resolved to PROPOSE,
which the rules permit.

**End-to-end numbers that matter for a real migration:**
- **Precision: 100%** (0 false positives, all 3 runs) — the agent did not
  get fooled by any of the entanglement traps.
- **Recall against what survived to it: 100%.**
- **Recall against true ground truth: 70% (7/10)** — the number a team
  relying on this pipeline would actually experience, because 3 real
  sites never reached the agent at all.

## Diagnostic: is the 2-site prefilter loss recoverable by the agent?

One additional run, stage A disabled (grep → stage B/C only → agent), 47
candidates including the 2 previously-dropped sites plus 10 more
reject-bait candidates the wider file set pulled in (`click.Context`,
`github_client.py`'s unrelated `httpx.AsyncClient`, `call_tool` inside an
f-string, 4 more test-wrapper calls).

**Result: 9/9 reachable GT correctly proposed, 0 false positives, 0
GT sites in FLAG-UNCERTAIN.** Both previously-dropped sites —
`tool_catalog.py:46` and `test_orchestrator_agent.py:18` — were proposed
correctly, with reasoning indistinguishable in quality from the other 7.
The 4 new test-wrapper candidates were correctly routed to
FLAG-UNCERTAIN by mandatory Rule 2 (test-path floor) rather than rejected
outright, exactly as designed.

**Conclusion: the prefilter, specifically stage A, is the sole cause of
that 2-site loss — not agent judgment.** Given the chance, the agent
handles entanglement fine. This is a single run, not 3 (it's a targeted
recoverability check, not a scored claim about agent reliability), but
the answer to "is this recoverable" doesn't need 3 runs to be clear: yes.

With stage A off, end-to-end recall against true GT rises to 9/10 (90%)
— the only remaining loss is the grep miss, which no prefilter change
touches.

## Proposal: transitive stage A (shipped 2026-08-18 — see "Shipped" section below for the re-verified numbers; this section is the original measure-before-implementing analysis, preserved as the record of why it was accepted)

**Design:** a file is relevant if it directly matches the relevance
pattern (today's rule), **or** it imports — directly or transitively,
through the repo's own intra-repo import graph — some file that does.
Built with Python's own `ast` module (no import-syntax heuristics) and
resolved to files using the standard "walk up while `__init__.py`
exists" rule that determines each file's true `sys.path` root, so it
stays scoped within one repo without hand-coded per-repo paths.
Implementation: `transitive_relevance_experiment.py` — a standalone
measurement script, not wired into `prefilter.py`.

**Cost, measured on both hosts:**

| host | total .py files | direct-relevant files (today) | transitive-relevant files (proposed) | reduction, today | reduction, proposed |
|---|---|---|---|---|---|
| entangled (OpsMesh) | 33 | 14 | **21** (+7) | 49.3% | **36.2%** |
| diluted (Django + 5 MCP repos + 4 OpenAI repos) | 685 | 13 | **13** (+0) | 90.1% | **90.1%** |

On the entangled host, transitive closure recovers exactly the files
containing both prefilter-dropped GT sites (confirmed directly: both
`tool_catalog.py` and `test_orchestrator_agent.py` are in the recovered
set), plus 5 more files reached only through import chains
(`cli.py`, `server/app.py`, `server/__init__.py`,
`tests/test_client_session.py`, `tests/test_client_session_group.py` —
the last of these is the file containing the grep-missed site, correctly
identified as relevant even though grep itself still won't produce that
candidate). **Real cost: 13 percentage points of reduction, in exchange
for not silently dropping real sites.**

On the diluted host — the same one `measure.py` scores as
`targetB_diluted` — **the transitive closure adds zero files.** None of
Django's 675 files, and none of the files in the 5 MCP repos beyond the
13 already directly relevant, import their way into relevance. Reduction
is unchanged at 90.1%.

**This second number needs an explicit caveat, not a quiet win.** The
diluted host is an *assembly of independent small repos* (5 separate MCP
integrations, one large but separate Django app, 4 separate OpenAI
repos) plus one big pile of unrelated code — it has no single shared
"core" module that most of the codebase imports. That's exactly the
topology where transitive closure stays cheap: import chains are short
and don't fan out. **A real company monorepo with a shared internal
SDK/framework layer that hundreds of files import would be a
structurally different and untested case** — if the directly-relevant
file is (or is imported by) something central like an internal
`http_client` or `service_base` module that most of the codebase already
depends on, transitive closure could plausibly pull in a large fraction
of the repo, and stage A's reduction power could collapse toward zero
on that specific topology. This experiment does not measure that case
and does not claim the 90.1%-unchanged result generalizes to it. If that
turns out to be true on a real shared-core monorepo, stage A would be
providing close to no reduction there, and the reduction work would have
to come from stages B and C alone — worth testing directly before
shipping this change broadly, not assumed from this result.

**Recommendation:** implement transitive stage A. It fixes a proven
correctness bug (two real GT sites silently dropped, confirmed on a host
I did not build and could not have unconsciously protected against) at a
real but bounded cost on the one host tested here, and at zero cost on
this study's existing diluted host. Test it against a single large
shared-core monorepo before treating the "cheap at scale" result as
general.

## Shipped: transitive stage A, re-verified with 9 fresh runs (3 per host)

Implemented in `prefilter.py`'s `stage_a_file_relevance` (an intra-repo
import graph via `ast`, module resolution via the standard "walk up while
`__init__.py` exists" rule) and re-run against all three tested host
types, 3 runs each — not assumed unchanged, freshly adjudicated:

| host | GT | precision | recall (propose) | recall (surfaced) | production misses | reduction |
|---|---|---|---|---|---|---|
| targetB_small | 20 | 100% x3 | 100%/100%/95% | 100% x3 | 0 | 81.1% (unchanged) |
| targetB_diluted | 20 | 100% x3 | 85%/85%/100% | 100% x3 | 0 | 90.1% (unchanged) |
| entangled (this host) | 10 | 100% x3 | 70%/70%/90% | 90% x3 | 0 | **36.2%** (was 49.3%) |

**`tool_catalog.py:46` — the site this whole exercise was about — is
PROPOSE, confidently, in all 3 fresh runs.** Zero regressions: every
previously-correct site on this host (`base.py:16/24`, `context.py:
12/13/20`, `test_server_base.py:31`) is still proposed in all 3 runs, and
the targetB_small/diluted candidate sets are unchanged byte-for-byte from
before the fix (verified directly). The only remaining miss on this host,
in all 3 fresh runs, is the pre-existing grep gap
(`test_client_session_group.py:23`) — a different mechanism, untouched by
a prefilter change by construction, since a file the grep vocabulary
never turns into a candidate never reaches stage A at all.

**One honest new data point, not a regression:** in 2 of 3 fresh runs,
`client/session_group.py:38` (a *different* production GT site — the
`ClientSessionGroup.call_tool()` contract change) landed in
FLAG-UNCERTAIN instead of PROPOSE, on a genuine reading of the migration
facts ("lost its `args` parameter" doesn't specify whether the positional
slot or a keyword-only `args=` was removed). Surfaced, not lost — recall-
surfaced held at 90% both times, same as the run that proposed it
confidently. Recorded transparently: this is the first time this study's
hedge-undercount mechanism has touched production code, where every
prior instance was the same test/mock site. Full cross-study accounting:
`rule_test/recall_failure_audit.md`.

## What this does and doesn't establish

Establishes: dilution (more unrelated code, no structural interaction)
and entanglement (real structural interaction through the host's own
layers) are different regimes with different failure modes. Dilution
didn't break anything in this study (100%/100% at 675-file scale, see
`rule_test/scale_experiment/report.md`). Entanglement breaks exactly one
thing — file-local relevance filtering — via a mechanism (silent,
structurally-blind drop) distinct from anything seen in dilution, while
leaving grep's other failure mode (vocabulary gaps on unanticipated
syntax) and the agent's judgment (100% precision/recall on everything it
was shown, 3/3 runs) both intact.

Does not establish: that 70% is a universal entanglement recall number.
This is one host, built once, by one agent, on one migration spec. It
does establish that the *mechanism* — file-local "no reference found"
being treated as certain irrelevance — is real, reproducible (2 runs
diagnostic-confirmed the same 2 sites), and not something I introduced by
knowing what to avoid.
