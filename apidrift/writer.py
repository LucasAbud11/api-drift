"""The only module allowed to write into `--into`, a separate working copy
of the analysed repo -- never into `--repo` itself, and structurally kept
apart from reposafe.py: this module never receives a RepoReader or a
`--repo` path at all, only an explicit `--into` destination the caller
supplies. RepoReader's read-only guarantee (no write/delete/rename method
exists on it, by construction) is untouched by this file's existence.

Every gate here runs before a single byte is written. Two independent
safety properties, both load-bearing:

- **Never touch the analysed repo.** `check_not_analysis_repo` refuses to
  run at all if `--into` resolves to the same path fixes.json says was
  analysed.
- **Never leave `--into` worse off than a clean `git diff` can undo.**
  `check_clean_worktree` requires a clean worktree before anything is
  written, and `apply_fixes` validates every fix (line-match, then parse)
  entirely in memory before writing anything -- a failure at either check
  means zero files were ever opened for writing, which trivially satisfies
  "restore all touched files to their original content" because nothing
  left original content in the first place.
"""
import ast
import difflib
import os
import subprocess


class ApplyError(Exception):
    """A safety gate failed before any write happened, or a fix failed
    in-memory validation before any write happened. Every raise site in
    this module corresponds to one STOPPED: line in cli.py."""


def resolve(path):
    return os.path.realpath(os.path.abspath(path))


