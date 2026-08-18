# Testing the "definition/import vs. usage" rule (revision 2)

**Revision 2 supersedes revision 1's agent-side numbers.** Revision 1
reconstructed "agent output" as ground truth ∪ the one documented FP
mechanism from `results.md`, then applied a rule targeting that exact
mechanism and reported 100% precision. That was flagged, correctly, as
circular: reaching 100% was guaranteed by the construction, not measured.
This revision replaces that reconstruction with 9 freshly launched,
walled-off detection agents, run from scratch and scored on their actual
output. It changes the answer.

Script: `rule_test/analysis.py`. Full run: `rule_test/raw_run_output.txt`.
Migration specs given to the agents: `rule_test/specs/`. Every agent's raw
proposed-site list, persisted before any scoring: `rule_test/agent_runs/`.

## What was re-run

9 fresh `general-purpose` agents, each launched cold with no memory of this
conversation, one per repo (4 Target A / OpenAI, 5 Target B / MCP), each
given:
- The migration spec for its target (`rule_test/specs/target_a_openai_migration_spec.md`
  or `target_b_mcp_migration_spec.md`), reconstructed by the orchestrator
  from the confirmed-changed/confirmed-unchanged facts already stated in
  `ground_truth.md` and `methodology_notes.md` — files the agents
  themselves never saw.
- Read access scoped to exactly one repo directory, with an explicit
  instruction never to open `ground_truth/`, `methodology_notes.md`,
  `results.md`, `rule_test/`, or any other repo besides their own.
- A required JSON output format (`proposed_sites` + `considered_and_rejected`,
  each with file/line/snippet/reason), so results were unambiguous to
  parse and score.

Each agent's full JSON response was written to
`rule_test/agent_runs/<repo>.json` immediately on return, before any
comparison against ground truth.

## Result 1: the real agents do not reproduce the original 55.3%

| | Target A | Target B |
|---|---|---|
| GT sites | 13 | 21 |
| Real agent proposed | 13 | 21 |
| Real agent recall | **100%** (13/13) | **100%** (21/21) |
| Real agent precision | **100%** (13/13) | **100%** (21/21) |

