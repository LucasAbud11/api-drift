# Blind vocabulary experiment: is the composition result an artifact of insider knowledge?

The composition experiment's 100%/100% result rested entirely on a grep
vocabulary I hand-built with full knowledge of ground truth — including a
bare `Context` term added specifically *because* I knew about the
Django decoy. That's not the production condition. This experiment
replaces that vocabulary with one derived blind: a fresh agent given
*only* the same "official migration guide" text the study has used
throughout (the verbatim breaking-change facts block, no counting
convention, no task framing, no output contract, no knowledge this is a
study at all) and told to write a coverage-tuned `grep -E` vocabulary
for that guide alone. No repo access, no tool use — a pure text-reasoning
task, exactly what a real developer facing a changelog would do.

## The headline number: zero structurally invisible sites, both targets, both scales

| scale | candidate-set recall (grep alone) | end-to-end recall | precision |
|---|---|---|---|
| Target A, small (13 GT) | **100%** | **100%** | **100%** |
| Target A, diluted (13 GT, 685-file host) | **100%** | **100%** | **100%** |
| Target B, small (20 GT) | **100%** | 98.3% (59/60 across 3 runs) | **100%** |
| Target B, diluted (20 GT, 1121-candidate host) | **100%** | **100%** | **100%** |

**The blind vocabulary's candidate set contains every one of the 33 total
GT sites (13 + 20) across both targets, at both scales.** Nothing is
structurally invisible in this study — every real site a developer
reading only the public guide would need to find is, in fact, findable by
a grep vocabulary derived from that guide alone. The one non-100%
end-to-end number (Target B small, 98.3%) is not a candidate-set gap —
it's a single run (of 6 total Target B runs) where the agent adjudicated
one genuine GT site (`tests/test_jmeter_server.py:11`, a Rule-1 module-
impersonation anchor) into FLAG-UNCERTAIN instead of PROPOSE. That site
was still surfaced, not silently lost — surfaced rate is 100% in every
run, every scale, both targets, no exceptions.

**This is the honest answer to "which sites are unrecoverable in this
architecture": zero, in this study.** That's a real finding, not a
foregone conclusion — it was not guaranteed going in, and the
vocabulary-diff section below shows *why* it held for one target and had
to work harder for the other.

## Vocabulary diff: where blind and hand-tuned differ, and why

**Target A (openai v0.x→v1.x): blind and hand-tuned are nearly
identical.** Both vocabularies enumerate the same 10 namespaces
(`ChatCompletion`, `Completion`, `Embedding`, `Image`, `Audio`,
`Moderation`, `File`, `FineTune`, `Model`, `Engine`) and the same 5 auth
attributes (`api_key`, `api_base`, `organization`, `api_version`,
`proxy`). The blind version added one thing the hand-tuned original
recovered baseline didn't have: a generic `openai\.[A-Z]\w*\.\w+`
catch-all, explicitly justified by the guide's own text ("ANY
`openai.<Namespace>.<method>(...)` call... is broken" — a template, not
just the ten listed examples). Candidate-set size at small scale: exactly
13 — identical to GT, zero slack in either direction, at both scales.
**Why they converge:** every term in Target A's guide is already
qualified by an `openai.` prefix. There is no bare, generic identifier to
derive from this guide — "ChatCompletion" alone means nothing outside
`openai.ChatCompletion`, so a faithful vocabulary stays naturally scoped
no matter who derives it.

**Target B (MCP v1→v2): blind is dramatically broader — 587 vs. 118
candidates at small scale (5x), 1121 vs. 214 at diluted scale (5x).**
The overlap is substantial (both include `FastMCP`, bare `Context`,
`ClientSession`/`StdioServerParameters`/`stdio_client`, `McpError`,
`.elicit(`/`.sample(`/`.list_roots(`) — bare `Context` in particular was
derived independently and correctly by the blind agent from the guide's
own line ("including `Context` if imported from that path"), not copied
from foreknowledge of the decoy. The difference is entirely in terms the
blind vocabulary added that the hand-tuned one never had:

