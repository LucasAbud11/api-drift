import os

import pytest

from apidrift import preflight


def _guide(tmp_path, text="some real guide text"):
    p = tmp_path / "guide.md"
    p.write_text(text)
    return str(p)


def test_missing_repo_is_rejected(tmp_path):
    with pytest.raises(preflight.PreflightError, match="--repo"):
        preflight.check_inputs(str(tmp_path / "nope"), _guide(tmp_path), str(tmp_path / "wd"))


def test_repo_that_is_a_file_is_rejected(tmp_path):
    not_a_dir = tmp_path / "repo_file"
    not_a_dir.write_text("x")
    with pytest.raises(preflight.PreflightError, match="--repo"):
        preflight.check_inputs(str(not_a_dir), _guide(tmp_path), str(tmp_path / "wd"))


def test_missing_guide_is_rejected(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(preflight.PreflightError, match="--guide"):
        preflight.check_inputs(str(repo), str(tmp_path / "nope.md"), str(tmp_path / "wd"))


def test_empty_guide_is_rejected(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(preflight.PreflightError, match="--guide is empty"):
        preflight.check_inputs(str(repo), _guide(tmp_path, text=""), str(tmp_path / "wd"))


def test_workdir_inside_repo_is_rejected(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(preflight.PreflightError):
        preflight.check_inputs(str(repo), _guide(tmp_path), str(repo / ".api-drift-run"))


def test_valid_inputs_pass(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    preflight.check_inputs(str(repo), _guide(tmp_path), str(tmp_path / "wd"))  # should not raise


def test_api_key_missing_is_rejected(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    with pytest.raises(preflight.PreflightError, match="ANTHROPIC_API_KEY"):
        preflight.check_api_key()


def test_api_key_present_passes(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
    preflight.check_api_key()  # should not raise


def test_auth_token_alone_also_passes(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-123")
    preflight.check_api_key()  # should not raise