Zero false positives, on either target, across all 9 repos. Every one of
the 9 agents was explicitly offered the chance to make the `ctx: Context`
mistake — m0xai has 14 such annotations, danilop has 3 — and every agent
rejected all 17 of them explicitly, with reasoning essentially identical
across independently-run agents: *"Context class keeps its own name in v2
(only its import path changes, which is already captured at the import
line). No edit needed at this usage site."* That's from `agent_runs/
danilop_MCP2Lambda.json`; `agent_runs/m0xai_trello-mcp-server.json` and
`agent_runs/tonyzorin_youtrack-mcp.json` say the same thing in their own
words. Full recall/precision, per-class, both targets, is in
`raw_run_output.txt` under `AGENT raw (REAL, fresh run)`.

**This is not a rerun of the original conditions — it's a different, and
probably easier, spec.** The Target B spec's item 3 states outright:
*"Context keeps its own name... nothing else about Context... changes."*
That sentence was written by reading `ground_truth.md`'s own explanation
of why the 17 sites were false positives, and putting the resolution
directly into the spec the fresh agents received. The original agents may
well have been given something vaguer on this exact point, or been left to
infer it — `results.md` describes the original mistake as agents reasoning
themselves into it "with explicit reasoning in the transcript," which
reads like a plausible-but-wrong inference filling a gap, not a spec
contradiction. Since the original spec text was never persisted anywhere,
this can't be settled directly. Two explanations are both consistent with
what's observable, and this run cannot distinguish them:

1. **Spec-hindsight effect**: my Target B spec — built after already
   knowing the failure mode — is strictly more explicit than whatever the
   original agents saw, and that explicitness is the entire reason the
   mistake didn't recur.
2. **Run-to-run variance**: even under an equivalently-scoped spec, an
   agent's choice to flag or not flag an ambiguous case like `ctx: Context`
   is not perfectly stable across runs, and the original 55.3% reflects one
   draw from that variance rather than "the agent's" typical behavior.

Either way, the practical consequence is the same: **the rule has nothing
to fix on this data.** Applying `rule(strict)` to the real agent output
changes nothing — 100%/100% in, 100%/100% out, because there were no
`ctx: Context`-style false positives left to remove. See `AGENT(REAL) +
rule(strict)` in `raw_run_output.txt`. `rule(naive)`, applied for
completeness, still collapses recall exactly as before (Target A 100%→0%,
Target B 100%→42.9%) — that failure mode doesn't depend on which agent
output you feed it, since it's a property of the rule's own
underspecification, not of what mistakes happen to be present in the input.

The superseded revision-1 reconstruction and its "55.3%→100%" result are
kept in `analysis.py` (`AGENT_A_RECONSTRUCTED`/`AGENT_B_RECONSTRUCTED`) and
printed in the `SUPERSEDED` section of `raw_run_output.txt`, for audit —
not as a finding.

## Result 2: the grep side is unchanged, and the "drift" is explained

Grep is a pure function of the repo tree and a fixed vocabulary — re-run
twice in-process in this session, it produces byte-identical candidate
sets both times (`DETERMINISM CHECK` at the bottom of
`raw_run_output.txt`: `True`/`True`). So "same command, different numbers"
doesn't describe what happened. What actually happened: **the original
grep run's script was never persisted either** (same gap as the agent
output) — `results.md` only recorded its aggregate counts (96 proposed,
21 correct, precision 21.9%). Revision 1 wrote an independent
reconstruction of the vocabulary from the documented decoy list, and it is
measurably broader than whatever produced the original 96. Reconciling
exactly, category by category, against my own script's output
(`rule_test/analysis.py`, `VOCAB_B`):

| Class | Original (documented) | Mine | Delta | Why |
|---|---|---|---|---|
| decorator/registration | 43 (18 secops + 6 QAInsights + 18 m0xai + 1 tonyzorin) | 47 (18 + 6 + **22** + 1) | +4 | `grep -c '\.add_tool('` against the live m0xai file returns **22**, not 18 — verified directly (`repos/m0xai_trello-mcp-server/server/tools/tools.py` has 22 `mcp.add_tool(...)` calls: 4 board + 5 list + 5 card + 8 checklist). The original tally undercounted this repo by 4; the repo itself hasn't changed (its GT lines still match exactly). This is a documented-record correction, not a re-run discrepancy. |
| test/mock | 4 (0 FP) | 6 (2 FP) | +2 | My `inputSchema` token also matches `tests/docker/test_mcp_docker.py`'s two dict-key reads of a raw JSON-RPC response (`attachment_tool["inputSchema"]`) — real text, real match, but (per the tonyzorin agent's own correct rejection) not an SDK object attribute. Not evidenced as part of the original decoy list. |
| client-side | 8 (7 FP) | 9 (8 FP) | +1 | One extra `StdioServerParameters`/`ClientSession` incidental match in `mcp_client_bedrock/mcp_client.py`; same family of token the original documented finding already 7 of. |
| literal | 41 (25 FP, 4 of them the documented httpx-collision) | 79 (63 FP) | +38 | The big one. My vocabulary added `ctx.error(`/`ctx.info(`/`mcp.types` as grep targets (20 FP) and matched `Context`/`httpx` as **bare, unscoped word-boundary tokens** across entire files rather than import-adjacent occurrences (18 + 22 = 40 FP between them, including one docstring hit on the phrase "Model **Context** Protocol"). None of the httpx/ctx.error/ctx.info/mcp.types decoys are mentioned anywhere in `results.md`'s breakdown of grep's FP sources — only the httpx CLI-tool collision (4 FP) is documented, and my run reproduces that specific one exactly. The rest is vocabulary I added, on the theory that a "full vocabulary grep across all 13 categories of the confirmed migration guide" (`methodology_notes.md` step 4) would include the guide's own confirmed-unchanged list as literal grep targets too. That's a defensible reading of the instruction, but it's evidently broader than what the original session actually ran. |

**141 vs. 96 is not two runs of the same script disagreeing — it's two
independently-written grep vocabularies, of different breadth, applied to
the same (unchanged, verified) repos.** One real accounting error in the
original write-up (m0xai's add_tool count) explains part of the gap; the
rest is a genuine methodology difference (my vocabulary is broader,
particularly around bare-word `Context`/`httpx` matching and three decoy
tokens — `ctx.error`, `ctx.info`, `mcp.types` — the original evidently
didn't grep for at all). Neither number is "wrong" in the sense of a bug;
they're answers to two different specifications of "naive vocabulary
grep," and only mine is reproducible from a script that's actually on
disk. Precision moves accordingly: 21.9% (original, undocumented script)
vs. 14.9% (mine, `rule_test/analysis.py`, deterministic) — both are real
measurements of *a* grep baseline, not the same baseline measured twice.

Applying `rule(strict)` to my grep output: 14.9% → 17.1% (120 FP → 102 FP,
18 removed — the same `Context`-annotation mechanism, independently
reproduced on grep's side, filtered safely with zero recall cost). This
number is unchanged from revision 1, since it never depended on the
agent-side reconstruction bug.

## Answer to the actual question, updated

**Whether the agent's precision advantage is "durable" cannot be assessed
from this data** — not because the rule failed, but because the real
fresh agent run has no precision problem for the rule (or anything else)
to fix. The original 55.3%/17-FP result, the entire basis for testing this
rule in the first place, did not reproduce under an independent re-run.
That could mean the original number was a noisy single draw, or it could
mean this run's spec quietly handed the agents the fix in item 3 — this
test cannot tell those apart, and says so rather than picking the
flattering read.

What *is* now solid, because it's grep-only and grep is deterministic and
disclosed in full:

- Grep's own precision problem is not primarily the `Context`-annotation
  mechanism. That mechanism accounts for at most 18 of grep's 120 raw
  false positives. The other 102 are decorator/registration overmatch (47,
  0% precision) and keyword collisions (`httpx`, `ctx.error`/`ctx.info`,
  bare `Context` matches) that require knowing whether a *specific* API
  surface actually changed — a different kind of judgment than "is this an
  import or a usage," and one this rule was never built to supply.
- The rule, applied to grep, recovers about 2 points of precision (14.9%→
  17.1%) out of whatever the true agent-vs-grep gap turns out to be. It is
  not close to sufficient to make grep competitive on its own.
- The naive (underspecified) reading of the rule remains actively
  dangerous on both grep and agent output, independent of which agent data
  you use as the "before": it deletes 100% of Target A's ground truth and
  ~43-57% of Target B's, silently.

**What this run adds that revision 1 didn't have**: real evidence that
the original 55.3% Target B agent-precision figure — the one number this
entire rule was invented to fix, and one of the two headline numbers
`results.md` uses to argue for the agent over grep — does not reproduce
under an independent, walled-off re-run with a comparably-scoped spec. If
that number is this sensitive to spec phrasing or run-to-run variance, it
was never a safe thing to build a filter around in the first place, and
probably shouldn't be treated as a stable characterization of "how the
agent behaves" until it's been observed more than once.

## What would actually settle this

1. The original migration-spec text, if it exists anywhere outside this
   repo (chat history, a different working directory, a paste buffer) —
   would resolve explanation (1) vs (2) above directly.
2. Multiple independent fresh runs (n≥3–5) of the same 9 agents against
   the *same* spec used here, to see whether 100%/100% is stable or
   whether the `ctx: Context` mistake reappears some fraction of the time
   — turning "run-to-run variance" from a hypothesis into a measured rate.
3. A grep vocabulary spec written down *before* running it, reviewed
   against the confirmed migration-guide categories, so future comparisons
   don't depend on reconstructing "what grep would naively match" after
   the fact.

None of these were done here; this revision's job was narrower — fix the
specific circularity that was flagged, report what the real data says, and
be explicit about what it still can't answer.

## Revision to `results.md`'s ship recommendation (updated)

The original recommendation — "ship it with one fix first: [this rule]" —
was already narrowed once, in the first update. It's narrowed further now:
the rule itself (correctly scoped, with the renamed-vs-moved-only table)
is real and safe to add — zero recall cost on real data, in both the
reconstructed and the real agent runs, and it independently helps grep's
output too. But its entire justification (a specific 17-site, 48.5%→100%
agent precision problem) has not been shown to be a reproducible property
of the agent worth engineering around; a fresh, comparably-thorough run
had zero instances of the problem. Recommend: keep the rule as a cheap,
provably-safe post-filter (it costs nothing when there's nothing to
filter), but stop citing the 48.5%→100% figure as the reason to ship it —
that figure has not reproduced.

## File manifest (everything referenced above, on disk)

- `rule_test/specs/target_a_openai_migration_spec.md`,
  `target_b_mcp_migration_spec.md` — exact specs given to the fresh agents.
- `rule_test/agent_runs/*.json` — all 9 agents' raw proposed/rejected
  sites, one file per repo, written before scoring.
- `rule_test/analysis.py` — grep vocabulary + candidate generation, ground
  truth transcription, both rule implementations (strict/naive), scoring,
  determinism check, and the superseded reconstruction (kept, clearly
  labeled, not used for conclusions).
- `rule_test/raw_run_output.txt` — full output of the script above, all
  targets/methods/rule-versions/classes.
