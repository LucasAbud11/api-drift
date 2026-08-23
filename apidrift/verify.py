"""Mechanical fix verification, per DESIGN.md section 4. Two independent
tiers, both best-effort and non-fatal -- neither ever raises out of this
module, and neither is part of the fixes.json hard-fail contract
(validate.py's two-bucket check). A verification failure is reported
alongside a fix, not used to silently drop or rewrite it: the human
reviewing report.md sees the flag and decides.

Tier 1 (`check_parse_and_line_match`, always runs, no dependency):
  - confirms every fix's claimed `original_line` actually matches the real
    source at that file:line (catches a hallucinated target line before it
    ever gets applied to anything)
  - applies every fix for a file together, then `ast.parse()`s the result
    (catches a syntactically broken replacement, and an interaction between
    two fixes landing in the same file)

Tier 2 (`check_install`, best-effort, opt-out via verify_install=False):
  DESIGN.md's "real install, default tier" -- pip-installs the migration's
  target package into an isolated venv under `workdir` and execs every
  touched import statement against it. Never crashes the run: no network,
  no matching version, an unbuildable extension, or any other install
  failure all degrade to `available: False` with the reason recorded, per
  DESIGN.md's own "reported as a downgraded tier when used, never presented
  with tier-2 confidence" -- callers must not treat an unavailable tier 2
  as tier-2-clean.
"""
import ast
import os
import subprocess
import sys
import venv


def _split_lines_keepends(text):
    return text.splitlines(keepends=True)


def _line_ending_of(line):
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    return ""


def check_parse_and_line_match(reader, expanded_fixes):
    """expanded_fixes: the post-expand_duplicates `fixes` list (each item:
    file, line, original_line, proposed_line, reason). Returns a report
    dict: per-item results plus an `all_ok` summary flag."""
    by_file = {}
    for item in expanded_fixes:
        by_file.setdefault(item["file"], []).append(item)

    items_report = []
    file_parse_results = {}

    for relpath, items in by_file.items():
        try:
            src = reader.read_text(relpath)
        except OSError as e:
            for item in items:
                items_report.append({
                    "file": relpath, "line": item["line"], "line_match_ok": False,
                    "error": f"could not read source file: {e}",
                })
            file_parse_results[relpath] = {"parses": False, "error": str(e)}
            continue

        lines = _split_lines_keepends(src)
        patched = list(lines)
        for item in sorted(items, key=lambda i: i["line"]):
            idx = item["line"] - 1
            if idx < 0 or idx >= len(lines):
                items_report.append({
                    "file": relpath, "line": item["line"], "line_match_ok": False,
                    "error": f"line {item['line']} is out of range for {relpath} "
                             f"({len(lines)} lines)",
                })
                continue
            actual = lines[idx]
            match_ok = actual.rstrip("\r\n") == item["original_line"].rstrip("\r\n") or \
                actual.strip() == item["original_line"].strip()
            ending = _line_ending_of(actual) or "\n"
            new_line = item["proposed_line"]
            if not new_line.endswith(("\n", "\r\n")):
                new_line = new_line + ending
            patched[idx] = new_line
            items_report.append({
                "file": relpath, "line": item["line"], "line_match_ok": match_ok,
                "actual_original": actual.rstrip("\r\n"),
                "claimed_original": item["original_line"],
            })

        patched_src = "".join(patched)
        try:
            ast.parse(patched_src)
            file_parse_results[relpath] = {"parses": True}
        except SyntaxError as e:
            file_parse_results[relpath] = {"parses": False, "error": str(e)}

    all_line_match_ok = all(r.get("line_match_ok", False) for r in items_report)
    all_parse_ok = all(r["parses"] for r in file_parse_results.values())

    return {
        "tier": "parse_and_line_match",
        "items": items_report,
        "file_parse_results": file_parse_results,
        "all_line_match_ok": all_line_match_ok,
        "all_parse_ok": all_line_match_ok and all_parse_ok if items_report else all_parse_ok,
        "ok": all_line_match_ok and all_parse_ok,
    }


