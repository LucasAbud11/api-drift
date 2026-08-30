"""Integration tests for `api-drift apply`, driven through apidrift.cli.main
exactly as a real invocation would be -- no network, no LLM calls. Covers
the ordering contract: gate failures (non-git, dirty, same-repo-as-analysed)
must stop before any write, and fixes.json's two-bucket shape (FIX applied,
FLAG-FOR-HUMAN only reported) must be respected end to end.
"""
import json
import os
import subprocess

import pytest

from apidrift import cli


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(path, files):
    os.makedirs(path, exist_ok=True)
    _git("init", "-q", cwd=path)
    _git("config", "user.email", "test@example.com", cwd=path)
    _git("config", "user.name", "Test", cwd=path)
    for relpath, body in files.items():
        with open(os.path.join(path, relpath), "w") as f:
            f.write(body)
    _git("add", "-A", cwd=path)
    _git("commit", "-q", "-m", "initial", cwd=path)
    return path


def _write_fixes_json(path, fixes, flagged_for_human=None, repo_root=None):
    data = {"fixes": fixes, "flagged_for_human": flagged_for_human or []}
    if repo_root is not None:
        data["repo_root"] = repo_root
    with open(path, "w") as f:
        json.dump(data, f)
    return path


def test_apply_writes_fix_and_reports_flagged(tmp_path, capsys):
    into = str(tmp_path / "into")
    _init_repo(into, {"mod.py": "import old_pkg\n"})
    fixes_path = _write_fixes_json(
        str(tmp_path / "fixes.json"),
        fixes=[{"file": "mod.py", "line": 1, "end_line": 1, "original_lines": ["import old_pkg"], "proposed_lines": ["import new_pkg"], "reason": "renamed"}],
        flagged_for_human=[{"file": "mod.py", "line": 5, "reason": "structural refactor"}],
    )

    cli.main(["apply", "--fixes", fixes_path, "--into", into])

    with open(os.path.join(into, "mod.py")) as f:
        assert f.read() == "import new_pkg\n"

    out = capsys.readouterr().out
    assert "Applied 1 fix(es) across 1 file(s), 1 skipped as FLAG-FOR-HUMAN." in out
    assert "mod.py:5 -- structural refactor" in out


def test_apply_dry_run_writes_nothing(tmp_path, capsys):
    into = str(tmp_path / "into")
    _init_repo(into, {"mod.py": "import old_pkg\n"})
    fixes_path = _write_fixes_json(
        str(tmp_path / "fixes.json"),
        fixes=[{"file": "mod.py", "line": 1, "end_line": 1, "original_lines": ["import old_pkg"], "proposed_lines": ["import new_pkg"], "reason": "renamed"}],
    )

    cli.main(["apply", "--fixes", fixes_path, "--into", into, "--dry-run"])

    with open(os.path.join(into, "mod.py")) as f:
        assert f.read() == "import old_pkg\n"

    out = capsys.readouterr().out
    assert "Would apply 1 fix(es)" in out
    assert "+import new_pkg" in out


def test_apply_stops_on_non_git_into(tmp_path, capsys):
    into = str(tmp_path / "into")
    os.makedirs(into)
    fixes_path = _write_fixes_json(str(tmp_path / "fixes.json"), fixes=[])

    with pytest.raises(SystemExit):
        cli.main(["apply", "--fixes", fixes_path, "--into", into])

    err = capsys.readouterr().err
    assert "STOPPED" in err
    assert "not a git repository" in err


def test_apply_stops_on_dirty_worktree(tmp_path, capsys):
    into = str(tmp_path / "into")
    _init_repo(into, {"mod.py": "import old_pkg\n"})
    with open(os.path.join(into, "mod.py"), "a") as f:
        f.write("x = 1\n")
    fixes_path = _write_fixes_json(str(tmp_path / "fixes.json"), fixes=[])

    with pytest.raises(SystemExit):
        cli.main(["apply", "--fixes", fixes_path, "--into", into])

    err = capsys.readouterr().err
    assert "STOPPED" in err
    assert "staged or unstaged" in err


def test_apply_stops_when_into_is_the_analysed_repo(tmp_path, capsys):
    into = str(tmp_path / "into")
    _init_repo(into, {"mod.py": "import old_pkg\n"})
    fixes_path = _write_fixes_json(
        str(tmp_path / "fixes.json"), fixes=[], repo_root=os.path.abspath(into),
    )

    with pytest.raises(SystemExit):
        cli.main(["apply", "--fixes", fixes_path, "--into", into])

    err = capsys.readouterr().err
    assert "STOPPED" in err
    assert "same path as the repo" in err


def test_apply_stops_all_or_nothing_on_line_drift(tmp_path, capsys):
    into = str(tmp_path / "into")
    _init_repo(into, {"a.py": "import old_pkg\n", "b.py": "import old_pkg\n"})
    fixes_path = _write_fixes_json(
        str(tmp_path / "fixes.json"),
        fixes=[
            {"file": "a.py", "line": 1, "end_line": 1, "original_lines": ["import old_pkg"], "proposed_lines": ["import new_pkg"], "reason": "renamed"},
            {"file": "b.py", "line": 1, "end_line": 1, "original_lines": ["import DRIFTED"], "proposed_lines": ["import new_pkg"], "reason": "renamed"},
        ],
    )

    with pytest.raises(SystemExit):
        cli.main(["apply", "--fixes", fixes_path, "--into", into])

    err = capsys.readouterr().err
    assert "STOPPED" in err
    with open(os.path.join(into, "a.py")) as f:
        assert f.read() == "import old_pkg\n"  # zero files modified, even the matching one


def test_apply_stops_on_malformed_fixes_json(tmp_path, capsys):
    into = str(tmp_path / "into")
    _init_repo(into, {"mod.py": "import old_pkg\n"})
    fixes_path = tmp_path / "fixes.json"
    fixes_path.write_text(json.dumps({"fixes": []}))  # missing flagged_for_human

    with pytest.raises(SystemExit):
        cli.main(["apply", "--fixes", str(fixes_path), "--into", into])

    assert "STOPPED" in capsys.readouterr().err
