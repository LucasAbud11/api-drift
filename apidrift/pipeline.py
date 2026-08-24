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

from . import guards, preflight, verify as verify_module
from .reposafe import RepoReader
from .stages import adjudicate, factblock, fixgen, grep, prefilter, report, vocabulary


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
        package_name_override=None, print_fn=print, skip_fix_generation=False,
        fixgen_chunk_size=fixgen.DEFAULT_CHUNK_SIZE, verify_install=True,
        package_version_override=None):
    """Runs the full pipeline. Never writes anything outside `workdir` --
    repo access goes exclusively through RepoReader, which has no write
    method. Returns a dict with every intermediate artifact plus the
    expanded, scoreable merged adjudication result.

    `skip_fix_generation` defaults to False (matching cli.py's
    `--skip-fix-generation` flag, which defaults to not-skipping) so a
    library caller gets the same full pipeline a real CLI run gets. Callers
    that want detection-only behavior -- the acceptance/replay tests, which
    pin their assertions and cassettes to the detection stages only -- pass
    it explicitly, the same way they already pass `force=True` explicitly
    rather than relying on a hidden default."""
    preflight.check_inputs(repo_root, guide_path, workdir)
    os.makedirs(workdir, exist_ok=True)
    reader = RepoReader(repo_root)

    with open(guide_path, encoding="utf-8") as f:
        guide_text = f.read()

    total_stages = 5 if skip_fix_generation else 6

    print_fn(f"[1/{total_stages}] Deriving fact block from guide...")
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

    print_fn(f"[2/{total_stages}] Deriving vocabulary...")
    vocab = vocabulary.derive(client, guide_text, fb)
    _write_json(os.path.join(workdir, "vocabulary.json"), vocab)
    print_fn(f"      {len(vocab['patterns'])} patterns")

    vcov = guards.check_vocabulary_coverage(fb, vocab)
    with open(os.path.join(workdir, "vocabulary_coverage.txt"), "w") as f:
        f.write(vcov.report)
    print_fn(vcov.report)
    if not vcov.ok and not force:
        raise GuardFailure(vcov.reason, vcov.report)
    if not vcov.ok:
        print_fn(f"      GUARD BYPASSED (--force): {vcov.reason}")

    print_fn(f"[3/{total_stages}] Searching repo...")
    candidates = grep.find_candidates(reader, vocab["patterns"])
    _write_json(os.path.join(workdir, "candidates.json"), candidates)
    print_fn(f"      {len(candidates)} raw candidates")

    yld = guards.check_vocabulary_yield(vocab["patterns"], candidates)
    if not yld.ok and not force:
        raise GuardFailure(yld.reason, yld.report)
    if not yld.ok:
        print_fn(f"      GUARD BYPASSED (--force): {yld.reason}")

    print_fn(f"[4/{total_stages}] Prefiltering...")
    target_pattern = prefilter.build_relevance_pattern(fb["package_name"])
    vocab_regex = re.compile("|".join(f"(?:{p})" for p in vocab["patterns"].values()))
    kept, expansion_map, stats, droplog = prefilter.run_pipeline(
        candidates, reader, target_pattern, vocab_regex=vocab_regex,
    )
    _write_json(os.path.join(workdir, "droplog.json"), droplog)
    print_fn(f"      {stats['start']} -> {stats['final']} after prefilter "
              f"(A: -{stats.get('dropped_by_A', 0)}, B: -{stats.get('dropped_by_B', 0)}, "
              f"C: collapsed {stats.get('collapsed_by_C', 0)})")

    print_fn(f"[5/{total_stages}] Adjudicating...")
    merged = adjudicate.run(client, kept, fb, workdir, chunk_size=chunk_size)
    expanded = adjudicate.expand_duplicates(merged, expansion_map)
    print_fn(f"      PROPOSE: {len(expanded['proposed_sites'])}  "
              f"FLAG-UNCERTAIN: {len(expanded['flag_uncertain'])}  "
              f"REJECT: {len(expanded['considered_and_rejected'])}")

    fixgen_merged = None
    fixgen_expanded = None
    verification_report = None
    if not skip_fix_generation:
        print_fn(f"[6/{total_stages}] Generating fixes...")
        if merged["proposed_sites"]:
            fixgen_merged = fixgen.run(client, reader, merged["proposed_sites"], fb, workdir,
                                        chunk_size=fixgen_chunk_size)
            fixgen_expanded = fixgen.expand_duplicates(fixgen_merged, expansion_map)
        else:
            fixgen_merged = {"fixes": [], "flagged_for_human": []}
            fixgen_expanded = {"fixes": [], "flagged_for_human": []}
        print_fn(f"      FIX: {len(fixgen_expanded['fixes'])}  "
                  f"FLAG-FOR-HUMAN: {len(fixgen_expanded['flagged_for_human'])}")

        verification_report = verify_module.run(
            reader, fb["package_name"], fixgen_expanded["fixes"], workdir,
            verify_install=verify_install, version=package_version_override,
        )
        _write_json(os.path.join(workdir, "verification.json"), verification_report)
        parse_ok = verification_report["parse_and_line_match"]["ok"]
        install = verification_report["install"]
        install_note = (f"{sum(1 for r in install['items'] if r['resolved'])}/"
                         f"{len(install['items'])} resolved" if install["available"]
                         else f"unavailable ({install['reason']})")
        print_fn(f"      Verification: parse+line-match {'OK' if parse_ok else 'FAILED'}, "
                  f"install-tier {install_note}")
        # repo_root lets `api-drift apply` refuse to write fixes back into
        # the exact repo this run read from -- writer.py's
        # check_not_analysis_repo compares --into against this field.
        fixgen_expanded["repo_root"] = reader.repo_root
        _write_json(os.path.join(workdir, "fixes.json"), fixgen_expanded)

    report_path = report.write(workdir, expanded, stats, fb, vocab,
                                fixgen_expanded=fixgen_expanded, verification_report=verification_report)
    print_fn(f"Done. Report: {report_path}")

    return {
        "factblock": fb,
        "vocabulary": vocab,
        "candidates": candidates,
        "droplog": droplog,
        "stats": stats,
        "merged": merged,
        "expanded": expanded,
        "fixgen_merged": fixgen_merged,
        "fixgen_expanded": fixgen_expanded,
        "verification_report": verification_report,
        "report_path": report_path,
    }