def _import_statements(expanded_fixes, package_name):
    """Fixes whose proposed_line is itself an import statement naming
    `package_name` -- the only shape tier 2 can meaningfully check without
    executing arbitrary application code."""
    out = []
    for item in expanded_fixes:
        stripped = item["proposed_line"].strip()
        if (stripped.startswith(f"import {package_name}")
                or stripped.startswith(f"from {package_name}")
                or stripped.startswith(f"import {package_name}.")):
            out.append(item)
    return out


def check_install(package_name, expanded_fixes, workdir, version=None, timeout=180):
    """Best-effort. Returns {"tier": "install", "available": bool,
    "reason": str, "items": [...]} -- `available=False` means tier 2
    genuinely did not run (no network, install failure, nothing to check);
    it is not itself a verification failure of any fix."""
    to_check = _import_statements(expanded_fixes, package_name)
    if not to_check:
        return {
            "tier": "install", "available": False,
            "reason": "no fix's proposed_line is an import statement naming "
                       f"{package_name!r} -- nothing for this tier to check",
            "items": [],
        }

    venv_dir = os.path.join(workdir, "verify_venv")
    try:
        if not os.path.isdir(venv_dir):
            venv.create(venv_dir, with_pip=True)
    except Exception as e:  # noqa: BLE001 -- any venv-creation failure degrades, never crashes the run
        return {
            "tier": "install", "available": False,
            "reason": f"could not create an isolated venv under workdir: {e}",
            "items": [],
        }

    venv_python = os.path.join(venv_dir, "bin", "python")
    if not os.path.isfile(venv_python):
        venv_python = os.path.join(venv_dir, "Scripts", "python.exe")  # Windows layout

    spec = f"{package_name}=={version}" if version else package_name
    try:
        proc = subprocess.run(
            [venv_python, "-m", "pip", "install", "--quiet", spec],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "tier": "install", "available": False,
            "reason": f"pip install {spec!r} timed out after {timeout}s",
            "items": [],
        }
    except OSError as e:
        return {
            "tier": "install", "available": False,
            "reason": f"could not run pip in the isolated venv: {e}",
            "items": [],
        }
    if proc.returncode != 0:
        return {
            "tier": "install", "available": False,
            "reason": f"pip install {spec!r} failed (exit {proc.returncode}): "
                       f"{proc.stderr.strip()[-1000:]}",
            "items": [],
        }

    items_report = []
    for item in to_check:
        stripped = item["proposed_line"].strip()
        script = f"{stripped}\n"
        try:
            check = subprocess.run(
                [venv_python, "-c", script],
                capture_output=True, text=True, timeout=30,
            )
        except subprocess.TimeoutExpired:
            items_report.append({
                "file": item["file"], "line": item["line"], "statement": stripped,
                "resolved": False, "error": "import check timed out",
            })
            continue
        items_report.append({
            "file": item["file"], "line": item["line"], "statement": stripped,
            "resolved": check.returncode == 0,
            "error": check.stderr.strip()[-1000:] if check.returncode != 0 else "",
        })

    return {
        "tier": "install", "available": True,
        "reason": f"installed {spec!r} into an isolated venv under workdir",
        "items": items_report,
        "all_resolved": all(r["resolved"] for r in items_report),
    }


def run(reader, package_name, expanded_fixes, workdir, verify_install=True, version=None):
    """Runs both tiers and returns the combined report written to
    workdir/verification.json. Never raises -- a verification-tier failure
    is data for the report, not a pipeline hard-fail."""
    report = {"parse_and_line_match": check_parse_and_line_match(reader, expanded_fixes)}
    if verify_install and expanded_fixes:
        report["install"] = check_install(package_name, expanded_fixes, workdir, version=version)
    else:
        report["install"] = {
            "tier": "install", "available": False,
            "reason": "skipped (--no-verify-install)" if not verify_install else "no fixes to verify",
            "items": [],
        }
    return report
