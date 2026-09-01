"""The thin end-to-end path: derive fact block -> derive vocabulary ->
grep -> prefilter -> adjudicate -> write report. One function, called by
cli.py, the acceptance test, and the replay test alike -- so "does the
packaged tool reproduce the study's numbers" and "does the plumbing still
work" are both exercised through the exact same code path a real run
takes, never a special test-only shortcut.
"""
import hashlib
import json
import os
import re

from . import guards, preflight, validate, verify as verify_module
from .reposafe import RepoReader
from .stages import adjudicate, factblock, fixgen, grep, prefilter, report, vocabulary
from .stages import gapfill as gapfill_stage


class GuardFailure(Exception):
    """Raised when a runtime guard stops the pipeline. Carries the full
    diagnostic report -- callers print it, they don't have to reconstruct
    it -- plus which guard (by its guards.GUARD_NAMES name) raised it, so
    a caller can tell the user exactly what to pass to --force=<name>
    rather than pointing them at bare --force."""
    def __init__(self, reason, diagnostic_report, name=None):
        super().__init__(reason)
        self.reason = reason
        self.diagnostic_report = diagnostic_report
        self.name = name


class GapfillNeedsConfirmation(Exception):
    """Raised when --gapfill is on, a target set is non-empty, and
    --gapfill-yes was not also given. Carries the plan report (target
    fact count, estimated cost) so the caller can show it and stop --
    mirrors GuardFailure's shape (a reason plus a report to print) but
    is a different kind of stop: this is not a correctness check
    failing, it's the deliberate pause this project's own convention
    requires before a real, paid API call -- print the plan, wait for an
    explicit go-ahead, never spend on an inferred yes."""
    def __init__(self, plan_report):
        super().__init__("gap-fill plan ready for review -- re-run with --gapfill-yes to proceed")
        self.plan_report = plan_report


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def _normalize_force(force):
    """Turns `run()`'s `force` argument into a frozenset of guard names to
    bypass -- the single place this project decides what "--force" means.
    `True` (bare --force) bypasses every guard in guards.GUARD_NAMES;
    `False`/omitted bypasses none; anything else (a comma-separated string,
    or any iterable of strings) is treated as an explicit guard-name list
    and validated against guards.GUARD_NAMES. An unknown name raises
    ValueError immediately, before any stage has run -- a typo must stop
    the run, never silently bypass nothing, since that reads as "the guard
    passed" instead of "the guard was never checked against your list"."""
    if force is True:
        return frozenset(guards.GUARD_NAMES)
    if not force:
        return frozenset()
    names = frozenset(n.strip() for n in force.split(",") if n.strip()) \
        if isinstance(force, str) else frozenset(force)
    unknown = names - frozenset(guards.GUARD_NAMES)
    if unknown:
        raise ValueError(
            f"--force: unknown guard name(s) {sorted(unknown)} -- valid guard names are "
            f"{', '.join(guards.GUARD_NAMES)}"
        )
    return names


def _apply_guard(name, result, workdir, bypass, print_fn, bypassed_log):
    """Writes `result`'s full report to workdir/<name>.txt unconditionally
    (pass or fail, so a human or a later run can always see exactly what a
    guard measured), then either raises (guard failed, not in the bypass
    set), prints a one-line "bypassed" notice naming this guard and its
    one-line reason (guard failed, bypassed), or does nothing further
    (guard passed). The bypass notice is the fix for the failure this was
    built to prevent: check_pattern_shape's verdict on gf_tooldecor was
    correct and was written to pattern_shape.txt on every real run, but
    with a blanket --force nothing distinguished it from any other
    bypassed guard, and nobody read the file -- see REPORT.md."""
    with open(os.path.join(workdir, f"{name}.txt"), "w") as f:
        f.write(result.report)
    if result.ok:
        return
    if name not in bypass:
        raise GuardFailure(result.reason, result.report, name=name)
    bypassed_log.append(name)
    print_fn(f"      GUARD BYPASSED [{name}] (--force): {result.reason}")


