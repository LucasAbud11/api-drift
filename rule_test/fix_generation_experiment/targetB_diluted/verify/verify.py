"""Mechanical verification of one fix-generation run.

For a given run's FIX-verdict items:
1. Copy the 5 targetB_small repos to a fresh scratch dir.
2. Apply each proposed_line as a literal line replacement at file:line.
3. ast.parse() every touched file -- "still parses."
4. For every touched line that is itself an `import` statement, exec just
   that statement against the real mcp_v2_stub (which has NO
   mcp.server.fastmcp module at all -- confirmed by negative control) and
   check the expected name binds to a class. This is the honest scope of
   "imports resolve" achievable in this environment: the repos' unrelated
   third-party deps (boto3, starlette, uvicorn, dotenv, requests) are not
   installed here, so full end-to-end module execution is not attempted
   and is not claimed.
5. For QAInsights specifically: run the real test suite (self-mocking, no
   external deps needed) before and after the fix, compare full pass/fail
   signature (not just counts) to the baseline captured fresh in this
   session.
"""
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIXGEN_HOST_DIR = os.path.dirname(HERE)  # .../fix_generation_experiment/targetB_diluted
FIXGEN = os.path.dirname(FIXGEN_HOST_DIR)  # .../fix_generation_experiment
REPO_ROOT = os.path.dirname(os.path.dirname(FIXGEN))
REPOS_SRC = os.path.join(REPO_ROOT, "rule_test", "scale_experiment", "host", "integrations")
STUB = os.path.join(FIXGEN, "verify", "mcp_v2_stub")
# Override with the FIXGEN_VERIFY_SCRATCH env var to pin a specific location;
# defaults to the system temp dir so this runs unmodified on any machine.
SCRATCH_BASE = os.environ.get("FIXGEN_VERIFY_SCRATCH", tempfile.gettempdir())

TARGETB_SMALL_REPOS = [
    "tonyzorin_youtrack-mcp",
    "QAInsights_jmeter-mcp-server",
    "securityfortech_secops-mcp",
    "m0xai_trello-mcp-server",
    "danilop_MCP2Lambda",
]

# Fresh baseline for QAInsights, captured in this session (see report.md):
# PYTHONPATH=. python3 -m unittest tests.test_jmeter_server -v
# Ran 9 tests: 6 pass, 3 fail (pre-existing, migration-unrelated kwarg-count
# assertions). Recorded here as the exact failing-test-name signature so a
# regression (different tests failing) is distinguishable from "same
# pre-existing gap."
BASELINE_QAINSIGHTS_FAILURES = {
    "test_execute_jmeter_test_default",
    "test_execute_jmeter_test_gui",
    "test_execute_jmeter_test_non_gui",
}
BASELINE_QAINSIGHTS_TOTAL = 9
BASELINE_QAINSIGHTS_PASS = 6


def make_scratch(run_n):
    scratch = os.path.join(SCRATCH_BASE, f"fixgen_diluted_verify_run{run_n}")
    if os.path.exists(scratch):
        shutil.rmtree(scratch)
    os.makedirs(os.path.join(scratch, "integrations"))
    for repo in TARGETB_SMALL_REPOS:
        shutil.copytree(os.path.join(REPOS_SRC, repo), os.path.join(scratch, "integrations", repo))
    return scratch


def apply_fixes(scratch, run_items):
    touched = []
    applied = []
    skipped_non_fix = []
    for item in run_items:
        if item.get("verdict") != "FIX":
            skipped_non_fix.append({"id": item["id"], "verdict": item.get("verdict")})
            continue
        path = os.path.join(scratch, item["file"])
        with open(path) as f:
            lines = f.readlines()
        idx = item["line"] - 1
        if idx < 0 or idx >= len(lines):
            applied.append({"id": item["id"], "ok": False, "error": f"line {item['line']} out of range for {item['file']}"})
            continue
        original_on_disk = lines[idx].rstrip("\n")
        expected_original = item.get("original_line", "")
        match_ok = original_on_disk.strip() == expected_original.strip()
        newline = item["proposed_line"]
        if not newline.endswith("\n"):
            newline = newline + "\n"
        lines[idx] = newline
        with open(path, "w") as f:
            f.writelines(lines)
        touched.append(path)
        applied.append({
            "id": item["id"], "ok": True, "file": item["file"], "line": item["line"],
            "original_matched_source": match_ok, "original_on_disk": original_on_disk,
            "agent_claimed_original": expected_original,
        })
    return touched, applied, skipped_non_fix


