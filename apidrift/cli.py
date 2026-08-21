import argparse
import sys

from . import llm, pipeline, preflight
from .llm import AnthropicLLMClient, LLMError


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


if __name__ == "__main__":
    main()
