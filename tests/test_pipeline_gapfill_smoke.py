"""Offline, fully-scripted end-to-end smoke tests for --gapfill's wiring
through pipeline.py: the confirmation gate (a plan is printed and the run
stops with GapfillNeedsConfirmation until --gapfill-yes is also given),
and, once confirmed, that gap-fill's new pattern actually flows through
grep/adjudicate the same way stage 2's own patterns do. No network, no
LLM calls, no real cost -- same fully-scripted-client style as
test_pipeline_fixgen_smoke.py.
"""
import os

import pytest

from apidrift import pipeline

GUIDE_TEXT = "`WidgetSession` now requires a positional timeout argument."


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
            "package_name": "widget",
            "facts": [{"number": 1, "text": GUIDE_TEXT}],
        },
        # Deliberately leaves `WidgetSession` uncovered -- the pattern
        # here matches nothing in the repo, simulating stage 2's real
        # gap while still satisfying validate_vocabulary's non-empty
        # requirement.
        "vocabulary": {
            "patterns": [{"name": "p1", "regex": r"\bWidgetOldThing\b"}],
        },
        "gapfill_chunk_000": {
            "patterns": [{"name": "gf_widgetsess", "regex": r"\bWidgetSession\b"}],
            "declined": [],
        },
        "adjudicate_chunk_000": {
            "proposed_sites": [{
                "file": "mod.py", "line": 2, "snippet": "session = WidgetSession(timeout=5)",
                "pattern": "gf_widgetsess", "reason": "fact 1: WidgetSession construction site",
                "related_sites": [],
            }],
            "flag_uncertain": [],
            "considered_and_rejected": [],
        },
    }


