# Ablation results, the real root cause, and a harder benchmark

Three things, in the order requested: the corrected framing of what the
ablation actually tested (N=2, not N=5), what really caused the original
17 false positives (recovered from disk, not inferred), and a proposal for
un-saturating the benchmark.

## 1. The real N

3 of the 5 Target B repos — tonyzorin, QAInsights, securityfortech — have
**zero** `ctx: Context` sites in their source at all (confirmed by direct
grep against the live repos, and by every one of the 30 agent runs against
them independently reporting zero). Neither ablation condition can produce
the effect being tested there; those 30 runs (both conditions × 5 runs ×
3 repos) are a recall/no-noise sanity check, not evidence about the
ablation's actual question. **The ablation's real N is 2 repos — m0xai (14
`ctx: Context` sites) and danilop (3) — each run 5× per condition, so 20
runs total that could show an effect.**

Scored (`rule_test/ablation/score_ablation.py`,
`ablation_scored_output.txt`):

| Repo | Condition A (5 runs) | Condition B (5 runs) |
|---|---|---|
| m0xai (5 GT sites, 3 of them the ambiguous `Context` import class) | 5/5 recall, 5/5 precision, every run | 5/5 recall, 5/5 precision, every run |
| danilop (3 GT sites, 1 ambiguous) | 3/3, every run | 3/3, every run |

Zero variance, zero false positives, in both conditions, across all 20
runs. Removing the "Context keeps its own name" sentence did not reproduce
the mistake even once.

## 2. The real root cause (recovered from disk, not inferred)

Per your instruction, I checked git history and session storage for what
actually differed between the original run and every run since. This
resolved concretely — the original session's full transcript exists on
disk and was recoverable.

**How it was found and confirmed genuine:** `~/.claude/projects/-Users-lucasabud-Projects-api-drift/804c3d31-60cd-454c-9433-1a6065725f24.jsonl` opens with the literal project-kickoff message ("I'm building a tool that detects breaking changes..."), and the two agent results extracted from it (m0xai: 19 raw findings = 5 real + 14 `ctx: Context`; danilop: 6 raw findings = 3 real + 3 `ctx: Context`) reproduce `results.md`'s exact reported counts. Its last commands are the literal `git commit` for `a940505`. This is not a reconstruction — it is the original run.

**What was checked, and what it settled:**

| Candidate variable | Finding |
|---|---|
| Model | `claude-sonnet-5` in both the original orchestrator and this session's agents — identical. |
| Agent spawn mechanism | `subagent_type: general-purpose`, no `model` override, in both — identical input shape (`description`/`subagent_type`/`prompt` only). |
| Orchestration structure | **Different, but not causal**: the original launched its 9 agents one at a time, sequentially (each a separate assistant turn, waiting for completion before the next `Agent` call); this session launched all 9 (and later all 50) in parallel batches. Each subagent is independently sandboxed regardless of concurrency, so this shouldn't affect subagent output — noted for completeness, not offered as the explanation. |
| **Spec content** | **This is it.** The recovered original Target B spec (`original_session_recovered/target_b_original_spec.txt`) is 9 dense numbered items — module rename, 11 separate camelCase→snake_case field renames, detailed `Context.log()`/`extra=`/`client_id`/`get_context()` behavior, a decorator-unchanged-for-high-level-but-changed-for-a-different-low-level-`Server`-class distinction, five separate client-SDK changes, an `httpx`-internals carve-out, an `McpError`→`MCPError` rename, and a `NoBackChannelError` behavior note. My reconstruction (built afterward, from `ground_truth.md`'s own description of what's confirmed changed/unchanged) was 6 much simpler items. The original is real-migration-guide dense; mine was a cleaned-up digest. |

**The specific mechanism, in the original agents' own words** — not spec ambiguity about whether `Context`'s *name* changes, but a *counting-convention* question the original spec (like mine) never addresses either way: does a line that only fails because an earlier line in the same file is broken count as its own separately-broken site? The original spec's item 1 explicitly resolves this for `FastMCP` ("any type annotation referencing `FastMCP` is broken") but never says anything, either way, about whether a downstream `Context` reference does. Both original agents reasoned about this explicitly and reached the same wrong-by-ground-truth-convention answer:

> m0xai agent, finding #4: *"Pattern 1 (type annotation referencing the broken `Context` symbol imported above)"*

> danilop agent, finding #3: *"Since Python evaluates parameter annotations at function-definition time... and the import already fails, this name would be unresolved. Flagging as affected via the broken import chain, **though the root cause is line 6**."*

The danilop agent's reasoning is not confused — it is a coherent, technically-defensible argument (import fails → module fails to load → every line "depends on" the fix) that happens to disagree with the counting convention `ground_truth.md` chose (only lines needing an *independent* text edit count; `results.md` already named this "reasoning that the annotation 'depends on' the broken import" — that description was accurate from the start). My reconstructed spec never tested this axis at all: item 3's "Context keeps its own name, nothing else changes" isn't just clarifying the name question, it's an implicit blanket "resolves automatically, no downstream action needed" statement that pre-empts the counting-convention question entirely — in *both* my conditions, since removing that one sentence still leaves a much shorter, much less import-failure-dwelling spec than the original ever was. **I ablated the wrong variable.** The real one — whether the spec states or leaves implicit a rule for transitively-affected lines — was never varied.

