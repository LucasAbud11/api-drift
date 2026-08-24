"""Offline tests for --factblock/--vocabulary (loading a previously
derived, guide-only artifact instead of re-deriving it) and the max_tokens
ceilings for the two guide-only stages. No network, no LLM calls -- a
scripted fake client answers whichever stages actually need to run.
"""
import json
import os

import pytest

from apidrift import pipeline, preflight, validate
from apidrift.stages import factblock, vocabulary

GUIDE_TEXT = "`old_pkg` is renamed to `new_pkg`. Update every import."


class ScriptedLLMClient:
    def __init__(self, script):
        self._script = script
        self.calls = []

    def complete(self, stage, system_text, user_text, schema, cache_system=False,
                 max_tokens=8000, effort="high"):
        self.calls.append({"stage": stage, "max_tokens": max_tokens})
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
            "proposed_sites": [], "flag_uncertain": [],
            "considered_and_rejected": [
                {"file": "mod.py", "line": 1, "reason": "not relevant for this test"},
            ],
        },
    }


def _repo(tmp_path, body="import old_pkg\n"):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "mod.py").write_text(body)
    return str(repo_root)


def _guide(tmp_path, text=GUIDE_TEXT):
    guide_path = tmp_path / "guide.md"
    guide_path.write_text(text)
    return str(guide_path)


# ---------------------------------------------------------------------
# max_tokens ceilings (regression guards -- these are the concrete numbers
# the task raised, catch a silent revert of either)
# ---------------------------------------------------------------------

def test_factblock_stage_requests_32000_max_tokens():
    client = ScriptedLLMClient(_script())
    factblock.derive(client, GUIDE_TEXT)
    assert client.calls[0]["max_tokens"] == 32000


def test_vocabulary_stage_requests_16000_max_tokens():
    client = ScriptedLLMClient(_script())
    fb = factblock.derive(client, GUIDE_TEXT)
    vocabulary.derive(client, GUIDE_TEXT, fb)
    assert client.calls[-1]["max_tokens"] == 16000


# ---------------------------------------------------------------------
# Loading a fact block / vocabulary instead of deriving
# ---------------------------------------------------------------------

def test_loading_factblock_skips_stage_1_and_still_validates(tmp_path):
    repo_root = _repo(tmp_path)
    guide_path = _guide(tmp_path)
    guide_sha256 = pipeline.hashlib.sha256(GUIDE_TEXT.encode("utf-8")).hexdigest()

    factblock_path = tmp_path / "factblock.json"
    factblock_path.write_text(json.dumps({
        "package_name": "old_pkg",
        "facts": [{"number": 1, "text": "`old_pkg` is renamed to `new_pkg`."}],
        "guide_sha256": guide_sha256,
    }))

    script = _script()
    del script["factblock"]  # if the stage tried to derive anyway, this raises AssertionError
    client = ScriptedLLMClient(script)

    result = pipeline.run(
        repo_root=repo_root, guide_path=guide_path, workdir=str(tmp_path / "workdir"),
        client=client, force=True, skip_fix_generation=True,
        factblock_path=str(factblock_path),
    )

    assert not any(c["stage"] == "factblock" for c in client.calls)
    assert result["factblock"]["package_name"] == "old_pkg"
    assert result["manifest"]["factblock_source"] == f"loaded:{os.path.abspath(factblock_path)}"
    assert result["manifest"]["vocabulary_source"] == "derived"

    with open(os.path.join(str(tmp_path / "workdir"), "manifest.json")) as f:
        manifest_on_disk = json.load(f)
    assert manifest_on_disk["guide_sha256"] == guide_sha256


def test_loading_vocabulary_skips_stage_2_and_still_validates(tmp_path):
    repo_root = _repo(tmp_path)
    guide_path = _guide(tmp_path)
    guide_sha256 = pipeline.hashlib.sha256(GUIDE_TEXT.encode("utf-8")).hexdigest()

    vocabulary_path = tmp_path / "vocabulary.json"
    vocabulary_path.write_text(json.dumps({
        "patterns": {"p1": r"\bold_pkg\b"},
        "guide_sha256": guide_sha256,
    }))

    script = _script()
    del script["vocabulary"]
    client = ScriptedLLMClient(script)

    result = pipeline.run(
        repo_root=repo_root, guide_path=guide_path, workdir=str(tmp_path / "workdir"),
        client=client, force=True, skip_fix_generation=True,
        vocabulary_path=str(vocabulary_path),
    )

    assert not any(c["stage"] == "vocabulary" for c in client.calls)
    assert result["vocabulary"]["patterns"] == {"p1": r"\bold_pkg\b"}
    assert result["manifest"]["vocabulary_source"] == f"loaded:{os.path.abspath(vocabulary_path)}"
    assert result["manifest"]["factblock_source"] == "derived"


