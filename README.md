# api-drift

A study of whether an LLM agent finds code broken by a real SDK
migration more reliably than grep — and generates the fix.

## The question, and the short answer

On recall, grep already keeps pace with the agent — both find nearly
everything a vocabulary covers, itself a real finding. Where they
diverge is precision: grep can't tell a look-alike from a real break, so
it proposes a pile of garbage alongside every true hit; the agent
doesn't. The pipeline exploits that split, not better search: grep
handles what it can't fail at, exhaustive search; the agent handles what
it can't fail at, judging what grep found — 100% precision on every host
tested.

## Findings worth your time

- **The first clean result was circular.** An early run put the agent
  ahead of grep on precision, but the fix was validated against a
  dataset built to guarantee success. Redone with fresh agents — the
  effect vanished.
- **A missing spec sentence, not a reasoning failure, explained a run of
  false positives.** The original prompt, recovered from disk, was
  silent on one counting question; closing it erased the same false
  positives across 27 fresh runs.
- **A failure mode appeared only at scale.** Diluting the search space
  with 675 unrelated files held precision at 100% but dropped recall to
  85% on a repeatable cluster, read in full but never turned into a
  verdict. Separating search from judgment eliminated it.
- **Ground truth was wrong twice**, and each correction had to survive a
  real test run — settled by migrating a disputed site and running the
  tests, not by arguing.

## Architecture

Three stages: grep searches exhaustively, limited only by its
vocabulary; a deterministic, LLM-free prefilter cuts candidates, only on
structural proof of irrelevance; only then does an LLM adjudicate the
fixed list, one verdict each. A fourth stage turns each confirmed site
into an exact fix or a decline, verified against each host's tests.

## What this is not

Research apparatus, not a runnable tool — no CLI, no packaging; nothing
to reproduce a result but reading the scripts. Two migrations, one SDK
family each, one language. Test/mock code is the recurring weak spot —
where the 90–100% recall range comes from: failure mechanisms
concentrate there, out of proportion to their share of ground truth,
pulling the worst case to 90% on the hardest host.

Full methodology: **[REPORT.md](REPORT.md)**. For raw per-run output,
browse `rule_test/`.