def run(repo_root, guide_path, workdir, client, chunk_size=40, force=False,
        package_name_override=None, print_fn=print, skip_fix_generation=False,
        fixgen_chunk_size=fixgen.DEFAULT_CHUNK_SIZE, verify_install=True,
        package_version_override=None, factblock_path=None, vocabulary_path=None,
        factblock_chunk_size=factblock.DEFAULT_CHUNK_SIZE, model=None, cache_ttl="5m",
        gapfill=False, gapfill_confirmed=False, gapfill_chunk_size=gapfill_stage.DEFAULT_CHUNK_SIZE):
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
    rather than relying on a hidden default.

    `force`: which of guards.GUARD_NAMES to bypass on failure --
    `factblock_coverage`, `vocabulary_coverage`, `pattern_shape`,
    `vocabulary_yield` (see guards.py; each guard still writes its full
    report to workdir/<name>.txt whether it passes or fails). `False`
    (default) bypasses none -- any guard failure stops the run. `True`
    bypasses all of them, matching bare `--force` on the CLI. Anything
    else -- a comma-separated string or any iterable of strings -- bypasses
    only the named guard(s); an unknown name raises ValueError before any
    stage runs, never a silent no-op. Every bypass, blanket or named,
    prints that guard's one-line verdict to stdout as it happens, and the
    full set of bypassed guards is printed again as one summary line once
    the last guard has run -- a bypassed guard's verdict must never exist
    only in a workdir file that nobody happens to open (see REPORT.md:
    check_pattern_shape correctly flagged an overbroad gap-fill pattern on
    every real run and nobody read pattern_shape.txt, because a blanket
    --force let the run complete either way).

    `factblock_path`/`vocabulary_path`: stages 1/2 depend only on --guide,
    never on --repo, so a fact block or vocabulary already derived against
    this exact guide can be loaded instead of re-derived -- same guide,
    several repos, one derivation instead of one per repo, and no
    sampling-variance drift between them. A loaded artifact still goes
    through the exact same validate_factblock/validate_vocabulary check
    and check_factblock_coverage/check_vocabulary_coverage guard a freshly
    derived one gets -- loading is never a way to skip either.

    `factblock_chunk_size`/`model`: stage 1 is chunked by guide section
    (see stages/factblock.py) -- `factblock_chunk_size` is the approx.
    input-token budget per chunk, and `model` (a plain string, not read
    off `client`, since not every LLMClient implementation carries one)
    is used only to print a per-chunk cost estimate as each chunk
    completes; omitted entirely (no cost line) if None.

    `cache_ttl`: prompt-cache TTL for adjudicate/fixgen's system prompt
    ("5m" default, or "1h"). Only worth raising when running several
    repos against the same loaded --factblock within the hour -- see
    stages/adjudicate.py and stages/fixgen.py for why a single-chunk run
    can't benefit from its own cache write regardless of TTL.

    `gapfill`/`gapfill_confirmed`/`gapfill_chunk_size`: `gapfill` defaults
    False -- stage 2's output is used exactly as before unless
    explicitly turned on. Turning it on with `gapfill_confirmed` still
    False computes the target set, the planned chunks, and an estimated
    cost, prints it, and stops by raising GapfillNeedsConfirmation
    rather than making any call -- this project never spends real API
    cost on an inferred yes (see stages/gapfill.py for the chunked gap-
    fill pass this runs when confirmed, and why chunking by target-fact
    count rather than raising max_tokens is the fix for a large target
    set). All three are no-ops if the target set turns out empty (stage
    2 already covered everything after the structural pre-filter)."""
    # Validated before preflight, let alone any file read or API call --
    # an unknown guard name in `force` must stop the run immediately, not
    # after work has already been spent.
    force_bypass = _normalize_force(force)
    bypassed_guards = []

    preflight.check_inputs(repo_root, guide_path, workdir,
                            factblock_path=factblock_path, vocabulary_path=vocabulary_path)
    os.makedirs(workdir, exist_ok=True)
    reader = RepoReader(repo_root)

    with open(guide_path, encoding="utf-8") as f:
        guide_text = f.read()
    guide_sha256 = hashlib.sha256(guide_text.encode("utf-8")).hexdigest()

    manifest = {
        "guide_path": os.path.abspath(guide_path),
        "guide_sha256": guide_sha256,
        "repo_root": reader.repo_root,
        "factblock_source": None,
        "vocabulary_source": None,
    }

    total_stages = 5 if skip_fix_generation else 6

    def _warn_on_guide_mismatch(kind, loaded_sha):
        if loaded_sha is None:
            print_fn(f"      WARNING: loaded {kind} has no recorded guide_sha256 -- cannot "
                      f"verify it came from --guide.")
        elif loaded_sha != guide_sha256:
            print_fn(f"      WARNING: loaded {kind}'s guide_sha256 ({loaded_sha[:12]}...) does "
                      f"not match --guide's sha256 ({guide_sha256[:12]}...) -- this {kind} may "
                      f"have been derived from a different guide.")

    if factblock_path:
        print_fn(f"[1/{total_stages}] Loading fact block from {factblock_path}...")
        fb = validate.validate_factblock_file(factblock_path)
        _warn_on_guide_mismatch("fact block", fb.get("guide_sha256"))
        if package_name_override:
            fb["package_name"] = package_name_override
        manifest["factblock_source"] = f"loaded:{os.path.abspath(factblock_path)}"
    else:
        print_fn(f"[1/{total_stages}] Deriving fact block from guide "
                  f"(chunk budget: ~{factblock_chunk_size} input tokens)...")
        fb = factblock.run(client, guide_text, workdir, chunk_token_budget=factblock_chunk_size,
                            model=model, print_fn=print_fn)
        if package_name_override:
            fb["package_name"] = package_name_override
        fb["guide_sha256"] = guide_sha256
        manifest["factblock_source"] = "derived"
    _write_json(os.path.join(workdir, "factblock.json"), fb)
    print_fn(f"      {len(fb['facts'])} facts, package={fb['package_name']!r}")

    cov = guards.check_factblock_coverage(guide_text, fb)
    _apply_guard("factblock_coverage", cov, workdir, force_bypass, print_fn, bypassed_guards)

    if vocabulary_path:
        print_fn(f"[2/{total_stages}] Loading vocabulary from {vocabulary_path}...")
        vocab = validate.validate_vocabulary_file(vocabulary_path)
        _warn_on_guide_mismatch("vocabulary", vocab.get("guide_sha256"))
        manifest["vocabulary_source"] = f"loaded:{os.path.abspath(vocabulary_path)}"
    else:
        print_fn(f"[2/{total_stages}] Deriving vocabulary...")
        vocab = vocabulary.derive(client, guide_text, fb)
        vocab["guide_sha256"] = guide_sha256
        manifest["vocabulary_source"] = "derived"
    print_fn(f"      {len(vocab['patterns'])} patterns")
    # vocabulary.json itself is written after the --gapfill block below, once
    # `vocab` holds whatever was actually used for grep/adjudicate -- never
    # here. A prior version wrote it at this point unconditionally, which
    # made workdir/vocabulary.json a permanent pre-merge snapshot on every
    # run where gap-fill ran (the real merged result only ever landed in
    # vocabulary_after_gapfill.json), so `--vocabulary <old workdir>/
    # vocabulary.json` on a later run silently reloaded the wrong,
    # non-gap-filled vocabulary. If gap-fill is requested, this pre-merge
    # vocab is preserved under its own explicit name so nothing is lost.
    if gapfill:
        _write_json(os.path.join(workdir, "vocabulary_pre_gapfill.json"), vocab)

    _write_json(os.path.join(workdir, "manifest.json"), manifest)

    # Persisted as structured data (not just guard report prose) so the
    # fact<->pattern relation is directly inspectable from the workdir --
    # e.g. by a future fact-block filter deciding what's safe to withhold
    # from a chunk. Shares its matching logic with check_vocabulary_coverage
    # below via compute_fact_pattern_coverage; neither reimplements it.
    coverage_rows = guards.compute_fact_pattern_coverage(fb, vocab)

    if gapfill:
        targets = gapfill_stage.build_targets(coverage_rows)
        if not targets:
            print_fn("      [gapfill] no partial/uncovered facts remain after the "
                      "structural pre-filter -- nothing to do.")
        else:
            plan_report = "\n".join(
                gapfill_stage.estimate_cost_report(
                    guide_text, vocab, fb, targets, chunk_size=gapfill_chunk_size, model=model,
                )
            )
            if not gapfill_confirmed:
                print_fn(plan_report)
                raise GapfillNeedsConfirmation(plan_report)
            n_chunks = len(gapfill_stage.plan_chunks(targets, gapfill_chunk_size))
            print_fn(f"[gapfill] deriving patterns for {len(targets)} target fact(s) "
                      f"({n_chunks} chunk(s))...")
            vocab, gapfill_report, coverage_rows = gapfill_stage.run(
                client, guide_text, fb, vocab, coverage_rows, workdir,
                chunk_size=gapfill_chunk_size, cache_ttl=cache_ttl,
            )
            _write_json(os.path.join(workdir, "vocabulary_after_gapfill.json"), vocab)
            print_fn(f"      [gapfill] {len(gapfill_report['new_patterns'])} new pattern(s), "
                      f"{len(gapfill_report['declined'])} declined, "
                      f"{len(gapfill_report['unresolved'])} unresolved")
            if gapfill_report["renamed_on_merge"]:
                print_fn(f"      [gapfill] {len(gapfill_report['renamed_on_merge'])} pattern "
                          f"id(s) renamed on merge (collided across chunks): "
                          f"{gapfill_report['renamed_on_merge']}")
            if gapfill_report["deduplicated"]:
                dropped = sum(len(g["dropped"]) for g in gapfill_report["deduplicated"])
                print_fn(f"      [gapfill] {dropped} redundant pattern(s) across "
                          f"{len(gapfill_report['deduplicated'])} group(s) collapsed at merge "
                          f"(same symbol set, independently derived by different chunks) -- "
                          f"see gapfill/report.json's 'deduplicated' for kept/dropped detail")
            if gapfill_report["overlapping_symbol_sets"]:
                print_fn(f"      [gapfill] {len(gapfill_report['overlapping_symbol_sets'])} "
                          f"pattern pair(s) share a symbol without matching symbol sets exactly "
                          f"-- NOT collapsed, see gapfill/report.json's "
                          f"'overlapping_symbol_sets' for review")
            if gapfill_report["anti_goodhart_warnings"]:
                print_fn(f"      [gapfill] WARNING: {len(gapfill_report['anti_goodhart_warnings'])} "
                          f"pattern(s) flagged by an anti-Goodhart check (non-fatal, still merged "
                          f"in -- see gapfill/report.json for the full reason on each):")
                for w in gapfill_report["anti_goodhart_warnings"]:
                    print_fn(f"        [{w['check']}] {w['pattern']} ({w['regex']!r})")

    # Written here, after any gap-fill merge, so vocabulary.json always names
    # the vocabulary actually used for grep/adjudicate below -- identical to
    # vocabulary_after_gapfill.json when gap-fill ran and merged anything, and
    # to the loaded/derived vocab otherwise.
    _write_json(os.path.join(workdir, "vocabulary.json"), vocab)

    coverage_summary = {"non_breaking": 0, "no_identifier": 0, "unsearchable": 0, "covered": 0, "partial": 0, "uncovered": 0}
    for row in coverage_rows:
        coverage_summary[row["status"]] += 1
    _write_json(os.path.join(workdir, "fact_pattern_coverage.json"),
                {"summary": coverage_summary, "facts": coverage_rows})

    vcov = guards.check_vocabulary_coverage(fb, vocab)
    print_fn(vcov.report)
    _apply_guard("vocabulary_coverage", vcov, workdir, force_bypass, print_fn, bypassed_guards)

    shape = guards.check_pattern_shape(vocab["patterns"])
    _apply_guard("pattern_shape", shape, workdir, force_bypass, print_fn, bypassed_guards)

    print_fn(f"[3/{total_stages}] Searching repo...")
    candidates = grep.find_candidates(reader, vocab["patterns"])
    _write_json(os.path.join(workdir, "candidates.json"), candidates)
    print_fn(f"      {len(candidates)} raw candidates")

    yld = guards.check_vocabulary_yield(vocab["patterns"], candidates)
    _apply_guard("vocabulary_yield", yld, workdir, force_bypass, print_fn, bypassed_guards)

    if bypassed_guards:
        print_fn(f"      GUARD(S) BYPASSED (--force): {', '.join(bypassed_guards)}")

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
    merged = adjudicate.run(client, kept, fb, workdir, chunk_size=chunk_size, cache_ttl=cache_ttl)
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
                                        uncertain_sites=merged["flag_uncertain"],
                                        chunk_size=fixgen_chunk_size, cache_ttl=cache_ttl)
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
        "manifest": manifest,
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
