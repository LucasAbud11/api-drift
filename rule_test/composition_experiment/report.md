# Composition experiment: grep-for-recall + agent-for-precision

Tests whether composing the two detectors' opposite failure modes —
grep is exhaustive by construction (100% recall, precision irrelevant);
the agent hit 100% precision in every prior experiment but lost coverage
under dilution (`scale_experiment/report.md`, `cluster_diagnosis.md`) —
eliminates the coverage ceiling. Pipeline: (1) grep produces a candidate
set tuned purely for coverage; (2) the agent adjudicates every candidate
into PROPOSE / FLAG-UNCERTAIN / REJECT using the Option-1 (name-
impersonation) and Option-2 (test/mock-path floor) mandatory routing
rules approved in the prior turn — it does not search; (3) score against
the corrected 20-site GT. Run 3x at small scale (the 5 repos alone) and
3x on the diluted 675-file host.

## Result: the coverage ceiling disappeared, cleanly, at both scales

| scale | candidates | proposed-only recall | precision | surfaced rate | closed-world violations |
|---|---|---|---|---|---|
| small (3 runs) | 118 | **60/60 = 100%** | **60/60 = 100%** | 100% | 0 |
| diluted (3 runs) | 214 | **60/60 = 100%** | **60/60 = 100%** | 100% | 0 |

Every one of the 6 runs independently reached the identical split: 20
PROPOSE (all 20 GT sites, correctly), 1 FLAG-UNCERTAIN (the one
genuinely ambiguous non-GT candidate — `tests/test_jmeter_server.py:12`,
`class FastMCP:`), and the rest REJECT. Zero false positives in any run,
including in the diluted host where 96 of the 214 candidates were
Django's own unrelated code (the `Context`/`get_context`/`cursor`/
`sample` name-collision decoys that make up the bulk of the grep
noise). Zero out-of-contract items (the agent never proposed/rejected
anything outside the list it was given) and zero unadjudicated
candidates (every single item got exactly one verdict) in all 6 runs —
full closed-world compliance, not just close to it.

**This directly answers what was asked.** Recall returned to grep's
level (100%, not just "improved") while precision stayed at the agent's
level (100%), and it did so at both scales identically — dilution had
*zero* measurable effect once the agent's job changed from
search-and-adjudicate to adjudicate-only. Compare to the scale
experiment's own numbers on the exact same host: 100% precision / 85%
recall with search-based auditing, vs. 100% / 100% here with the
candidate list handed over. The three GT sites that were missed 9 times
across 3 dilution runs in the search-based version (`tests/
test_jmeter_server.py:11,21,22`) were confidently and correctly PROPOSED
in all 6 runs here — the mandatory Rule 1 routing didn't even need to
divert them to FLAG-UNCERTAIN; the agent's own confidence, once it
didn't have to also find the lines, was sufficient.

## Adjudication cost

| scale | QAInsights | danilop | m0xai | securityfortech | tonyzorin | django (decoy) | **total** |
|---|---|---|---|---|---|---|---|
| small | 14 | 13 | 59 | 24 | 8 | — | **118** |
| diluted | 14 | 13 | 59 | 24 | 8 | 96 | **214** |

Going from small to diluted scale didn't change the cost of the real
signal at all (118 real candidates either way, since the grep vocabulary
is repo-scoped and the 5 target repos are identical files at both
scales) — it added 96 pure-noise candidates from Django. That's the
actual "dilution" this pipeline pays for: not more true positives to
find, just more distractors to correctly dismiss. 214 candidates,
adjudicated exhaustively and correctly in a single pass, in every run.

**Does mechanism B reappear if the candidate list gets large enough?**
Not tested here, and that's a real limitation, not a footnote. 214 is
the number this specific host and vocabulary produced — it is not a
stress test of the hypothesis raised going in ("if grep hands it 500
candidates... mechanism B may just reappear in a different place"). The
result above shows 214 flat candidates, all addressed correctly, is
comfortably within whatever the adjudication budget actually is. It does
not show where that budget runs out. A host built specifically to push
the candidate count into the many hundreds or low thousands (a coverage-
tuned vocabulary run against something the size of the full Django repo,
or a vocabulary with more generically-matching terms) would be the next
test if this number needs pinning down before relying on the pipeline at
real-world monorepo scale.

## What this does and doesn't establish

Establishes: search and adjudication are separable, and separating them
removes the specific coupling that produced mechanism B in the scale
experiment (the same reasoning pass being asked to both locate every
relevant line across a large host *and* individually justify a verdict
on each one — evidence for the latter crowding out coverage of the
former is exactly what `cluster_diagnosis.md` found: content read into
context, never converted into an output line). Handing the search step
to a mechanical, exhaustive tool and reserving the LLM strictly for
judgment removes that coupling entirely, at least at the scale tested
here.

Does not establish: (1) an adjudication-volume ceiling — see above; (2)
anything about entanglement — this pipeline still hasn't been tested
against a host where the target library's own shapes are woven through
the host's code (subclassed `Context`, wrapped SDK objects, re-exported
symbols), which is the next experiment; (3) that the grep vocabulary
used here generalizes to a real migration where the breaking-change
vocabulary isn't already known as precisely as it is in this study's
synthetic Target B — coverage-tuned grep is only exhaustive relative to
a vocabulary someone had to write, and mis-specifying that vocabulary
(missing a term the way the original baseline missed bare `Context`,
see `rule_test/original_session_recovered/grep_baseline_command.sh`'s
own comment) reopens exactly the recall gap this pipeline is designed to
close. The grep step's own recall is doing real work here and depends on
getting that vocabulary right.