def check_git_repo(into_root):
    if not os.path.isdir(into_root):
        raise ApplyError(f"--into path does not exist or is not a directory: {into_root}")
    try:
        result = subprocess.run(
            ["git", "-C", into_root, "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True,
        )
    except OSError as e:
        raise ApplyError(f"could not run git against --into ({into_root}): {e}") from e
    if result.returncode != 0 or result.stdout.strip() != "true":
        raise ApplyError(f"--into is not a git repository: {into_root}")


def check_clean_worktree(into_root):
    """No staged or unstaged changes -- git diff is the user's only undo
    for what apply_fixes writes, so it must start clean. Untracked files
    are not checked: they aren't something `git diff` can undo or lose,
    and apply_fixes only ever writes to files a fix names, never creates
    new ones."""
    unstaged = subprocess.run(["git", "-C", into_root, "diff", "--quiet"],
                               capture_output=True, text=True)
    staged = subprocess.run(["git", "-C", into_root, "diff", "--cached", "--quiet"],
                             capture_output=True, text=True)
    for result in (unstaged, staged):
        if result.returncode not in (0, 1):
            raise ApplyError(
                f"could not read git diff status for --into ({into_root}): "
                f"{result.stderr.strip()}"
            )
    if unstaged.returncode == 1 or staged.returncode == 1:
        raise ApplyError(
            f"--into has staged or unstaged changes -- git diff is the only undo "
            f"this command gives you, so --into must start clean: {into_root}"
        )


def check_not_analysis_repo(into_root, analysis_repo_root):
    """No-op if fixes.json didn't record an analysis repo path -- that's
    a caller-level gap (fixed by pipeline.py always recording repo_root
    going forward), not something this function can check itself."""
    if not analysis_repo_root:
        return
    if resolve(into_root) == resolve(analysis_repo_root):
        raise ApplyError(
            f"--into resolves to the same path as the repo this run analysed "
            f"({analysis_repo_root!r}) -- apply must target a separate working "
            f"copy, never the analysed repo itself."
        )


def _line_ending_of(line):
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    return ""


def _read_file(into_root, relpath):
    full = os.path.join(into_root, relpath)
    with open(full, encoding="utf-8", errors="replace") as f:
        return f.read()


def _check_overlaps(relpath, items):
    """Raises ApplyError if any two of this file's fixes claim overlapping
    line ranges -- see verify.py's identical check for why this is a real
    possibility a block fix introduces that a single-line-only scheme
    never had to guard against."""
    ordered = sorted(items, key=lambda i: i["line"])
    for a, b in zip(ordered, ordered[1:]):
        if b["line"] <= a["end_line"]:
            raise ApplyError(
                f"{relpath}: fixes at line {a['line']}-{a['end_line']} and "
                f"{b['line']}-{b['end_line']} overlap -- cannot apply both, "
                f"aborting with zero files modified"
            )


def check_line_matches(into_root, fixes):
    """Re-reads each fix's target block from --into and confirms it
    matches the recorded original_lines exactly -- deliberately repeats
    verify.py's tier 1, because --into is a different checkout than the
    one analysed and may have drifted since. Returns a list of mismatch
    dicts, empty if every fix matches."""
    mismatches = []
    by_file = {}
    for fix in fixes:
        by_file.setdefault(fix["file"], []).append(fix)

    for relpath, items in by_file.items():
        full = os.path.join(into_root, relpath)
        if not os.path.isfile(full):
            for item in items:
                mismatches.append({
                    "file": relpath, "line": item["line"],
                    "reason": f"file does not exist in --into: {relpath}",
                })
            continue
        lines = _read_file(into_root, relpath).splitlines(keepends=True)
        for item in items:
            start_idx = item["line"] - 1
            end_idx = item["end_line"]
            if start_idx < 0 or end_idx > len(lines):
                mismatches.append({
                    "file": relpath, "line": item["line"],
                    "reason": f"lines {item['line']}-{item['end_line']} are out of range "
                              f"for {relpath} ({len(lines)} lines)",
                })
                continue
            actual_block = [l.rstrip("\r\n") for l in lines[start_idx:end_idx]]
            expected_block = [l.rstrip("\r\n") for l in item["original_lines"]]
            if actual_block != expected_block and \
                    [l.strip() for l in actual_block] != [l.strip() for l in expected_block]:
                mismatches.append({
                    "file": relpath, "line": item["line"],
                    "reason": f"block drifted -- expected {expected_block!r}, "
                              f"found {actual_block!r}",
                })
    return mismatches


def apply_fixes(into_root, fixes, dry_run=False):
    """All-or-nothing. Builds and validates every touched file's patched
    content entirely in memory first (line-match, then ast.parse) -- only
    once every fix and every touched file clears both checks does this
    function open anything for writing, and dry_run=True never does even
    that. Returns {"diffs": [...], "files_modified": [...], "n_fixes": int}.
    Raises ApplyError, before any write, on the first check that fails."""
    if not fixes:
        return {"diffs": [], "files_modified": [], "n_fixes": 0}

    mismatches = check_line_matches(into_root, fixes)
    if mismatches:
        detail = "\n".join(
            f"  {m['file']}:{m['line']} -- {m['reason']}" for m in mismatches
        )
        raise ApplyError(
            f"{len(mismatches)} fix(es) do not match --into's current source -- "
            f"aborting with zero files modified:\n{detail}"
        )

    by_file = {}
    for fix in fixes:
        by_file.setdefault(fix["file"], []).append(fix)

    originals = {}
    patched = {}
    diffs = []
    for relpath, items in sorted(by_file.items()):
        original_text = _read_file(into_root, relpath)
        originals[relpath] = original_text
        lines = original_text.splitlines(keepends=True)
        _check_overlaps(relpath, items)
        # Descending line order: a block fix can change the line count, so
        # applying in ascending order (the old single-line-only scheme)
        # would shift every not-yet-applied fix's index the moment any
        # earlier fix's replacement has a different length than its
        # original span. Every fix not yet applied here has a strictly
        # lower `line` (overlap already ruled out above), so replacing a
        # later range never moves an earlier one's index.
        new_lines = list(lines)
        for item in sorted(items, key=lambda i: i["line"], reverse=True):
            start_idx = item["line"] - 1
            end_idx = item["end_line"]
            ending = _line_ending_of(lines[end_idx - 1]) or "\n"
            proposed = [
                pl if pl.endswith(("\n", "\r\n")) else pl + ending
                for pl in item["proposed_lines"]
            ]
            new_lines[start_idx:end_idx] = proposed
        patched_text = "".join(new_lines)

        try:
            ast.parse(patched_text)
        except SyntaxError as e:
            raise ApplyError(
                f"applying {len(items)} fix(es) to {relpath} produces a file that "
                f"fails to parse -- aborting, zero files modified: {e}"
            ) from e

        patched[relpath] = patched_text
        diffs.append("".join(difflib.unified_diff(
            lines, new_lines, fromfile=f"a/{relpath}", tofile=f"b/{relpath}",
        )))

    if not dry_run:
        written = []
        try:
            for relpath, patched_text in patched.items():
                full = os.path.join(into_root, relpath)
                with open(full, "w", encoding="utf-8") as f:
                    f.write(patched_text)
                written.append(relpath)
        except OSError as e:
            # Belt-and-suspenders: every fix already cleared line-match and
            # parse checks above, so a failure here can only be a real I/O
            # problem (disk full, permissions changed mid-run), not a bad
            # fix -- restore whatever this loop already wrote before it
            # propagates, so a failed apply never leaves --into half-patched.
            for relpath in written:
                full = os.path.join(into_root, relpath)
                with open(full, "w", encoding="utf-8") as f:
                    f.write(originals[relpath])
            raise ApplyError(
                f"write failed partway through -- restored {len(written)} "
                f"already-written file(s) to original content: {e}"
            ) from e

    return {
        "diffs": diffs,
        "files_modified": sorted(patched.keys()),
        "n_fixes": len(fixes),
    }
