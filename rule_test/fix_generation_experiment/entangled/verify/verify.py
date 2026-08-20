"""Mechanical verification of one entangled-host fix-generation run.

Unlike targetB_small/diluted, this host has a real pytest suite (not
self-mocking) and 4 of its 10 confirmed sites (E4, E5, E6, E9) have NO
correct single-line answer -- see ../fix_ground_truth.md. This script:

1. Applies every FIX-verdict site literally (line replacement), regardless
   of whether it's one of the "hard" 4 -- if a run confidently proposed a
   single-line fix for E4/E5/E6/E9, this is exactly where we want to see,
   empirically, whether it breaks the real (pytest, not mocked-away) test
   suite, not just score it as wrong on paper.
2. Leaves every FLAG-FOR-HUMAN / SKIP site untouched (a real pipeline
   would not blind-apply an edit it wasn't confident in).
3. ast.parse()s every touched file.
4. Runs the host's real pytest suite (needs pytest/pytest-asyncio/PyYAML/
   click installed, plus the local mcp v2 stub on PYTHONPATH) and compares
   the full pass/fail test-name signature to the fresh baseline captured
   this session (16 passed, 0 failed, unmodified host + v1 stub).
5. Import-boundary check (same technique as targetB_small/diluted) for any
   FIX'd line that is itself an import statement.
"""
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ENTANGLED_DIR = os.path.dirname(HERE)          # .../fix_generation_experiment/entangled
FIXGEN = os.path.dirname(ENTANGLED_DIR)         # .../fix_generation_experiment
REPO_ROOT = os.path.dirname(os.path.dirname(FIXGEN))
HOST_SRC = os.path.join(REPO_ROOT, "rule_test", "entanglement_experiment", "host")
V2_STUB = os.path.join(FIXGEN, "verify", "mcp_v2_stub")
# Override with the FIXGEN_VERIFY_SCRATCH env var to pin a specific location;
# defaults to the system temp dir so this runs unmodified on any machine.
SCRATCH_BASE = os.environ.get("FIXGEN_VERIFY_SCRATCH", tempfile.gettempdir())

# Fresh baseline, this session, unmodified host + v1 stub:
# PYTHONPATH=src:mcp_v1_stub python3 -m pytest tests/ -v -> 16 passed, 0 failed.
BASELINE_TOTAL = 16
BASELINE_PASS = 16
BASELINE_FAILURES = set()  # empty: nothing failed at baseline


def make_scratch(run_n):
    scratch = os.path.join(SCRATCH_BASE, f"fixgen_entangled_verify_run{run_n}")
    if os.path.exists(scratch):
        shutil.rmtree(scratch)
    shutil.copytree(HOST_SRC, os.path.join(scratch, "host"))
    return scratch