def test_loading_both_skips_both_stages(tmp_path):
    repo_root = _repo(tmp_path)
    guide_path = _guide(tmp_path)
    guide_sha256 = pipeline.hashlib.sha256(GUIDE_TEXT.encode("utf-8")).hexdigest()

    factblock_path = tmp_path / "factblock.json"
    factblock_path.write_text(json.dumps({
        "package_name": "old_pkg",
        "facts": [{"number": 1, "text": "`old_pkg` is renamed to `new_pkg`."}],
        "guide_sha256": guide_sha256,
    }))
    vocabulary_path = tmp_path / "vocabulary.json"
    vocabulary_path.write_text(json.dumps({
        "patterns": {"p1": r"\bold_pkg\b"},
        "guide_sha256": guide_sha256,
    }))

    client = ScriptedLLMClient({"adjudicate_chunk_000": _script()["adjudicate_chunk_000"]})

    result = pipeline.run(
        repo_root=repo_root, guide_path=guide_path, workdir=str(tmp_path / "workdir"),
        client=client, force=True, skip_fix_generation=True,
        factblock_path=str(factblock_path), vocabulary_path=str(vocabulary_path),
    )

    assert client.calls  # only the adjudication call happened
    assert all(c["stage"].startswith("adjudicate") for c in client.calls)
    assert result["manifest"]["factblock_source"].startswith("loaded:")
    assert result["manifest"]["vocabulary_source"].startswith("loaded:")


# ---------------------------------------------------------------------
# Loading a BAD artifact still hits validation/guards -- loading is not a
# bypass.
# ---------------------------------------------------------------------

def test_loading_malformed_factblock_hard_fails(tmp_path):
    repo_root = _repo(tmp_path)
    guide_path = _guide(tmp_path)

    factblock_path = tmp_path / "factblock.json"
    factblock_path.write_text(json.dumps({"package_name": "old_pkg", "facts": []}))  # empty facts

    client = ScriptedLLMClient(_script())

    with pytest.raises(ValueError, match="VALIDATION FAILED"):
        pipeline.run(
            repo_root=repo_root, guide_path=guide_path, workdir=str(tmp_path / "workdir"),
            client=client, force=True, skip_fix_generation=True,
            factblock_path=str(factblock_path),
        )


def test_loading_malformed_vocabulary_hard_fails(tmp_path):
    repo_root = _repo(tmp_path)
    guide_path = _guide(tmp_path)

    vocabulary_path = tmp_path / "vocabulary.json"
    vocabulary_path.write_text(json.dumps({"patterns": {}}))  # empty patterns

    client = ScriptedLLMClient(_script())

    with pytest.raises(ValueError, match="VALIDATION FAILED"):
        pipeline.run(
            repo_root=repo_root, guide_path=guide_path, workdir=str(tmp_path / "workdir"),
            client=client, force=True, skip_fix_generation=True,
            vocabulary_path=str(vocabulary_path),
        )


def test_loading_factblock_that_fails_coverage_guard_still_stops(tmp_path):
    """A loaded fact block that doesn't name enough of the guide's own
    symbols must still trip check_factblock_coverage -- validation alone
    (well-formed JSON shape) isn't the only check loading has to survive."""
    repo_root = _repo(tmp_path)
    guide_text = ("`old_pkg` is renamed to `new_pkg`. Also `old_pkg.helper()` "
                  "becomes `new_pkg.helper()`, and `OLD_CONST` becomes `NEW_CONST`.")
    guide_path = _guide(tmp_path, text=guide_text)

    factblock_path = tmp_path / "factblock.json"
    factblock_path.write_text(json.dumps({
        "package_name": "old_pkg",
        "facts": [{"number": 1, "text": "something unrelated, no guide symbols named"}],
    }))

    client = ScriptedLLMClient(_script())

    with pytest.raises(pipeline.GuardFailure):
        pipeline.run(
            repo_root=repo_root, guide_path=guide_path, workdir=str(tmp_path / "workdir"),
            client=client, force=False, skip_fix_generation=True,
            factblock_path=str(factblock_path),
        )


