"""The thin end-to-end path: derive fact block -> derive vocabulary ->
grep -> prefilter -> adjudicate -> write report. One function, called by
cli.py, the acceptance test, and the replay test alike -- so "does the
packaged tool reproduce the study's numbers" and "does the plumbing still
work" are both exercised through the exact same code path a real run
takes, never a special test-only shortcut.
"""
import json
import os
import re

from . import guards
from .reposafe import RepoReader, assert_no_overlap
from .stages import adjudicate, factblock, grep, prefilter, report, vocabulary


class GuardFailure(Exception):
    """Raised when a runtime guard stops the pipeline. Carries the full
    diagnostic report -- callers print it, they don't have to reconstruct
    it."""
    def __init__(self, reason, diagnostic_report):
        super().__init__(reason)
        self.reason = reason
        self.diagnostic_report = diagnostic_report


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def run(repo_root, guide_path, workdir, client, chunk_size=40, force=False,
        package_name_override=None, print_fn=print):
    """Runs the full pipeline. Never writes anything outside `workdir` --
    repo access goes exclusively through RepoReader, which has no write
    method. Returns a dict with every intermediate artifact plus the
    expanded, scoreable merged adjudication result."""
    assert_no_overlap(repo_root, workdir)
    os.makedirs(workdir, exist_ok=True)
    reader = RepoReader(repo_root)

    with open(guide_path, encoding="utf-8") as f:
        guide_text = f.read()

    print_fn("[1/5] Deriving fact block from guide...")
    fb = factblock.derive(client, guide_text)
    if package_name_override:
        fb["package_name"] = package_name_override
    _write_json(os.path.join(workdir, "factblock.json"), fb)
    print_fn(f"      {len(fb['facts'])} facts, package={fb['package_name']!r}")

    cov = guards.check_factblock_coverage(guide_text, fb)
    if not cov.ok and not force:
        raise GuardFailure(cov.reason, cov.report)
    if not cov.ok:
        print_fn(f"      GUARD BYPASSED (--force): {cov.reason}")

    print_fn("[2/5] Deriving vocabulary...")
    vocab = vocabulary.derive(client, guide_text, fb)
    _write_json(os.path.join(workdir, "vocabulary.json"), vocab)
    print_fn(f"      {len(vocab['patterns'])} patterns")

    print_fn("[3/5] Searching repo...")
    candidates = grep.find_candidates(reader, vocab["patterns"])
    _write_json(os.path.join(workdir, "candidates.json"), candidates)
    print_fn(f"      {len(candidates)} raw candidates")

    yld = guards.check_vocabulary_yield(vocab["patterns"], candidates)
    if not yld.ok and not force:
        raise GuardFailure(yld.reason, yld.report)
    if not yld.ok:
        print_fn(f"      GUARD BYPASSED (--force): {yld.reason}")

    print_fn("[4/5] Prefiltering...")
    target_pattern = prefilter.build_relevance_pattern(fb["package_name"])
    vocab_regex = re.compile("|".join(f"(?:{p})" for p in vocab["patterns"].values()))
    kept, expansion_map, stats, droplog = prefilter.run_pipeline(
        candidates, reader, target_pattern, vocab_regex=vocab_regex,
    )
    _write_json(os.path.join(workdir, "droplog.json"), droplog)
    print_fn(f"      {stats['start']} -> {stats['final']} after prefilter "
              f"(A: -{stats.get('dropped_by_A', 0)}, B: -{stats.get('dropped_by_B', 0)}, "
              f"C: collapsed {stats.get('collapsed_by_C', 0)})")

    print_fn("[5/5] Adjudicating...")
    merged = adjudicate.run(client, kept, fb, workdir, chunk_size=chunk_size)
    expanded = adjudicate.expand_duplicates(merged, expansion_map)
    print_fn(f"      PROPOSE: {len(expanded['proposed_sites'])}  "
              f"FLAG-UNCERTAIN: {len(expanded['flag_uncertain'])}  "
              f"REJECT: {len(expanded['considered_and_rejected'])}")

    report_path = report.write(workdir, expanded, stats, fb, vocab)
    print_fn(f"Done. Report: {report_path}")

    return {
        "factblock": fb,
        "vocabulary": vocab,
        "candidates": candidates,
        "droplog": droplog,
        "stats": stats,
        "merged": merged,
        "expanded": expanded,
        "report_path": report_path,
    }