def apply_fixes(scratch, run_items):
    """Applies every FIX verdict literally, including on the 4 hard sites --
    that's deliberate; see module docstring."""
    touched = []
    applied = []
    skipped_non_fix = []
    host_dir = os.path.join(scratch, "host")
    for item in run_items:
        if item.get("verdict") != "FIX":
            skipped_non_fix.append({"id": item["id"], "verdict": item.get("verdict")})
            continue
        path = os.path.join(host_dir, item["file"])
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
        if newline is None:
            applied.append({"id": item["id"], "ok": False, "error": "verdict FIX but proposed_line is null"})
            continue
        if not newline.endswith("\n"):
            newline = newline + "\n"
        lines[idx] = newline
        with open(path, "w") as f:
            f.writelines(lines)
        touched.append(path)
        applied.append({
            "id": item["id"], "ok": True, "file": item["file"], "line": item["line"],
            "original_matched_source": match_ok, "original_on_disk": original_on_disk,
            "agent_claimed_original": expected_original, "proposed_line": item["proposed_line"],
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
    results = []
    for item in run_items:
        if item.get("verdict") != "FIX":
            continue
        line = item.get("proposed_line", "") or ""
        stripped = line.strip()
        if not (stripped.startswith("from mcp") or stripped.startswith("import mcp")):
            continue
        script = (
            f"import sys; sys.path.insert(0, {V2_STUB!r})\n"
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


def run_pytest_suite(scratch):
    host_dir = os.path.join(scratch, "host")
    env = dict(os.environ)
    env["PYTHONPATH"] = "src:" + V2_STUB
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-v"],
        cwd=host_dir, capture_output=True, text=True, env=env, timeout=120,
    )
    out = proc.stdout + "\n" + proc.stderr
    passed, failed, errored = set(), set(), set()
    for line in out.splitlines():
        line = line.strip()
        if " PASSED" in line:
            passed.add(line.split("::")[-1].split(" ")[0])
        elif " FAILED" in line:
            failed.add(line.split("::")[-1].split(" ")[0])
        elif " ERROR" in line and "::" in line:
            errored.add(line.split("::")[-1].split(" ")[0])
    summary_line = None
    for line in out.splitlines():
        if line.strip().startswith(("=", "-")) and ("passed" in line or "error" in line or "failed" in line):
            summary_line = line.strip()
    return {
        "returncode": proc.returncode,
        "summary_line": summary_line,
        "n_passed": len(passed), "n_failed": len(failed), "n_errored": len(errored),
        "failed_tests": sorted(failed), "errored_tests": sorted(errored),
        "matches_baseline": (len(failed) == 0 and len(errored) == 0 and proc.returncode == 0),
        "raw_tail": "\n".join(out.splitlines()[-30:]),
    }


def verify_run(run_n):
    run_path = os.path.join(ENTANGLED_DIR, "runs", f"run{run_n}.json")
    with open(run_path) as f:
        run_items = json.load(f)

    scratch = make_scratch(run_n)
    touched, applied, skipped = apply_fixes(scratch, run_items)
    parse_results = check_parses(touched)
    import_results = check_import_boundary(scratch, run_items)
    pytest_after = run_pytest_suite(scratch)

    hard_site_fixes = [a for a in applied if a["ok"] and a["id"] in ("E4", "E5", "E6", "E9")]

    result = {
        "run": run_n,
        "scratch_dir": scratch,
        "n_fix_applied": len(touched),
        "n_skipped_non_fix": len(skipped),
        "skipped_non_fix": skipped,
        "apply_detail": applied,
        "hard_site_fix_attempts": hard_site_fixes,
        "all_original_lines_matched_source": all(a.get("original_matched_source", True) for a in applied if a["ok"]),
        "all_applies_ok": all(a["ok"] for a in applied),
        "parse_results": parse_results,
        "all_parse_ok": all(r["parses"] for r in parse_results),
        "import_boundary_results": import_results,
        "all_imports_resolved": all(r["resolved"] for r in import_results) if import_results else True,
        "n_import_checks": len(import_results),
        "pytest_after_fix": pytest_after,
    }
    return result


def main():
    all_results = {}
    for n in (1, 2, 3):
        print(f"\n===== Verifying entangled run {n} =====")
        r = verify_run(n)
        all_results[f"run{n}"] = r
        print(f"  FIX applied: {r['n_fix_applied']}  (non-FIX skipped: {r['n_skipped_non_fix']})")
        print(f"  all applies matched source original_line: {r['all_original_lines_matched_source']}")
        print(f"  all applies ok (no null proposed_line etc): {r['all_applies_ok']}")
        print(f"  all touched files parse: {r['all_parse_ok']}")
        print(f"  import-boundary checks: {r['n_import_checks']}, all resolved: {r['all_imports_resolved']}")
        for ir in r["import_boundary_results"]:
            if not ir["resolved"]:
                print(f"    FAILED IMPORT: {ir['id']} {ir['statement']!r}\n{ir['stderr']}")
        if r["hard_site_fix_attempts"]:
            print(f"  *** Run attempted a FIX on a no-single-line-fix site: {[a['id'] for a in r['hard_site_fix_attempts']]} ***")
        pt = r["pytest_after_fix"]
        print(f"  pytest after fix: {pt['summary_line']}  failed={pt['failed_tests']}  errored={pt['errored_tests']}  matches_baseline={pt['matches_baseline']}")

    with open(os.path.join(HERE, "verification_results.json"), "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nWrote {os.path.join(HERE, 'verification_results.json')}")


if __name__ == "__main__":
    main()
