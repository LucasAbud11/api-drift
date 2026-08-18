# Diagnosis: why the sys.modules-stub cluster is missed 3/3 under dilution but only 1/3 (as full misses) at small scale

Question: for the 9 total misses across the 3 dilution runs (all confined to
`QAInsights_jmeter-mcp-server/tests/test_jmeter_server.py:11,21,22`), does the
detector reach those lines and reject them, or does it never surface them at
all? These are different failures — one is judgment, one is search (or, as
the evidence below shows, a third thing that isn't quite either).

## Method

For each of the 3 dilution runs, pulled the actual tool-call history from the
subagent's own transcript (`~/.claude/projects/.../subagents/agent-<id>.jsonl`
— the full JSONL record of every tool call the subagent made, not just its
final answer) and checked: (1) did the agent ever `Read` `test_jmeter_server.py`,
and with what line range; (2) does any intermediate assistant text mention the
specific lines (`fastmcp_mod`, "line 11", "line 21") before the final answer;
(3) what did the final `considered_and_rejected` bucket actually say. Then
compared against the equivalent evidence already on file for the small-scale
`spec_reinstated` QAInsights runs.

## Finding: the file was read in full in all 3 dilution runs — this is not a retrieval failure

| run | Read call on test_jmeter_server.py | file length | lines 11/21/22 in the returned content? |
|---|---|---|---|
| dilution run1 | `Read(file_path=..., limit=60)` | 116 lines | yes (11-22 « 60) |
| dilution run2 | `Read(file_path=...)` (no limit — full file) | 116 lines | yes |
| dilution run3 | `Read(file_path=...)` (no limit — full file) | 116 lines | yes |

Every one of the 9 misses had its own line's exact text sitting in the
subagent's context window at some point. None of the 9 misses is a case
where the detector's search never located the file or never read the
relevant offset. Whatever failed, failed downstream of retrieval.

## Finding: the 9 misses split into two distinct, evidenced mechanisms

**Mechanism A — judgment failure: reached, reasoned about individually, explicitly wrong.**

Dilution run1 rejected all 6 candidate lines in the stub (9, 10, 11, 12,
21, 22) with individual, stated reasoning for each — full coverage, no
gaps. The reasoning for the 3 GT lines:

> line 11: "Creates a fake module object under the old path name for
> testing only; does not import the real mcp.server.fastmcp, so it is
> not broken by its removal."
> line 21: "Assigns the local fake class into the fake module;
> self-consistent regardless of real SDK changes."
> line 22: "Registers the fake module under the old path in sys.modules;
> jmeter_server.py's import resolves against this stub, not the real
> installed package, so this test is unaffected by the real SDK's
> migration."

This is the identical argument shape — "the stub is self-contained,
therefore nothing about it can be broken by the real SDK's migration" —
diagnosed in `spec_reinstated/report.md` as small-scale run3's failure
mechanism, which also achieved full coverage (explicitly rejected all 4
candidate lines, including B8b, with individually stated reasoning) and
was wrong for the same reason: it treats "the stub doesn't consult the
real package" as proof nothing in it needs to change, missing that
`jmeter_server.py`'s corrected import will look up a *different*
`sys.modules` key and a *different* exposed attribute name than the stub
currently provides — the stub isn't broken by the SDK version, it's
broken by the production code around it changing.

Dilution run2 shows the same mechanism on exactly one of its three
misses — line 22 — with near-identical reasoning ("Stubs sys.modules
before importing jmeter_server, so the import always succeeds via the
fake module regardless of the real SDK's version; not broken by the
migration").

**Mechanism B — a third thing, neither judgment nor search: retrieved, never individually addressed, no reasoning trace at all.**

Dilution run2's other two misses (lines 11, 21) and all three of dilution
run3's misses (11, 21, 22) do not appear in `considered_and_rejected`,
`proposed_sites`, or `flag_uncertain` at all. Checked the full
intermediate transcript (not just the final answer) for any assistant
text mentioning `fastmcp_mod`, "line 11", or "line 21" before the final
JSON block: **none exists**. The content was read into context (per the
table above) but never generated an individual verdict of any kind —
not a rejection, not a flag, nothing. This is not "search failure" in
the sense the question posed it (the search *did* find the content) and
it is not "judgment failure" either (there is no judgment on record to
be wrong). It's an attention/synthesis gap during output generation: the
raw material was available and simply didn't make it into the final
per-line accounting.

## This mechanism is new at scale, not a re-weighting of the old one

Zero of the 3 small-scale QAInsights runs show mechanism B. Small-scale
run1 and run2 hit 8/8 (full correct coverage); run3 hit 4/8 but via full
mechanism-A coverage (all 4 candidate lines individually, explicitly,
wrongly rejected — nothing was dropped silently). Mechanism A alone
accounts for 100% of small-scale misses.

Under dilution, mechanism A still exists (4 of 9 dilution misses: all 3
of run1's, 1 of run2's) and is essentially unchanged in argument and
confidence from its small-scale appearance. What's new is mechanism B (5
of 9 dilution misses: 2 from run2, 3 from run3) — a failure type that
never once appeared at small scale. **Dilution's effect on this cluster
is not "the same judgment error happens more often" — it's the
appearance of a second, previously-nonexistent failure mode that now
accounts for the majority of the misses.**

## Circumstantial support: total output size tracks with which mechanism dominates

| run | total items reported (proposed+rejected+flagged, whole host) | mechanism on this cluster |
|---|---|---|
| dilution run1 | 88 | A (full coverage, wrong verdict) |
| dilution run2 | 90 | mixed (A on 1 line, B on 2) |
| dilution run3 | 57 | B (silent on all 3) |

Run3, the run with by far the thinnest total output across the whole
675-file host (57 items vs. ~90 for the other two), is also the run that
shows mechanism B most completely. This is n=3 and not proof of a
dose-response relationship, but it's directionally consistent with a
"the detector's per-item accounting budget doesn't scale with host size"
explanation for mechanism B: on a single small repo, exhaustively
itemizing every borderline line in one file (small-scale run3: 10 items
just for QAInsights) is cheap; spread across 675 files, the same
exhaustiveness would require an output an order of magnitude longer, and
what's actually observed is a shorter output with an unremarked gap
exactly where that exhaustiveness would have been needed.

## Answer

Not one failure — two, and dilution didn't just amplify the existing one,
it introduced a new one that's now the larger contributor (5/9 vs 4/9
misses). Mechanism A (judgment: reached, reasoned, wrong) is the same
failure already characterized at small scale, unchanged in mechanism or
confidence. Mechanism B (retrieved but never individually surfaced, no
reasoning trace) has no small-scale analogue and is the more concerning
of the two for a detector meant to open PRs unattended: mechanism A at
least leaves a wrong-but-legible reason on the record that a reviewer
could catch and argue with; mechanism B leaves nothing to catch — the
site simply isn't in the output, correct or otherwise.
