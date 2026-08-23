"""Offline, fully-scripted end-to-end smoke test: runs pipeline.run() with
a fake client that answers every stage (factblock, vocabulary, adjudicate,
fixgen) with a canned response, `verify_install=False` so no venv/pip/
network is touched. No real cost, no real API call -- this exercises the
new fix-generation wiring through pipeline.py and report.py the same way
test_replay_targetb.py exercises detection-only plumbing, just with a
scripted fake instead of a recorded cassette (there's no cassette for a
stage that never made a real call yet)."""
import json
import os

from apidrift import pipeline

GUIDE_TEXT = "`old_pkg` is renamed to `new_pkg`. Update every import."


class ScriptedLLMClient:
    def __init__(self, script):
        self._script = script
        self.calls = []

    def complete(self, stage, system_text, user_text, schema, cache_system=False,
                 max_tokens=8000, effort="high"):
        self.calls.append(stage)
        for prefix, response in self._script.items():
            if stage.startswith(prefix):
                return response
        raise AssertionError(f"no scripted response for stage {stage!r}")


def _script():
    return {
        "factblock": {
            "package_name": "old_pkg",
            "facts": [{"number": 1, "text": "`old_pkg` is renamed to `new_pkg`."}],
        },
        "vocabulary": {
            "patterns": [{"name": "p1", "regex": r"\bold_pkg\b"}],
        },
        "adjudicate_chunk_000": {
            "proposed_sites": [{
                "file": "mod.py", "line": 1, "snippet": "import old_pkg",
                "pattern": "1", "reason": "import of the renamed package",
            }],
            "flag_uncertain": [],
            "considered_and_rejected": [],
        },
        "fixgen_chunk_000": {
            "fixes": [{
                "file": "mod.py", "line": 1,
                "original_line": "import old_pkg", "proposed_line": "import new_pkg",
                "reason": "fact 1: package renamed",
            }],
            "flagged_for_human": [],
        },
    }


def test_pipeline_runs_fix_generation_end_to_end(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "mod.py").write_text("import old_pkg\n\ndef f():\n    return 1\n")

    guide_path = tmp_path / "guide.md"
    guide_path.write_text(GUIDE_TEXT)

    workdir = str(tmp_path / "workdir")
    client = ScriptedLLMClient(_script())

    result = pipeline.run(
        repo_root=str(repo_root),
        guide_path=str(guide_path),
        workdir=workdir,
        client=client,
        chunk_size=40,
        force=True,
        verify_install=False,
    )

    assert result["fixgen_expanded"]["fixes"][0]["proposed_line"] == "import new_pkg"
    assert result["fixgen_expanded"]["flagged_for_human"] == []
    assert result["verification_report"]["parse_and_line_match"]["ok"] is True
    assert result["verification_report"]["install"]["available"] is False

    assert os.path.isfile(os.path.join(workdir, "fixes.json"))
    with open(os.path.join(workdir, "fixes.json")) as f:
        fixes_on_disk = json.load(f)
    assert fixes_on_disk["fixes"][0]["file"] == "mod.py"

    assert os.path.isfile(os.path.join(workdir, "verification.json"))

    with open(result["report_path"]) as f:
        report_text = f.read()
    assert "## FIX (1)" in report_text
    assert "import new_pkg" in report_text
    assert "## FLAG-FOR-HUMAN (0)" in report_text


def test_pipeline_skip_fix_generation_writes_no_fixgen_artifacts(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "mod.py").write_text("import old_pkg\n")

    guide_path = tmp_path / "guide.md"
    guide_path.write_text(GUIDE_TEXT)

    workdir = str(tmp_path / "workdir")
    client = ScriptedLLMClient(_script())

    result = pipeline.run(
        repo_root=str(repo_root),
        guide_path=str(guide_path),
        workdir=workdir,
        client=client,
        chunk_size=40,
        force=True,
        skip_fix_generation=True,
    )

    assert result["fixgen_expanded"] is None
    assert not os.path.isfile(os.path.join(workdir, "fixes.json"))
    assert not any(c.startswith("fixgen") for c in client.calls)
