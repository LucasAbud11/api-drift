import argparse
import sys

from . import llm, pipeline, preflight, validate, writer
from .llm import AnthropicLLMClient, LLMError
from .stages import fixgen


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
    run_p.add_argument("--force", action="store_true",
                        help="Proceed past a guard failure anyway (still prints the diagnostic).")
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
                force=args.force,
                package_name_override=args.package,
                skip_fix_generation=args.skip_fix_generation,
                fixgen_chunk_size=args.fixgen_chunk_size or fixgen.DEFAULT_CHUNK_SIZE,
                verify_install=args.verify_install,
                package_version_override=args.package_version,
            )
        except preflight.PreflightError as e:
            print(f"\nSTOPPED: {e}\n", file=sys.stderr)
            sys.exit(1)
        except LLMError as e:
            print(f"\nSTOPPED: {e}\n", file=sys.stderr)
            sys.exit(1)
        except pipeline.GuardFailure as e:
            print(f"\nSTOPPED: {e.reason}\n", file=sys.stderr)
            print(e.diagnostic_report, file=sys.stderr)
            print("\nRe-run with --force to proceed anyway.", file=sys.stderr)
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