def _setup_repo(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    # Line 1 gives prefilter stage A (package-relevance) a bare `widget`
    # token to match -- `WidgetSession` alone doesn't word-boundary-match
    # a `\bwidget\b`-shaped relevance pattern.
    (repo_root / "mod.py").write_text("import widget\nsession = WidgetSession(timeout=5)\n")
    guide_path = tmp_path / "guide.md"
    guide_path.write_text(GUIDE_TEXT)
    return str(repo_root), str(guide_path)


def test_gapfill_without_confirmation_stops_before_any_gapfill_call(tmp_path):
    repo_root, guide_path = _setup_repo(tmp_path)
    workdir = str(tmp_path / "workdir")
    client = ScriptedLLMClient(_script())

    with pytest.raises(pipeline.GapfillNeedsConfirmation) as exc_info:
        pipeline.run(
            repo_root=repo_root, guide_path=guide_path, workdir=workdir, client=client,
            force=True, skip_fix_generation=True, verify_install=False,
            gapfill=True, gapfill_confirmed=False,
        )

    assert "1 target fact(s)" in exc_info.value.plan_report
    assert "no API calls made yet" in exc_info.value.plan_report
    assert not any(c.startswith("gapfill") for c in client.calls)
    assert not os.path.isdir(os.path.join(workdir, "gapfill"))


def test_gapfill_off_by_default_never_touches_gapfill_module(tmp_path):
    repo_root, guide_path = _setup_repo(tmp_path)
    workdir = str(tmp_path / "workdir")
    client = ScriptedLLMClient(_script())

    # gapfill defaults False -- must run exactly like it always has,
    # guard failure and all, with no gap-fill plan or call.
    with pytest.raises(pipeline.GuardFailure):
        pipeline.run(
            repo_root=repo_root, guide_path=guide_path, workdir=workdir, client=client,
            skip_fix_generation=True, verify_install=False,
        )
    assert not any(c.startswith("gapfill") for c in client.calls)


def test_gapfill_confirmed_merges_new_pattern_through_to_candidates(tmp_path):
    repo_root, guide_path = _setup_repo(tmp_path)
    workdir = str(tmp_path / "workdir")
    client = ScriptedLLMClient(_script())

    result = pipeline.run(
        repo_root=repo_root, guide_path=guide_path, workdir=workdir, client=client,
        force=True, skip_fix_generation=True, verify_install=False,
        gapfill=True, gapfill_confirmed=True,
    )

    assert "gf_widgetsess" in result["vocabulary"]["patterns"]
    assert any(c["file"] == "mod.py" and c["line"] == 2 for c in result["candidates"])
    assert result["expanded"]["proposed_sites"][0]["file"] == "mod.py"
    assert os.path.isfile(os.path.join(workdir, "vocabulary_after_gapfill.json"))
    assert os.path.isfile(os.path.join(workdir, "gapfill", "report.json"))

    # Coverage after gap-fill has nothing left to flag -- the guard
    # should not need --force for this repo's one fact anymore. Confirm
    # by re-checking the persisted coverage file directly.
    import json
    with open(os.path.join(workdir, "fact_pattern_coverage.json")) as f:
        cov = json.load(f)
    assert cov["summary"]["partial"] == 0
    assert cov["summary"]["uncovered"] == 0


def test_gapfill_vocabulary_json_names_the_merged_vocabulary_not_the_pre_merge_one(tmp_path):
    # Regression test: workdir/vocabulary.json used to be written before the
    # --gapfill block ran, so it permanently held the pre-merge vocabulary on
    # any run where gap-fill actually added patterns -- the real merged
    # result only ever landed in vocabulary_after_gapfill.json. A later
    # `--vocabulary <workdir>/vocabulary.json` would then silently reload the
    # non-gap-filled vocabulary. vocabulary.json must always match whatever
    # was actually used for grep/adjudicate in the same run, and the
    # pre-merge input must still be recoverable under its own name.
    repo_root, guide_path = _setup_repo(tmp_path)
    workdir = str(tmp_path / "workdir")
    client = ScriptedLLMClient(_script())

    pipeline.run(
        repo_root=repo_root, guide_path=guide_path, workdir=workdir, client=client,
        force=True, skip_fix_generation=True, verify_install=False,
        gapfill=True, gapfill_confirmed=True,
    )

    import json
    with open(os.path.join(workdir, "vocabulary.json")) as f:
        on_disk = json.load(f)
    with open(os.path.join(workdir, "vocabulary_after_gapfill.json")) as f:
        after_gapfill = json.load(f)
    with open(os.path.join(workdir, "vocabulary_pre_gapfill.json")) as f:
        pre_gapfill = json.load(f)

    assert "gf_widgetsess" in on_disk["patterns"]
    assert on_disk == after_gapfill
    assert "gf_widgetsess" not in pre_gapfill["patterns"]


def test_gapfill_id_check_warning_is_printed_but_does_not_stop_the_run(tmp_path):
    # A pattern id that doesn't read as an abbreviation of its own
    # regex is non-fatal (see validate.py's _validate_gapfill_pattern_
    # anti_goodhart) -- the run must still complete, the pattern must
    # still merge in, and the warning must reach print_fn so a human
    # running this for real sees it.
    repo_root, guide_path = _setup_repo(tmp_path)
    workdir = str(tmp_path / "workdir")
    script = _script()
    script["gapfill_chunk_000"] = {
        "patterns": [{"name": "gf_totallyunrelated", "regex": r"\bWidgetSession\b"}],
        "declined": [],
    }
    script["adjudicate_chunk_000"]["proposed_sites"][0]["pattern"] = "gf_totallyunrelated"
    client = ScriptedLLMClient(script)

    printed = []
    result = pipeline.run(
        repo_root=repo_root, guide_path=guide_path, workdir=workdir, client=client,
        force=True, skip_fix_generation=True, verify_install=False,
        gapfill=True, gapfill_confirmed=True, print_fn=printed.append,
    )

    assert "gf_totallyunrelated" in result["vocabulary"]["patterns"]
    joined = "\n".join(printed)
    assert "WARNING" in joined
    assert "gf_totallyunrelated" in joined
