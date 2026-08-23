"""Unit tests for mechanical fix verification (apidrift/verify.py). Tier 1
(parse + line-match) is tested directly, no network. Tier 2 (real install)
is tested with subprocess/venv monkeypatched out -- no real pip install, no
network -- covering the unavailable-degrades-gracefully path and the
success path without depending on the environment having network access.
"""
import os

from apidrift import verify
from apidrift.reposafe import RepoReader


def _make_repo(tmp_path, filename, body):
    full = tmp_path / filename
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(body)
    return RepoReader(str(tmp_path))


def test_parse_and_line_match_ok(tmp_path):
    reader = _make_repo(tmp_path, "mod.py", "import old_pkg\n\ndef f():\n    return 1\n")
    fixes = [{"file": "mod.py", "line": 1, "original_line": "import old_pkg",
              "proposed_line": "import new_pkg", "reason": "renamed"}]

    report = verify.check_parse_and_line_match(reader, fixes)

    assert report["ok"] is True
    assert report["all_line_match_ok"] is True
    assert report["file_parse_results"]["mod.py"]["parses"] is True


def test_parse_and_line_match_detects_wrong_original(tmp_path):
    reader = _make_repo(tmp_path, "mod.py", "import old_pkg\n")
    fixes = [{"file": "mod.py", "line": 1, "original_line": "import something_else",
              "proposed_line": "import new_pkg", "reason": "renamed"}]

    report = verify.check_parse_and_line_match(reader, fixes)

    assert report["ok"] is False
    assert report["items"][0]["line_match_ok"] is False


def test_parse_and_line_match_detects_syntax_break(tmp_path):
    reader = _make_repo(tmp_path, "mod.py", "import old_pkg\n\ndef f():\n    return 1\n")
    fixes = [{"file": "mod.py", "line": 1, "original_line": "import old_pkg",
              "proposed_line": "import new_pkg(((", "reason": "broken"}]

    report = verify.check_parse_and_line_match(reader, fixes)

    assert report["ok"] is False
    assert report["file_parse_results"]["mod.py"]["parses"] is False


def test_parse_and_line_match_applies_multiple_fixes_in_one_file_together(tmp_path):
    reader = _make_repo(
        tmp_path, "mod.py",
        "import old_pkg\n\ndef f():\n    return old_pkg.thing()\n",
    )
    fixes = [
        {"file": "mod.py", "line": 1, "original_line": "import old_pkg",
         "proposed_line": "import new_pkg", "reason": "r1"},
        {"file": "mod.py", "line": 4, "original_line": "    return old_pkg.thing()",
         "proposed_line": "    return new_pkg.thing()", "reason": "r2"},
    ]

    report = verify.check_parse_and_line_match(reader, fixes)

    assert report["ok"] is True
    assert len(report["items"]) == 2


def test_check_install_no_import_fixes_is_unavailable(tmp_path):
    fixes = [{"file": "mod.py", "line": 4, "original_line": "    return old_pkg.thing()",
              "proposed_line": "    return new_pkg.thing()", "reason": "attribute rename"}]

    report = verify.check_install("new_pkg", fixes, str(tmp_path))

    assert report["available"] is False
    assert "nothing for this tier to check" in report["reason"]


def test_check_install_pip_failure_degrades_gracefully(tmp_path, monkeypatch):
    fixes = [{"file": "mod.py", "line": 1, "original_line": "import old_pkg",
              "proposed_line": "import new_pkg", "reason": "renamed"}]

    monkeypatch.setattr(verify.venv, "create", lambda path, with_pip=True: None)

    class _FakeCompleted:
        def __init__(self, returncode, stderr=""):
            self.returncode = returncode
            self.stdout = ""
            self.stderr = stderr

    def fake_run(cmd, capture_output, text, timeout):
        return _FakeCompleted(1, stderr="ERROR: No matching distribution found")

    monkeypatch.setattr(verify.subprocess, "run", fake_run)
    monkeypatch.setattr(os.path, "isfile", lambda p: True)  # pretend venv python exists

    report = verify.check_install("new_pkg", fixes, str(tmp_path))

    assert report["available"] is False
    assert "pip install" in report["reason"]


def test_check_install_success_path_resolves_imports(tmp_path, monkeypatch):
    fixes = [{"file": "mod.py", "line": 1, "original_line": "import old_pkg",
              "proposed_line": "import new_pkg", "reason": "renamed"}]

    monkeypatch.setattr(verify.venv, "create", lambda path, with_pip=True: None)
    monkeypatch.setattr(os.path, "isfile", lambda p: True)

    class _FakeCompleted:
        def __init__(self, returncode, stderr=""):
            self.returncode = returncode
            self.stdout = ""
            self.stderr = stderr

    calls = {"n": 0}

    def fake_run(cmd, capture_output, text, timeout):
        calls["n"] += 1
        return _FakeCompleted(0)  # both the pip install call and the import-check call succeed

    monkeypatch.setattr(verify.subprocess, "run", fake_run)

    report = verify.check_install("new_pkg", fixes, str(tmp_path))

    assert report["available"] is True
    assert report["all_resolved"] is True
    assert calls["n"] == 2  # one install call, one import-check call