- `message=`, `data=`, `extra=`, `.debug(`, `.info(`, `.warning(`,
  `.error(` — derived from fact 3's `.log()` parameter rename and the
  four logging methods it names. These are bare Python keyword-argument
  and method names with no qualifying prefix anywhere in the guide's own
  text, so a faithful reading can't scope them down without inventing a
  qualifier the guide never states.
- `args=`, `timedelta`, `sampling_capabilities`, `roots_list_supported`
  — same pattern, derived from fact 5's client-SDK parameter changes.
- Two terms the hand-tuned vocabulary had that blind correctly dropped:
  the decorator syntax (`@mcp.tool(`, `.add_tool(`, etc.) — fact 4
  explicitly states these are *unchanged*, and the blind agent reasoned
  it shouldn't derive search terms from a fact that says nothing is
  broken there; and bare `httpx` — fact 6 explicitly carves out
  unrelated application-level httpx usage, so blind narrowed to
  `httpx\.AsyncClient|httpx\.Auth`, the two constructs the guide actually
  says get passed into SDK functions.

**Why the asymmetry:** Target B's guide, unlike Target A's, describes
several breaking changes as bare parameter/method names on generic-
sounding objects (`extra=`, `data=`, `cursor=`, `args=`, `.info()`,
`.error()`) rather than always through an `mcp.`-qualified path. Any
vocabulary faithfully covering those facts — blind or not — will match
enormous amounts of unrelated code, because parameter names like `data=`
and methods like `.error()` are common Python idioms, not MCP-specific
tokens. This is a property of how this guide is written, not of the
deriving agent's skill: the same asymmetry would recur against the real
public MCP or OpenAI migration guides to whatever extent their own
prose leans on generic vs. namespace-qualified language.

## Adjudication cost: this is what actually pushes toward the untested volume question

| scale | candidates | of which noise (non-GT) | flag_uncertain (Rule 2 test-path floor) |
|---|---|---|---|
| Target A, small | 13 | 0 | 0 |
| Target A, diluted | 13 | 0 | 0 |
| Target B, small | 587 | 567 | 74-77 per run |
| Target B, diluted | **1121** | **1101** | 74 per run |

Target B diluted's 1121 candidates is the first time this study has
actually landed inside the volume range the prior composition report
flagged as untested ("if grep hands it 500 candidates on a large host...
mechanism B may just reappear"). It didn't reappear on recall (100% in
all 3 runs) — but it did surface a new, previously-unseen operational
failure mode: **two of the three Target B diluted runs failed outright
mid-task** (one hard server error, one silent truncation at 569/1121
candidates with no continuation), and a third run that did complete
successfully dropped the `snippet` field from all 1121 entries as a
side effect of switching to a compact-TSV internal workflow to manage
the volume — caught by the same hardened validator built for this study,
and repaired by backfilling from the (independently verified) candidate
list rather than silently passed through. All three defects were
concentrated in the largest-candidate-count condition and did not occur
at any smaller scale. **The adjudication-volume ceiling this study set
out to find was not a recall ceiling — every run that finished was
accurate — it was a completion-reliability ceiling: single-shot output at
this size has a real, measured failure rate (2 of 5 attempts before
success, for run2; 1 of 2 for run3) that a production pipeline would
need to design around (batching, incremental persistence, retries) well
before recall itself becomes the limiting factor.**

## Pipeline hardening note

Every number above passed through the same `validate_run_file()` used
throughout this study. It caught a real defect this time — not a
contrived test case — when one Target B diluted run's compact-TSV
workflow silently dropped `snippet` from all 1121 entries. The fix
(backfilling from the independently-generated candidate list, which
carries the literal source text grep itself captured, not agent
judgment) was verified to have zero unmatched entries before being
accepted. Two other runs failed outright (a hard API error, a silent
truncation short of 1121 candidates) and were not patched or
reconstructed — they were re-run from scratch, consistent with this
study's standing policy that incomplete detector output is never
treated as if it were complete.
