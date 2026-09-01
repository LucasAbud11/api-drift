import argparse
import sys
from argparse import BooleanOptionalAction

from . import guards, llm, pipeline, preflight, validate, writer
from .llm import AnthropicLLMClient, LLMError
from .stages import factblock, fixgen, gapfill

# argparse const for bare `--force` (no `=value`) -- distinct from any real
# guard name or comma-separated list, and translated to pipeline.run's
# force=True (bypass every guard) below, never passed through as a string.
_FORCE_ALL = "__ALL__"


def main(argv=None):
    parser = argparse.ArgumentParser(prog="api-drift")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Detect and adjudicate sites affected by a migration.")
    run_p.add_argument("--repo", required=True, help="Path to the target repository (read-only).")
    run_p.add_argument("--guide", required=True, help="Path to the migration guide (text/markdown).")
    run_p.add_argument("--package", default=None,
                        help="Override the inferred primary import name. If omitted, the "
                             "fact-block step must state one or the run hard-fails.")
    run_p.add_argument("--workdir", default=None,
                        help="Where run artifacts are written. Default: "
                             "./.api-drift-run/<timestamp>/")
    run_p.add_argument("--chunk-size", type=int, default=40)
    run_p.add_argument("--force", nargs="?", const=_FORCE_ALL, default=False,
                        metavar="GUARD1,GUARD2",
                        help="Proceed past a guard failure anyway. Bare --force bypasses every "
                             "guard; --force=GUARD1,GUARD2 bypasses only the named guard(s) -- "
                             "an unknown name stops the run before anything else runs. Every "
                             "bypassed guard still prints its one-line verdict to stdout (never "
                             "only to its workdir/<name>.txt report) and is named again in a "
                             "final summary line. Guard names: " + ", ".join(guards.GUARD_NAMES) + ".")
    run_p.add_argument("--model", default="claude-opus-5")
    run_p.add_argument("--skip-fix-generation", action="store_true",
                        help="Stop after detection; do not generate fixes.")
    run_p.add_argument("--fixgen-chunk-size", type=int, default=None,
                        help="Sites per fix-generation call. Default: a smaller size than "
                             "--chunk-size, since each site carries surrounding source context.")
    run_p.add_argument("--no-verify-install", dest="verify_install", action="store_false",
                        help="Skip tier-2 fix verification (pip-installing the target package "
                             "into an isolated venv under --workdir and checking touched "
                             "imports resolve against it). Tier-1 verification (parse + "
                             "claimed-original-line match) always runs regardless.")
    run_p.add_argument("--package-version", default=None,
                        help="Pin the exact version to install for tier-2 fix verification. "
                             "Default: pip installs the latest release of the inferred package.")
    run_p.add_argument("--factblock", default=None,
                        help="Load a previously derived fact block instead of deriving one -- "
                             "skips stage 1. Still validated and guard-checked exactly like a "
                             "freshly derived fact block.")
    run_p.add_argument("--vocabulary", default=None,
                        help="Load a previously derived vocabulary instead of deriving one -- "
                             "skips stage 2. Still validated and guard-checked exactly like a "
                             "freshly derived vocabulary.")
    run_p.add_argument("--factblock-chunk-size", type=int, default=None,
                        help="Approx. input-token budget per fact-block chunk -- a `##` guide "
                             "section over this budget is split further on its own `###` "
                             f"subheadings. Default: {factblock.DEFAULT_CHUNK_SIZE}.")
    run_p.add_argument("--dry-run", action="store_true",
                        help="Print the planned fact-block chunk list (guide section, approx "
                             "input tokens) and an estimated cost, then exit without making "
                             "any API call.")
    run_p.add_argument("--gapfill", action=BooleanOptionalAction, default=False,
                        help="After stage 2, run one scoped derivation pass for facts left "
                             "partial/uncovered by the structural pre-filter (see "
                             "apidrift/stages/gapfill.py). Off by default -- existing runs "
                             "are unchanged. Prints the target fact count and an estimated "
                             "cost and stops (no call made) unless --gapfill-yes is also "
                             "given.")
    run_p.add_argument("--gapfill-yes", action="store_true",
                        help="Confirm the gap-fill plan printed by --gapfill and actually "
                             "make the call. Ignored if --gapfill is off.")
    run_p.add_argument("--gapfill-chunk-size", type=int, default=None,
                        help="Target facts per gap-fill call -- gap-fill's output is one "
                             "pattern-or-decline per target fact, so a larger guide with "
                             "more gaps needs more chunks, not a higher max_tokens. "
                             f"Default: {gapfill.DEFAULT_CHUNK_SIZE}.")
    run_p.add_argument("--cache-ttl", choices=["5m", "1h"], default="5m",
                        help="Prompt-cache TTL for adjudication/fix-generation's system "
                             "prompt (default: 5m). '1h' costs a higher cache-write premium "
                             "and only pays off when running several repos against the same "
                             "loaded --factblock within that hour, so later repos' calls can "
                             "read the cache an earlier repo's call wrote. A single repo run "
                             "cannot redeem its own cache write either way.")

    apply_p = sub.add_parser(
        "apply", help="Write a run's FIX bucket into a separate working copy of the repo.")
    apply_p.add_argument("--fixes", required=True, help="Path to a fixes.json produced by a run.")
    apply_p.add_argument("--into", required=True,
                          help="Path to a separate git clone to write fixes into -- never the "
                               "repo the run analysed.")
    apply_p.add_argument("--dry-run", action="store_true",
                          help="Run every safety check and print the diff, but write nothing.")

    args = parser.parse_args(argv)

    if args.command == "run":
        workdir = args.workdir
        if workdir is None:
            import datetime
            workdir = f"./.api-drift-run/{datetime.datetime.now().strftime('%Y-%m-%dT%H-%M-%S')}"

        factblock_chunk_size = args.factblock_chunk_size or factblock.DEFAULT_CHUNK_SIZE
        gapfill_chunk_size = args.gapfill_chunk_size or gapfill.DEFAULT_CHUNK_SIZE

        if args.dry_run:
            # No client is ever constructed on this path -- not just
            # "doesn't call complete()" but no ANTHROPIC_API_KEY check,
            # no anthropic.Anthropic() construction, nothing that could
            # touch the network, matching "exits WITHOUT making any API
            # call" literally.
            try:
                preflight.check_guide(args.guide)
                with open(args.guide, encoding="utf-8") as f:
                    guide_text = f.read()
            except preflight.PreflightError as e:
                print(f"\nSTOPPED: {e}\n", file=sys.stderr)
                sys.exit(1)

            if args.gapfill:
                # Gap-fill's plan depends on coverage, which depends on
                # BOTH a fact block and a vocabulary already existing --
                # --dry-run never derives either (that's the one API
                # call this mode exists to avoid), so a gap-fill plan is
                # only computable here when both are already on disk.
                if not (args.factblock and args.vocabulary):
                    print("--dry-run --gapfill: gap-fill's plan needs a coverage computation, "
                          "which needs both a fact block and a vocabulary already derived -- "
                          "pass --factblock and --vocabulary (both loaded from disk, no API "
                          "call) to estimate a gap-fill chunk plan. Nothing to estimate "
                          "without both.")
                    return
                try:
                    fb = validate.validate_factblock_file(args.factblock)
                    vocab = validate.validate_vocabulary_file(args.vocabulary)
                except ValueError as e:
                    print(f"\nSTOPPED: {e}\n", file=sys.stderr)
                    sys.exit(1)
                coverage_rows = guards.compute_fact_pattern_coverage(fb, vocab)
                targets = gapfill.build_targets(coverage_rows)
                for line in gapfill.estimate_cost_report(
                    guide_text, vocab, fb, targets, chunk_size=gapfill_chunk_size, model=args.model,
                ):
                    print(line)
                return

            if args.factblock:
                print(f"--dry-run: --factblock={args.factblock!r} is set -- stage 1 "
                      f"would be loaded from disk, not derived, so there is no chunk "
                      f"plan or cost to estimate. Nothing to do.")
                return
            for line in factblock.format_dry_run_report(guide_text, factblock_chunk_size,
                                                          model=args.model):
                print(line)
            return

        force = True if args.force == _FORCE_ALL else args.force

        client = None
        try:
            preflight.check_api_key()
            client = AnthropicLLMClient(model=args.model)
            pipeline.run(
                repo_root=args.repo,
                guide_path=args.guide,
                workdir=workdir,
                client=client,
                chunk_size=args.chunk_size,
                force=force,
                package_name_override=args.package,
                skip_fix_generation=args.skip_fix_generation,
                fixgen_chunk_size=args.fixgen_chunk_size or fixgen.DEFAULT_CHUNK_SIZE,
                verify_install=args.verify_install,
                package_version_override=args.package_version,
                factblock_path=args.factblock,
                vocabulary_path=args.vocabulary,
                factblock_chunk_size=factblock_chunk_size,
                model=args.model,
                cache_ttl=args.cache_ttl,
                gapfill=args.gapfill,
                gapfill_confirmed=args.gapfill_yes,
                gapfill_chunk_size=gapfill_chunk_size,
            )
        except preflight.PreflightError as e:
            print(f"\nSTOPPED: {e}\n", file=sys.stderr)
            sys.exit(1)
        except LLMError as e:
            print(f"\nSTOPPED: {e}\n", file=sys.stderr)
            sys.exit(1)
        except pipeline.GapfillNeedsConfirmation as e:
            print(f"\n{e.plan_report}\n", file=sys.stderr)
            print("Re-run with --gapfill-yes to proceed.", file=sys.stderr)
            sys.exit(1)
        except pipeline.GuardFailure as e:
            print(f"\nSTOPPED: {e.reason}\n", file=sys.stderr)
            print(e.diagnostic_report, file=sys.stderr)
            print(f"\nRe-run with --force={e.name} to proceed past just this guard, "
                  f"or bare --force to bypass all of them.", file=sys.stderr)
            sys.exit(1)
        except ValueError as e:
            # Every artifact-shape and vocabulary-breadth hard-fail in
            # validate.py raises a plain ValueError -- catch it here so it
            # prints the same clean, one-line stop everything else in this
            # CLI gets, never a raw traceback from deep inside a stage.
            print(f"\nSTOPPED: {e}\n", file=sys.stderr)
            sys.exit(1)
        finally:
            # Printed even on a guard/LLM-error exit -- those calls were
            # still billed, so a stopped run's cost must not go unreported.
            if client is not None and client.calls:
                print(f"\n{llm.format_usage_report(client, args.model)}")

    elif args.command == "apply":
        try:
            data = validate.validate_fixgen_file(args.fixes)
        except ValueError as e:
            print(f"\nSTOPPED: {e}\n", file=sys.stderr)
            sys.exit(1)

        try:
            writer.check_git_repo(args.into)
            writer.check_clean_worktree(args.into)
            writer.check_not_analysis_repo(args.into, data.get("repo_root"))
            result = writer.apply_fixes(args.into, data["fixes"], dry_run=args.dry_run)
        except writer.ApplyError as e:
            print(f"\nSTOPPED: {e}\n", file=sys.stderr)
            sys.exit(1)

        for diff_text in result["diffs"]:
            print(diff_text)

        flagged = data["flagged_for_human"]
        if flagged:
            print("Skipped (FLAG-FOR-HUMAN):")
            for item in sorted(flagged, key=lambda x: (x["file"], x["line"])):
                print(f"  {item['file']}:{item['line']} -- {item['reason']}")
            print()

        verb = "Would apply" if args.dry_run else "Applied"
        print(f"{verb} {result['n_fixes']} fix(es) across {len(result['files_modified'])} "
              f"file(s), {len(flagged)} skipped as FLAG-FOR-HUMAN.")


if __name__ == "__main__":
    main()
