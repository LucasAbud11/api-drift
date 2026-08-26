"""pipeline.run() must persist the fact<->pattern coverage relation as
structured JSON in the workdir, not only as vocabulary_coverage.txt
prose. Offline, fully-scripted -- no real API call, same ScriptedLLMClient
shape as test_pipeline_fixgen_smoke.py."""
import json
import os

from apidrift import guards, pipeline

GUIDE_TEXT = (
    "`old_pkg.Foo` is renamed to `old_pkg.Bar`. "
    "CONFIRMED UNCHANGED: `old_pkg.Baz` is not affected. "
    "`old_pkg.Qux.run()` gains a required `timeout=` kwarg."
)


class ScriptedLLMClient:
    def __init__(self, script):
        self._script = script
        self.calls = []

    def complete(self, stage, system_text, user_text, schema, cache_system=False,
                 cache_ttl="5m", max_tokens=8000, effort="high"):
        self.calls.append(stage)
        for prefix, response in self._script.items():
            if stage.startswith(prefix):
                return response
        raise AssertionError(f"no scripted response for stage {stage!r}")


def _script():
    return {
        "factblock": {
            "package_name": "old_pkg",
            "facts": [
                {"number": 1, "text": "`old_pkg.Foo` is renamed to `old_pkg.Bar`."},
                {"number": 2, "text": "CONFIRMED UNCHANGED: `old_pkg.Baz` is not affected."},
                {"number": 3, "text": "`old_pkg.Qux.run()` gains a required `timeout=` kwarg."},
            ],
        },
        "vocabulary": {
            # p1 covers fact 1's `old_pkg.Foo` span but not `old_pkg.Bar` --
            # deliberately partial. Fact 2 is non-breaking (no pattern
            # expected). Fact 3's identifiers have no covering pattern at
            # all -- deliberately uncovered.
            "patterns": [{"name": "p1_foo", "regex": r"\bold_pkg\.Foo\b"}],
        },
        "adjudicate_chunk_000": {
            "proposed_sites": [{
                "file": "mod.py", "line": 2, "snippet": "old_pkg.Foo()",
                "pattern": "1", "reason": "matches fact 1",
            }],
            "flag_uncertain": [],
            "considered_and_rejected": [],
        },
    }


def test_pipeline_writes_fact_pattern_coverage_json(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "mod.py").write_text("import old_pkg\nold_pkg.Foo()\n")

    guide_path = tmp_path / "guide.md"
    guide_path.write_text(GUIDE_TEXT)

    workdir = str(tmp_path / "workdir")
    client = ScriptedLLMClient(_script())

    pipeline.run(
        repo_root=str(repo_root),
        guide_path=str(guide_path),
        workdir=workdir,
        client=client,
        chunk_size=40,
        force=True,
        skip_fix_generation=True,
    )

    path = os.path.join(workdir, "fact_pattern_coverage.json")
    assert os.path.isfile(path)
    with open(path) as f:
        data = json.load(f)

    assert data["summary"] == {
        "non_breaking": 1, "no_identifier": 0, "covered": 0, "partial": 1, "uncovered": 1,
    }
    by_number = {row["number"]: row for row in data["facts"]}
    assert by_number[1]["status"] == "partial"
    assert by_number[2]["status"] == "non_breaking"
    assert by_number[3]["status"] == "uncovered"

    # The persisted rows must be exactly what compute_fact_pattern_coverage
    # produces independently -- pipeline.py must not have its own copy of
    # the matching logic.
    with open(os.path.join(workdir, "factblock.json")) as f:
        fb = json.load(f)
    with open(os.path.join(workdir, "vocabulary.json")) as f:
        vocab = json.load(f)
    assert data["facts"] == guards.compute_fact_pattern_coverage(fb, vocab)
