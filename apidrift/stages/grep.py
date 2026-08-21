"""Grep candidate generation. Reads through RepoReader only -- no raw
`open()` on a repo path anywhere in this file. Adapted from the already-
generic rule_test/blind_vocab_experiment/build_candidates.py; same
mechanics, vendored so the packaged tool doesn't import across the
rule_test/ experiment-scratch boundary.
"""
import re


def find_candidates(reader, patterns):
    """patterns: {name: regex_str}. Returns a list of candidate dicts:
    {file, line, snippet, _pattern}. `_pattern` records which single
    pattern matched (first match wins if more than one would) -- used by
    guards.check_vocabulary_yield for the per-pattern breakdown; not part
    of the adjudication contract, stripped before candidates are shown to
    the model."""
    compiled = {name: re.compile(rx) for name, rx in patterns.items()}
    results = []
    for rel in reader.list_py_files():
        try:
            text = reader.read_text(rel)
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            for name, rx in compiled.items():
                if rx.search(line):
                    results.append({
                        "file": rel,
                        "line": i,
                        "snippet": line.rstrip("\n"),
                        "_pattern": name,
                    })
                    break  # one candidate per line; first matching pattern wins
    return results