def test_missing_factblock_path_is_a_clean_preflight_error(tmp_path):
    repo_root = _repo(tmp_path)
    guide_path = _guide(tmp_path)
    client = ScriptedLLMClient(_script())

    with pytest.raises(preflight.PreflightError, match="--factblock"):
        pipeline.run(
            repo_root=repo_root, guide_path=guide_path, workdir=str(tmp_path / "workdir"),
            client=client, force=True, skip_fix_generation=True,
            factblock_path=str(tmp_path / "nope.json"),
        )


# ---------------------------------------------------------------------
# sha256 mismatch warning (loud, not a hard fail)
# ---------------------------------------------------------------------

def test_factblock_guide_sha_mismatch_warns_but_does_not_stop(tmp_path):
    repo_root = _repo(tmp_path)
    guide_path = _guide(tmp_path)

    factblock_path = tmp_path / "factblock.json"
    factblock_path.write_text(json.dumps({
        "package_name": "old_pkg",
        "facts": [{"number": 1, "text": "`old_pkg` is renamed to `new_pkg`."}],
        "guide_sha256": "0" * 64,  # deliberately wrong
    }))

    client = ScriptedLLMClient(_script())
    printed = []

    result = pipeline.run(
        repo_root=repo_root, guide_path=guide_path, workdir=str(tmp_path / "workdir"),
        client=client, force=True, skip_fix_generation=True,
        factblock_path=str(factblock_path), print_fn=printed.append,
    )

    assert result["factblock"]["package_name"] == "old_pkg"  # run proceeded
    assert any("WARNING" in line and "guide_sha256" in line for line in printed)


def test_vocabulary_guide_sha_mismatch_warns_but_does_not_stop(tmp_path):
    repo_root = _repo(tmp_path)
    guide_path = _guide(tmp_path)

    vocabulary_path = tmp_path / "vocabulary.json"
    vocabulary_path.write_text(json.dumps({
        "patterns": {"p1": r"\bold_pkg\b"},
        "guide_sha256": "0" * 64,
    }))

    client = ScriptedLLMClient(_script())
    printed = []

    result = pipeline.run(
        repo_root=repo_root, guide_path=guide_path, workdir=str(tmp_path / "workdir"),
        client=client, force=True, skip_fix_generation=True,
        vocabulary_path=str(vocabulary_path), print_fn=printed.append,
    )

    assert result["vocabulary"]["patterns"] == {"p1": r"\bold_pkg\b"}
    assert any("WARNING" in line and "guide_sha256" in line for line in printed)


def test_loaded_artifact_with_no_recorded_sha_warns(tmp_path):
    repo_root = _repo(tmp_path)
    guide_path = _guide(tmp_path)

    factblock_path = tmp_path / "factblock.json"
    factblock_path.write_text(json.dumps({
        "package_name": "old_pkg",
        "facts": [{"number": 1, "text": "`old_pkg` is renamed to `new_pkg`."}],
    }))  # no guide_sha256 at all -- e.g. predates this feature

    client = ScriptedLLMClient(_script())
    printed = []

    pipeline.run(
        repo_root=repo_root, guide_path=guide_path, workdir=str(tmp_path / "workdir"),
        client=client, force=True, skip_fix_generation=True,
        factblock_path=str(factblock_path), print_fn=printed.append,
    )

    assert any("WARNING" in line and "no recorded guide_sha256" in line for line in printed)


def test_derived_artifacts_record_matching_guide_sha256(tmp_path):
    """Not a loaded artifact -- confirms a freshly derived factblock.json/
    vocabulary.json is stamped with the current guide's sha256, which is
    the field a later run's --factblock/--vocabulary load depends on."""
    repo_root = _repo(tmp_path)
    guide_path = _guide(tmp_path)
    guide_sha256 = pipeline.hashlib.sha256(GUIDE_TEXT.encode("utf-8")).hexdigest()

    client = ScriptedLLMClient(_script())
    result = pipeline.run(
        repo_root=repo_root, guide_path=guide_path, workdir=str(tmp_path / "workdir"),
        client=client, force=True, skip_fix_generation=True,
    )

    assert result["factblock"]["guide_sha256"] == guide_sha256
    assert result["vocabulary"]["guide_sha256"] == guide_sha256
    assert result["manifest"]["guide_sha256"] == guide_sha256
    assert result["manifest"]["factblock_source"] == "derived"
    assert result["manifest"]["vocabulary_source"] == "derived"
