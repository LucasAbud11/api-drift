"""Offline CLI tests for `run --gapfill --dry-run`: gap-fill's plan is
only computable without an API call when BOTH --factblock and
--vocabulary are already on disk (coverage needs both), so this exercises
that gate plus the happy path printing a real chunk plan. No network, no
client ever constructed -- same style as test_factblock_chunking.py's
own --dry-run tests.
"""
import json

import pytest

from apidrift import cli, llm

GUIDE_TEXT = "`WidgetSession` now requires a positional timeout argument."


def _fb(package_name, texts):
    return {"package_name": package_name,
            "facts": [{"number": i + 1, "text": t} for i, t in enumerate(texts)]}


def _write(path, data):
    path.write_text(json.dumps(data))


def test_dry_run_gapfill_without_both_artifacts_explains_and_makes_no_call(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def _boom(*a, **k):
        raise AssertionError("AnthropicLLMClient must never be constructed on --dry-run")
    monkeypatch.setattr(llm, "AnthropicLLMClient", _boom)
    monkeypatch.setattr(cli, "AnthropicLLMClient", _boom)

    repo = tmp_path / "repo"
    repo.mkdir()
    guide_path = tmp_path / "guide.md"
    guide_path.write_text(GUIDE_TEXT)

    cli.main(["run", "--repo", str(repo), "--guide", str(guide_path), "--gapfill", "--dry-run"])

    out = capsys.readouterr().out
    assert "pass --factblock and --vocabulary" in out
    assert "GAP-FILL PLAN" not in out


def test_dry_run_gapfill_with_both_artifacts_prints_chunk_plan(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def _boom(*a, **k):
        raise AssertionError("AnthropicLLMClient must never be constructed on --dry-run")
    monkeypatch.setattr(llm, "AnthropicLLMClient", _boom)
    monkeypatch.setattr(cli, "AnthropicLLMClient", _boom)

    repo = tmp_path / "repo"
    repo.mkdir()
    guide_path = tmp_path / "guide.md"
    guide_path.write_text(GUIDE_TEXT)

    factblock_path = tmp_path / "factblock.json"
    _write(factblock_path, _fb("widget", [GUIDE_TEXT]))
    vocabulary_path = tmp_path / "vocabulary.json"
    # Leaves WidgetSession uncovered, same as a real gap.
    _write(vocabulary_path, {"patterns": {"p1": r"\bWidgetOldThing\b"}})

    cli.main([
        "run", "--repo", str(repo), "--guide", str(guide_path),
        "--factblock", str(factblock_path), "--vocabulary", str(vocabulary_path),
        "--gapfill", "--gapfill-chunk-size", "5", "--dry-run",
    ])

    out = capsys.readouterr().out
    assert "GAP-FILL PLAN" in out
    assert "1 target fact(s)" in out
    assert "1 planned chunk(s) of up to 5 each" in out
    assert "no API calls made yet" in out


def test_dry_run_gapfill_with_nothing_to_fill_reports_zero_targets(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(llm, "AnthropicLLMClient", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(cli, "AnthropicLLMClient", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))

    repo = tmp_path / "repo"
    repo.mkdir()
    guide_path = tmp_path / "guide.md"
    guide_path.write_text(GUIDE_TEXT)

    factblock_path = tmp_path / "factblock.json"
    _write(factblock_path, _fb("widget", [GUIDE_TEXT]))
    vocabulary_path = tmp_path / "vocabulary.json"
    _write(vocabulary_path, {"patterns": {"p1": r"\bWidgetSession\b"}})

    cli.main([
        "run", "--repo", str(repo), "--guide", str(guide_path),
        "--factblock", str(factblock_path), "--vocabulary", str(vocabulary_path),
        "--gapfill", "--dry-run",
    ])

    out = capsys.readouterr().out
    assert "GAP-FILL PLAN -- 0 target fact(s), 0 planned chunk(s)" in out


def test_dry_run_gapfill_with_invalid_loaded_vocabulary_stops_cleanly(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    guide_path = tmp_path / "guide.md"
    guide_path.write_text(GUIDE_TEXT)

    factblock_path = tmp_path / "factblock.json"
    _write(factblock_path, _fb("widget", [GUIDE_TEXT]))
    vocabulary_path = tmp_path / "vocabulary.json"
    vocabulary_path.write_text("not json")

    with pytest.raises(SystemExit):
        cli.main([
            "run", "--repo", str(repo), "--guide", str(guide_path),
            "--factblock", str(factblock_path), "--vocabulary", str(vocabulary_path),
            "--gapfill", "--dry-run",
        ])
    assert "STOPPED" in capsys.readouterr().err
