"""Grep candidate generation. Reads through RepoReader only -- no raw
`open()` on a repo path anywhere in this file. Adapted from the already-
generic rule_test/blind_vocab_experiment/build_candidates.py; same
mechanics, vendored so the packaged tool doesn't import across the
rule_test/ experiment-scratch boundary.
"""
import re


def find_candidates(reader, patterns):
    """patterns: {name: regex_str}. Returns a list of candidate dicts:
    {file, line, snippet, _pattern, _patterns}. `_pattern` records a
    single representative pattern (the first match, by `patterns`'
    iteration order) -- used by guards.check_vocabulary_yield for the
    per-pattern breakdown. `_patterns` records the FULL set of pattern
    names that matched this line, in the same order: a line can satisfy
    several patterns at once (e.g. a call that's both a renamed method
    and inside a fact naming a co-occurring kwarg), and `_pattern` alone
    only ever recorded the first of those -- silently discarding the
    rest. Any consumer that needs to know everything a candidate is
    plausibly relevant to (fact-block filtering is the motivating case)
    must read `_patterns`, not `_pattern`. Neither is part of the
    adjudication contract -- both are stripped before candidates are
    shown to the model (any key starting with `_`, see
    adjudicate._strip_internal_fields)."""
    compiled = {name: re.compile(rx) for name, rx in patterns.items()}
    results = []
    for rel in reader.list_py_files():
        try:
            text = reader.read_text(rel)
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            matched = [name for name, rx in compiled.items() if rx.search(line)]
            if matched:
                results.append({
                    "file": rel,
                    "line": i,
                    "snippet": line.rstrip("\n"),
                    "_pattern": matched[0],
                    "_patterns": matched,
                })
    return results
