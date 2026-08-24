"""Unit tests for apidrift/writer.py -- the only module allowed to write
into --into. All offline, real local git repos via subprocess (no network,
no LLM calls)."""
import os
import subprocess

import pytest

from apidrift import writer


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(path, files):
    os.makedirs(path, exist_ok=True)
    _git("init", "-q", cwd=path)
    _git("config", "user.email", "test@example.com", cwd=path)
    _git("config", "user.name", "Test", cwd=path)
    for relpath, body in files.items():
        full = os.path.join(path, relpath)
        os.makedirs(os.path.dirname(full) or path, exist_ok=True)
        with open(full, "w") as f:
            f.write(body)
    _git("add", "-A", cwd=path)
    _git("commit", "-q", "-m", "initial", cwd=path)
    return path


# ---------------------------------------------------------------------
# Safety gates
# ---------------------------------------------------------------------

def test_check_git_repo_rejects_nonexistent_path(tmp_path):
    with pytest.raises(writer.ApplyError, match="does not exist"):
        writer.check_git_repo(str(tmp_path / "nope"))


def test_check_git_repo_rejects_non_git_dir(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(writer.ApplyError, match="not a git repository"):
        writer.check_git_repo(str(plain))


def test_check_git_repo_accepts_real_repo(tmp_path):
    repo = str(tmp_path / "repo")
    _init_repo(repo, {"mod.py": "import old_pkg\n"})
    writer.check_git_repo(repo)  # should not raise


def test_check_clean_worktree_accepts_clean_repo(tmp_path):
    repo = str(tmp_path / "repo")
    _init_repo(repo, {"mod.py": "import old_pkg\n"})
    writer.check_clean_worktree(repo)  # should not raise


def test_check_clean_worktree_rejects_unstaged_changes(tmp_path):
    repo = str(tmp_path / "repo")
    _init_repo(repo, {"mod.py": "import old_pkg\n"})
    with open(os.path.join(repo, "mod.py"), "a") as f:
        f.write("x = 1\n")
    with pytest.raises(writer.ApplyError, match="staged or unstaged"):
        writer.check_clean_worktree(repo)


def test_check_clean_worktree_rejects_staged_changes(tmp_path):
    repo = str(tmp_path / "repo")
    _init_repo(repo, {"mod.py": "import old_pkg\n"})
    with open(os.path.join(repo, "mod.py"), "a") as f:
        f.write("x = 1\n")
    _git("add", "mod.py", cwd=repo)
    with pytest.raises(writer.ApplyError, match="staged or unstaged"):
        writer.check_clean_worktree(repo)


def test_check_not_analysis_repo_noop_when_unrecorded(tmp_path):
    repo = str(tmp_path / "repo")
    _init_repo(repo, {"mod.py": "import old_pkg\n"})
    writer.check_not_analysis_repo(repo, None)  # should not raise


def test_check_not_analysis_repo_rejects_same_path(tmp_path):
    repo = str(tmp_path / "repo")
    _init_repo(repo, {"mod.py": "import old_pkg\n"})
    with pytest.raises(writer.ApplyError, match="same path as the repo"):
        writer.check_not_analysis_repo(repo, repo)


def test_check_not_analysis_repo_accepts_different_path(tmp_path):
    into = str(tmp_path / "into")
    analysed = str(tmp_path / "analysed")
    _init_repo(into, {"mod.py": "import old_pkg\n"})
    os.makedirs(analysed)
    writer.check_not_analysis_repo(into, analysed)  # should not raise


# ---------------------------------------------------------------------
# check_line_matches
# ---------------------------------------------------------------------

def test_check_line_matches_ok(tmp_path):
    repo = str(tmp_path / "repo")
    _init_repo(repo, {"mod.py": "import old_pkg\n"})
    fixes = [{"file": "mod.py", "line": 1, "original_line": "import old_pkg",
              "proposed_line": "import new_pkg", "reason": "renamed"}]
    assert writer.check_line_matches(repo, fixes) == []


def test_check_line_matches_detects_drift(tmp_path):
    repo = str(tmp_path / "repo")
    _init_repo(repo, {"mod.py": "import something_else\n"})
    fixes = [{"file": "mod.py", "line": 1, "original_line": "import old_pkg",
              "proposed_line": "import new_pkg", "reason": "renamed"}]
    mismatches = writer.check_line_matches(repo, fixes)
    assert len(mismatches) == 1
    assert "drifted" in mismatches[0]["reason"]


def test_check_line_matches_detects_missing_file(tmp_path):
    repo = str(tmp_path / "repo")
    _init_repo(repo, {"mod.py": "import old_pkg\n"})
    fixes = [{"file": "gone.py", "line": 1, "original_line": "import old_pkg",
              "proposed_line": "import new_pkg", "reason": "renamed"}]
    mismatches = writer.check_line_matches(repo, fixes)
    assert len(mismatches) == 1
    assert "does not exist" in mismatches[0]["reason"]


def test_check_line_matches_detects_out_of_range(tmp_path):
    repo = str(tmp_path / "repo")
    _init_repo(repo, {"mod.py": "import old_pkg\n"})
    fixes = [{"file": "mod.py", "line": 99, "original_line": "import old_pkg",
              "proposed_line": "import new_pkg", "reason": "renamed"}]
    mismatches = writer.check_line_matches(repo, fixes)
    assert len(mismatches) == 1
    assert "out of range" in mismatches[0]["reason"]


# ---------------------------------------------------------------------
# apply_fixes
# ---------------------------------------------------------------------

def test_apply_fixes_writes_correct_content(tmp_path):
    repo = str(tmp_path / "repo")
    _init_repo(repo, {"mod.py": "import old_pkg\n\ndef f():\n    return old_pkg.g()\n"})
    fixes = [{"file": "mod.py", "line": 1, "original_line": "import old_pkg",
              "proposed_line": "import new_pkg", "reason": "renamed"}]

    result = writer.apply_fixes(repo, fixes, dry_run=False)

    with open(os.path.join(repo, "mod.py")) as f:
        content = f.read()
    assert content == "import new_pkg\n\ndef f():\n    return old_pkg.g()\n"
    assert result["files_modified"] == ["mod.py"]
    assert result["n_fixes"] == 1
    assert "-import old_pkg" in result["diffs"][0]
    assert "+import new_pkg" in result["diffs"][0]


def test_apply_fixes_applies_multiple_fixes_same_file(tmp_path):
    repo = str(tmp_path / "repo")
    _init_repo(repo, {"mod.py": "import old_pkg\nold_pkg.setup()\n"})
    fixes = [
        {"file": "mod.py", "line": 1, "original_line": "import old_pkg",
         "proposed_line": "import new_pkg", "reason": "renamed"},
        {"file": "mod.py", "line": 2, "original_line": "old_pkg.setup()",
         "proposed_line": "new_pkg.setup()", "reason": "renamed"},
    ]

    result = writer.apply_fixes(repo, fixes, dry_run=False)

    with open(os.path.join(repo, "mod.py")) as f:
        content = f.read()
    assert content == "import new_pkg\nnew_pkg.setup()\n"
    assert result["n_fixes"] == 2


def test_apply_fixes_dry_run_writes_nothing(tmp_path):
    repo = str(tmp_path / "repo")
    original = "import old_pkg\n"
    _init_repo(repo, {"mod.py": original})
    fixes = [{"file": "mod.py", "line": 1, "original_line": "import old_pkg",
              "proposed_line": "import new_pkg", "reason": "renamed"}]

    result = writer.apply_fixes(repo, fixes, dry_run=True)

    with open(os.path.join(repo, "mod.py")) as f:
        assert f.read() == original
    assert "+import new_pkg" in result["diffs"][0]


def test_apply_fixes_aborts_all_on_one_mismatch(tmp_path):
    repo = str(tmp_path / "repo")
    original_a = "import old_pkg\n"
    original_b = "import something_else\n"
    _init_repo(repo, {"a.py": original_a, "b.py": original_b})
    fixes = [
        {"file": "a.py", "line": 1, "original_line": "import old_pkg",
         "proposed_line": "import new_pkg", "reason": "renamed"},
        {"file": "b.py", "line": 1, "original_line": "import old_pkg",
         "proposed_line": "import new_pkg", "reason": "renamed"},
    ]

    with pytest.raises(writer.ApplyError, match="do not match"):
        writer.apply_fixes(repo, fixes, dry_run=False)

    with open(os.path.join(repo, "a.py")) as f:
        assert f.read() == original_a
    with open(os.path.join(repo, "b.py")) as f:
        assert f.read() == original_b


def test_apply_fixes_aborts_on_syntax_break_with_zero_writes(tmp_path):
    repo = str(tmp_path / "repo")
    original_a = "import old_pkg\n"
    original_b = "import old_pkg\n"
    _init_repo(repo, {"a.py": original_a, "b.py": original_b})
    fixes = [
        {"file": "a.py", "line": 1, "original_line": "import old_pkg",
         "proposed_line": "import new_pkg", "reason": "renamed"},
        {"file": "b.py", "line": 1, "original_line": "import old_pkg",
         "proposed_line": "import new_pkg(((", "reason": "broken"},
    ]

    with pytest.raises(writer.ApplyError, match="fails to parse"):
        writer.apply_fixes(repo, fixes, dry_run=False)

    with open(os.path.join(repo, "a.py")) as f:
        assert f.read() == original_a
    with open(os.path.join(repo, "b.py")) as f:
        assert f.read() == original_b


def test_apply_fixes_empty_list_is_a_noop(tmp_path):
    repo = str(tmp_path / "repo")
    _init_repo(repo, {"mod.py": "import old_pkg\n"})
    result = writer.apply_fixes(repo, [], dry_run=False)
    assert result == {"diffs": [], "files_modified": [], "n_fixes": 0}
