# Batch reliability: 5 runs on the reduced candidate set, plus idempotent resume

The diluted Target B pipeline was unreliable at 1121 candidates (2 of 3
first attempts failed outright — one hard server error, one silent
truncation at 569/1121). The candidate-reduction stage above cuts that
same host down to 111 candidates with zero GT loss. This tests whether
the reduction alone fixes reliability, and ships the idempotent-resume
infrastructure the user asked for regardless of the answer.

## Result: 5/5 clean on first attempt

| attempt | schema-valid | full 111/111 coverage | closed-world violations | recall | surfaced |
|---|---|---|---|---|---|
| 1 | yes | yes | 0 | 95.0% | **100%** |
| 2 | yes | yes | 0 | 100% | 100% |
| 3 | yes | yes | 0 | 100% | 100% |
| 4 | yes | yes | 0 | 100% | 100% |
| 5 | yes | yes | 0 | 100% | 100% |

**5 of 5 independent attempts completed cleanly on the first try** — no
retries needed, no server errors, no truncation. Compare directly to the
same host at full (1121) candidate volume: 2 of 3 first attempts failed
outright there. The only variable changed between those two experiments
is candidate count (1121 -> 111); same host, same spec, same rules,
same model. **The reduction stage is what fixed reliability — not
because it made the task semantically easier, but because it made the
single-shot output short enough to not hit whatever length/duration
threshold was causing the failures.** Attempt 1's one recall dip (95%)
is not a reliability failure — it's the same kind of judgment variance
seen throughout this study (one GT site landed in FLAG-UNCERTAIN
instead of PROPOSE), and it was still surfaced, not lost: 100% surfaced
rate in all 5 runs, no exceptions.

## What this does and doesn't establish

Establishes: at 111 candidates, this pipeline is reliable enough that 5
consecutive independent runs needed zero retries. It does not establish
that 111 is some kind of hard ceiling below which failures never happen,
or that a future target's reduced candidate count will always land this
low — Target A's guide reduced to 9, Target B's to 111, and there's no
guarantee a real-world migration guide's own vocabulary breadth won't
still leave a host in the hundreds after filtering. That's exactly why
the chunking/idempotent-resume infrastructure below was built regardless
of the clean 5/5 result, not conditionally on failures actually showing
up here.

## Idempotent, chunked pipeline (built, not conditionally-triggered)

`pipeline.py` implements the state machine half of a resumable
adjudication run:

- **Work unit is one chunk** (default 40 candidates), not the whole run.
  A run at N candidates becomes `ceil(N/40)` independent chunks.
- **A chunk counts as done only if its output file exists, validates
  through the same hardened `validate_run_file()` used throughout this
  study, AND its adjudicated (file, line) set exactly matches what that
  chunk was given** — a stale, corrupt, or partial file is never
  mistaken for a completed one.
- **Resuming a run calls `pending_chunks()`**, which returns only the
  chunks that aren't done. A partial failure costs exactly the chunks
  that failed to persist — completed chunks are never re-dispatched,
  never re-billed, never re-risked.
- **Writes are atomic** (`.tmp` file, validated, then `os.replace`) so a
  process that dies mid-write never leaves a corrupt file that looks
  done.
- **`merge()`** combines all chunks' buckets into one final result and
  runs the same validator on the combined output before calling the run
  complete.

`reliability_demo.py` verifies this against real data, not a synthetic
example: it takes one of the 5 already-completed reliability runs
(attempt 3), reorganizes its actual verdicts into 3 chunks the way
`ChunkPlan` would, simulates chunk 1 failing to persist (the same
failure shape actually observed twice in this study), confirms
`status()` reports only chunk 1 as pending, resumes by supplying just
that chunk, and confirms the merged result covers the identical
(file, line, bucket) set as the original single-shot run — resume after
partial failure reproduces the same output, not a different one.

## What "tool, not demo" means concretely here

Before this: a failed 1121-candidate run had no recoverable state —
the only option was re-running the entire 1121-item adjudication from
zero, at full cost, with the same failure risk on the retry. After
this: a failure costs one ~40-candidate chunk, the other chunks' work
and spend are preserved on disk, and re-invoking the same command
finishes the run rather than restarting it. That distinction — cost of
failure scales with chunk size, not run size — is what was asked for,
and it now holds regardless of whether reduction alone keeps producing
5/5 reliability on the next target this gets pointed at.