**Confirms your prediction, not mine:** if 20/20 clean runs is a genuine reproduction rate and the earlier 55.3% doesn't reproduce because of a coincidence in wording, that's what you called a weak explanation needing a fourth variable — and the fourth variable is real, on disk, and it's spec density/completeness, not a single sentence.

**Grep-drift, now closed with certainty (not reconstruction):** the original session's actual grep command was also recovered (`original_session_recovered/grep_baseline_command.sh`) and re-run verbatim against the same, unchanged repos. It reproduces **21/21 recall, 21/100 precision (21.0%)** — matching the reported 21.9% almost exactly (the ~1-point gap is unexplained and immaterial). Critically: **the real vocabulary never searches for bare `Context` at all.** Checking its 100 raw hits for the string "context" turns up exactly 4 lines — the 4 real `Context`-import GT sites, matched via the `fastmcp` token, not a `Context` token. Applying the strict rule to this real baseline removes **zero** candidates — there is nothing for it to remove, because grep's actual vocabulary structurally cannot produce a `ctx: Context`-annotation false positive. This is a stronger, now-certain version of what the earlier (reconstructed) analysis suggested by inference: the rule's value is agent-specific. Grep's real 79 false positives break down as decorator (24) + `add_tool` (23) + `httpx` (22) + `ClientSession`/`StdioServerParameters`/`stdio_client` (7) + 3 residual `FastMCP` mentions — every one of them a class the rule was never built to touch.

**What's still not recoverable:** nothing material. The one open question (why 100 vs. the reported 96 raw grep hits) is a ~4% gap with no remaining evidence to explain it and no bearing on any conclusion above.

## 3. The benchmark is saturated — 3 ways to fix it, and which one matters most

Every method now scores 100%/100% on this benchmark's easy path (the
reconstructed spec) and the harder path (the real original spec) has
already been run once and produced a real, measurable gap (55.3% vs.
21.9%) — meaning the fix isn't "invent harder cases," it's "stop
accidentally making the test easier than the thing it's supposed to
measure." Three concrete directions, ranked:

**1. Reinstate the real spec as the standard, and stop simplifying it.**
This session's simplified 6-item digest was, it turns out, the accidental
cause of a saturated benchmark: real vendor migration guides are dense,
inconsistent about which edge cases they spell out, and don't converge
into six clean rules. The recovered 9-item original is sitting on disk
right now (`original_session_recovered/target_b_original_spec.txt`) — it's
free, and it's already validated as harder. Every future comparison run
should use it verbatim, not a re-digested version of it.

**2. Scale up fan-out per breaking change.** m0xai's 14 `ctx: Context`
sites in one repo is already the single largest error-producing structure
in the study — a repo with 50-100 downstream consumers of one broken
import (more realistic for a mid-size service with many handler modules)
would turn a binary "did it make this mistake" signal into a graded
precision score with enough range to actually compare methods, instead of
a coin-flip that happened to land on the wrong side once.

**3. Multiple concurrent migrations in one repo.** Real codebases are
usually mid-migration on more than one dependency at a time. A repo
touched by two unrelated breaking changes simultaneously tests whether an
agent correctly attributes each site to the right spec and doesn't leak
one migration's "this is fine" caveats onto the other's decorators/fields
— a failure mode this study's single-migration-per-repo design can't
surface at all.

**Recommendation:** priority order is 1, then 2, then 3. (1) isn't really
optional — it's a correction, since the "easy" version of this benchmark
was never the intended test. But if you're asking which axis most
resembles an actual customer's situation: **(2), codebase scale.** Every
real customer's repo is bigger and messier than these 5-20 file toy
repos, in a way that's true regardless of which SDK they're migrating or
how well-written the vendor's changelog is — whereas (1) is about spec
quality, which varies wildly by vendor, and (3) is a real but narrower
failure mode. Scale is the one dimension where "will this actually work
on my codebase" is currently untested by any of the 9 repos in this
study.

## File manifest (this turn)

- `rule_test/ablation/spec_condition_A.md`, `spec_condition_B.md` — the two
  ablation specs actually used (this session's reconstruction, item 3
  present/absent).
- `rule_test/ablation/runs/condition_{A,B}/{repo}/run{1-5}.json` — all 50
  raw agent outputs, persisted before scoring.
- `rule_test/ablation/score_ablation.py`, `ablation_scored_output.txt` — the
  scoring script and its output.
- `rule_test/ablation/original_grep_B_raw.txt` — the real original grep
  command's output, re-run verbatim against the live repos.
- `rule_test/original_session_recovered/` — the actual original spec, the
  actual original agents' full reasoning, and the actual original grep
  command, extracted verbatim from the recovered session transcript.
