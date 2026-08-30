"""Mechanical fix verification, per DESIGN.md section 4. Two independent
tiers, both best-effort and non-fatal -- neither ever raises out of this
module, and neither is part of the fixes.json hard-fail contract
(validate.py's two-bucket check). A verification failure is reported
alongside a fix, not used to silently drop or rewrite it: the human
reviewing report.md sees the flag and decides.

Tier 1 (`check_parse_and_line_match`, always runs, no dependency):
  - confirms every fix's claimed `original_lines` actually match the real
    source across that fix's whole line/end_line span (catches a
    hallucinated target before it ever gets applied to anything)
  - applies every fix for a file together -- in descending line order, so
    a block fix that changes the line count never shifts an earlier fix's
    index (see _apply_block_fixes) -- then `ast.parse()`s the result
    (catches a syntactically broken replacement, and an interaction
    between two fixes landing in the same file)

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


def _check_overlaps(relpath, items):
    """Raises ValueError if any two of this file's fixes claim overlapping
    line ranges -- two fixes may never touch the same physical line. Not
    expected in practice (fixgen produces at most one fix per confirmed
    site, and jointly-resolved group members are disjoint statements), but
    a block fix's range makes this a real possibility a single-line-only
    scheme never had to check, so it's checked explicitly rather than
    silently corrupting the patched text."""
    ordered = sorted(items, key=lambda i: i["line"])
    for a, b in zip(ordered, ordered[1:]):
        if b["line"] <= a["end_line"]:
            raise ValueError(
                f"{relpath}: fixes at line {a['line']}-{a['end_line']} and "
                f"{b['line']}-{b['end_line']} overlap -- cannot apply both"
            )


def _apply_block_fixes(lines, items):
    """lines: a file's physical lines (keepends=True). items: fixes for
    this one file, each with line/end_line/proposed_lines. Applies in
    DESCENDING order of `line` -- a block replacement can change the line
    count, but every fix not yet applied has a strictly lower `line`
    (overlap is already ruled out by _check_overlaps), so replacing a
    later range never shifts an earlier one's index. This is the fix for
    the latent corruption bug a block fix introduces: the old scheme
    (ascending order, one line in for one line out) silently mis-splices
    the moment any fix's replacement has a different line count than its
    original span."""
    new_lines = list(lines)
    for item in sorted(items, key=lambda i: i["line"], reverse=True):
        start_idx = item["line"] - 1
        end_idx = item["end_line"]  # exclusive slice bound (end_line is 1-indexed inclusive)
        ending = _line_ending_of(lines[end_idx - 1]) or "\n"
        proposed = [
            pl if pl.endswith(("\n", "\r\n")) else pl + ending
            for pl in item["proposed_lines"]
        ]
        new_lines[start_idx:end_idx] = proposed
    return new_lines


def check_parse_and_line_match(reader, expanded_fixes):
    """expanded_fixes: the post-expand_duplicates `fixes` list (each item:
    file, line, end_line, original_lines, proposed_lines, reason). Returns
    a report dict: per-item results plus an `all_ok` summary flag."""
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
        _check_overlaps(relpath, items)
        for item in sorted(items, key=lambda i: i["line"]):
            start_idx = item["line"] - 1
            end_idx = item["end_line"]
            if start_idx < 0 or end_idx > len(lines):
                items_report.append({
                    "file": relpath, "line": item["line"], "line_match_ok": False,
                    "error": f"lines {item['line']}-{item['end_line']} are out of range "
                             f"for {relpath} ({len(lines)} lines)",
                })
                continue
            actual_block = [l.rstrip("\r\n") for l in lines[start_idx:end_idx]]
            claimed_block = [l.rstrip("\r\n") for l in item["original_lines"]]
            match_ok = actual_block == claimed_block or \
                [l.strip() for l in actual_block] == [l.strip() for l in claimed_block]
            items_report.append({
                "file": relpath, "line": item["line"], "line_match_ok": match_ok,
                "actual_original": "\n".join(actual_block),
                "claimed_original": "\n".join(item["original_lines"]),
            })

        patched_lines = _apply_block_fixes(lines, items)
        patched_src = "".join(patched_lines)
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
    """Fixes whose proposed_lines is (still) a single import statement
    naming `package_name` -- the only shape tier 2 can meaningfully check
    without executing arbitrary application code. A block fix with more
    than one proposed line is never an import-shaped fix by this
    definition, even if one of its lines happens to be an import -- tier 2
    only ever execs a single statement in isolation, and a multi-line
    block's lines are not independently valid Python."""
    out = []
    for item in expanded_fixes:
        if len(item["proposed_lines"]) != 1:
            continue
        stripped = item["proposed_lines"][0].strip()
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
            "reason": "no fix's proposed_lines is a single import statement naming "
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
        stripped = item["proposed_lines"][0].strip()
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
