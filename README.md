# api-drift

A study of whether an LLM agent finds code broken by a real SDK
breaking-change migration more reliably than grep — and generates the fix.

## The question, and the short answer

Grep either over-matches or under-matches a breaking change, with no way
to know which in advance. Can an agent reliably tell two look-alike lines
apart — a type annotation that's fine versus an import that's broken?
Yes: a pipeline hitting 100% precision and 90–100% recall on every host
tested, plus a fix stage that proposes exact fixes and declines the rest.

## Findings worth your time

- **The first clean result was circular.** An early run showed the agent
  ahead of grep on precision, but the fix was tested against a dataset
  reconstructed to guarantee success. Redone with fresh agents — the
  effect vanished.
- **A missing sentence in the spec, not a reasoning failure, explained a
  run of false positives.** The original prompt, recovered from disk, was
  silent on one counting question; closing that gap eliminated the same
  false positives across 27 fresh runs.
- **A failure mode appeared only at scale.** Diluting the search space
  with 675 unrelated files held precision at 100% but dropped recall to
  85% on one repeatable cluster — content read in full but never turned
  into a verdict. Separating search from judgment eliminated it.
- **Ground truth was wrong twice**, and each correction had to survive a
  real test run, not an argument — one disputed site was settled by
  migrating it and running the tests.

## Architecture

Three stages: grep searches exhaustively, limited only by its vocabulary;
a deterministic, LLM-free prefilter cuts candidate volume, dropping a
site only on structural proof it's irrelevant, never on absence of
evidence; only then does an LLM adjudicate the fixed list it's handed,
one verdict each, nothing left to search for. That split is the fix —
combined search-and-judgment is what broke at scale. A fourth stage turns
each confirmed site into an exact fix or a decline, verified by running
each host's tests before and after.

## What this is not

Research apparatus for one question, not a runnable tool — no CLI or
packaging; reproducing results means reading the scripts by hand. Two
migrations, one SDK family each, one language. Test/mock code is the
one recurring weak spot: several failure mechanisms concentrate there,
out of proportion to its share of ground truth.

Full methodology and every number: **[REPORT.md](REPORT.md)**.