def check_parses(touched_paths):
    results = []
    for path in sorted(set(touched_paths)):
        with open(path) as f:
            src = f.read()
        try:
            ast.parse(src)
            results.append({"file": path, "parses": True})
        except SyntaxError as e:
            results.append({"file": path, "parses": False, "error": str(e)})
    return results


def check_import_boundary(scratch, run_items):
    """For every FIX'd line that is itself an `import` statement, exec it
    in isolation against the real v2 stub and confirm the expected name
    binds to a class."""
    results = []
    for item in run_items:
        if item.get("verdict") != "FIX":
            continue
        line = item.get("proposed_line", "") or ""
        stripped = line.strip()
        if not (stripped.startswith("from mcp") or stripped.startswith("import mcp")):
            continue
        script = (
            f"import sys; sys.path.insert(0, {STUB!r})\n"
            f"{stripped}\n"
            f"names = [n.strip() for n in {stripped!r}.split('import')[1].split(',')]\n"
            f"import inspect\n"
            f"for n in names:\n"
            f"    obj = eval(n)\n"
            f"    assert inspect.isclass(obj), f'{{n}} did not resolve to a class'\n"
            f"print('OK', names)\n"
        )
        proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=15)
        results.append({
            "id": item["id"], "file": item["file"], "line": item["line"],
            "statement": stripped, "resolved": proc.returncode == 0,
            "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip()[-2000:],
        })
    return results


def run_qainsights_suite(scratch):
    repo_dir = os.path.join(scratch, "integrations", "QAInsights_jmeter-mcp-server")
    env = dict(os.environ)
    env["PYTHONPATH"] = "."
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "tests.test_jmeter_server", "-v"],
        cwd=repo_dir, capture_output=True, text=True, env=env, timeout=60,
    )
    out = proc.stdout + "\n" + proc.stderr
    failing = set()
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("FAIL:") or line.startswith("ERROR:"):
            name = line.split()[1]
            failing.add(name)
    ran_match = None
    for line in out.splitlines():
        if line.strip().startswith("Ran "):
            ran_match = line.strip()
    return {
        "returncode": proc.returncode,
        "ran_line": ran_match,
        "failing_tests": sorted(failing),
        "matches_baseline_signature": failing == BASELINE_QAINSIGHTS_FAILURES,
        "raw_tail": "\n".join(out.splitlines()[-15:]),
    }


def verify_run(run_n):
    run_path = os.path.join(FIXGEN_HOST_DIR, "runs", f"run{run_n}.json")
    with open(run_path) as f:
        run_items = json.load(f)

    scratch = make_scratch(run_n)
    touched, applied, skipped = apply_fixes(scratch, run_items)
    parse_results = check_parses(touched)
    import_results = check_import_boundary(scratch, run_items)
    qainsights_after = run_qainsights_suite(scratch)

    result = {
        "run": run_n,
        "scratch_dir": scratch,
        "n_fix_applied": len(touched),
        "n_skipped_non_fix": len(skipped),
        "skipped_non_fix": skipped,
        "apply_detail": applied,
        "all_original_lines_matched_source": all(a.get("original_matched_source", True) for a in applied if a["ok"]),
        "all_applies_ok": all(a["ok"] for a in applied),
        "parse_results": parse_results,
        "all_parse_ok": all(r["parses"] for r in parse_results),
        "import_boundary_results": import_results,
        "all_imports_resolved": all(r["resolved"] for r in import_results),
        "n_import_checks": len(import_results),
        "qainsights_after_fix": qainsights_after,
    }
    return result


def main():
    all_results = {}
    for n in (1, 2, 3):
        print(f"\n===== Verifying run {n} =====")
        r = verify_run(n)
        all_results[f"run{n}"] = r
        print(f"  FIX applied: {r['n_fix_applied']}  (non-FIX skipped: {r['n_skipped_non_fix']})")
        print(f"  all applies matched source original_line: {r['all_original_lines_matched_source']}")
        print(f"  all touched files parse: {r['all_parse_ok']}")
        print(f"  import-boundary checks: {r['n_import_checks']}, all resolved: {r['all_imports_resolved']}")
        for ir in r["import_boundary_results"]:
            if not ir["resolved"]:
                print(f"    FAILED IMPORT: {ir['id']} {ir['statement']!r}\n{ir['stderr']}")
        qa = r["qainsights_after_fix"]
        print(f"  QAInsights suite after fix: {qa['ran_line']}  failing={qa['failing_tests']}  matches_baseline_signature={qa['matches_baseline_signature']}")

    with open(os.path.join(HERE, "verification_results.json"), "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nWrote {os.path.join(HERE, 'verification_results.json')}")


if __name__ == "__main__":
    main()
