"""Offline tests for pipeline.run()'s per-guard --force: `force=True`/
`False` keep meaning "bypass every guard"/"bypass none", exactly as
before, but `force` now also accepts a comma-separated string or any
iterable of guards.GUARD_NAMES to bypass only those. Named suppression
must not silence a different, unnamed guard's own failure; an unknown
name must stop the run before any stage executes (never a silent
no-op); and every bypass -- blanket or named -- must print that guard's
one-line verdict to stdout, not leave it recoverable only from its
workdir/<name>.txt report (see REPORT.md: check_pattern_shape's verdict
on gf_tooldecor was correct and on disk on every real run, and nobody
read it, because a blanket --force let the run complete either way).

Fully scripted, no network -- same ScriptedLLMClient shape as
test_pipeline_gapfill_smoke.py.
"""
import os

import pytest

from apidrift import cli, guards, pipeline

# Four distinct guide symbols; the fact block below only ever names one of
# them (`pkg.A`), giving check_factblock_coverage a 1/4 = 25% ratio --
# below its 30% floor, so it fails deterministically on every run of this
# fixture.
GUIDE_TEXT = "`pkg.A`, `pkg.B`, `pkg.C`, `pkg.D` are all affected."


class ScriptedLLMClient:
    def __init__(self, script):
        self._script = script
        self.calls = []
        # Only needed for the CLI-level tests below, which run cli.main()
        # to completion -- its `finally` block prints a usage report off
        # this shape regardless of how the run ended.
        self.usage_totals = {
            "input_tokens": 0, "output_tokens": 0,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
        }

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
            "package_name": "pkg",
            "facts": [{"number": 1, "text": "`pkg.A` is renamed."}],
        },
        # No pattern for `pkg.A` at all -- the fact block's only fact is
        # left uncovered, failing check_vocabulary_coverage. The one
        # pattern present is fully literal (no open span) and matches
        # nothing in the repo below, so pattern_shape and vocabulary_yield
        # both pass cleanly -- only factblock_coverage and
        # vocabulary_coverage fail on this fixture.
        "vocabulary": {
            "patterns": [{"name": "p1", "regex": r"\bIrrelevantMarker\b"}],
        },
        "adjudicate_chunk_000": {
            "proposed_sites": [], "flag_uncertain": [], "considered_and_rejected": [],
        },
    }


def _setup(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "mod.py").write_text("x = 1\n")
    guide_path = tmp_path / "guide.md"
    guide_path.write_text(GUIDE_TEXT)
    return str(repo_root), str(guide_path)


def test_no_force_the_first_failing_guard_stops_the_run(tmp_path):
    repo_root, guide_path = _setup(tmp_path)
    workdir = str(tmp_path / "workdir")
    client = ScriptedLLMClient(_script())

    with pytest.raises(pipeline.GuardFailure) as exc_info:
        pipeline.run(repo_root=repo_root, guide_path=guide_path, workdir=workdir,
                      client=client, skip_fix_generation=True, verify_install=False)

    assert exc_info.value.name == "factblock_coverage"


def test_named_bypass_suppresses_only_that_guard(tmp_path):
    repo_root, guide_path = _setup(tmp_path)
    workdir = str(tmp_path / "workdir")
    client = ScriptedLLMClient(_script())

    # factblock_coverage is named -- bypassed. vocabulary_coverage is NOT
    # named -- it still fails and still stops the run, proving named
    # suppression doesn't leak to a guard it wasn't given.
    with pytest.raises(pipeline.GuardFailure) as exc_info:
        pipeline.run(repo_root=repo_root, guide_path=guide_path, workdir=workdir,
                      client=client, skip_fix_generation=True, verify_install=False,
                      force=["factblock_coverage"])

    assert exc_info.value.name == "vocabulary_coverage"


def test_naming_every_failing_guard_lets_the_run_complete(tmp_path):
    repo_root, guide_path = _setup(tmp_path)
    workdir = str(tmp_path / "workdir")
    client = ScriptedLLMClient(_script())

    result = pipeline.run(repo_root=repo_root, guide_path=guide_path, workdir=workdir,
                           client=client, skip_fix_generation=True, verify_install=False,
                           force="factblock_coverage,vocabulary_coverage")

    assert result is not None


def test_unknown_guard_name_stops_before_any_call_or_workdir_write(tmp_path):
    repo_root, guide_path = _setup(tmp_path)
    workdir = str(tmp_path / "workdir")
    client = ScriptedLLMClient(_script())

    with pytest.raises(ValueError, match="unknown guard name"):
        pipeline.run(repo_root=repo_root, guide_path=guide_path, workdir=workdir,
                      client=client, skip_fix_generation=True, verify_install=False,
                      force="nope_not_a_real_guard")

    assert client.calls == []
    assert not os.path.exists(workdir)


def test_unknown_name_among_valid_ones_also_stops_the_run(tmp_path):
    repo_root, guide_path = _setup(tmp_path)
    workdir = str(tmp_path / "workdir")
    client = ScriptedLLMClient(_script())

    # A typo must not silently fall back to "bypass nothing" -- one bad
    # name in an otherwise-valid list still raises.
    with pytest.raises(ValueError, match="unknown guard name"):
        pipeline.run(repo_root=repo_root, guide_path=guide_path, workdir=workdir,
                      client=client, skip_fix_generation=True, verify_install=False,
                      force="factblock_coverage,pattren_shape")

    assert client.calls == []


def test_bypassed_guards_reach_stdout_not_only_the_workdir_file(tmp_path, capsys):
    repo_root, guide_path = _setup(tmp_path)
    workdir = str(tmp_path / "workdir")
    client = ScriptedLLMClient(_script())

    pipeline.run(repo_root=repo_root, guide_path=guide_path, workdir=workdir,
                 client=client, skip_fix_generation=True, verify_install=False,
                 force=True)

    out = capsys.readouterr().out
    assert "GUARD BYPASSED [factblock_coverage]" in out
    assert "GUARD BYPASSED [vocabulary_coverage]" in out
    assert "GUARD(S) BYPASSED (--force): factblock_coverage, vocabulary_coverage" in out

    # Every guard writes its report under its own name, pass or fail --
    # not just the ones that happened to fail this run.
    for name in guards.GUARD_NAMES:
        assert os.path.isfile(os.path.join(workdir, f"{name}.txt"))


def test_bare_force_true_still_bypasses_every_guard(tmp_path):
    repo_root, guide_path = _setup(tmp_path)
    workdir = str(tmp_path / "workdir")
    client = ScriptedLLMClient(_script())

    result = pipeline.run(repo_root=repo_root, guide_path=guide_path, workdir=workdir,
                           client=client, skip_fix_generation=True, verify_install=False,
                           force=True)

    assert result is not None


# --- CLI-level: the same behavior through argparse and cli.main(), not
# just through pipeline.run() directly. ANTHROPIC_API_KEY is set to a
# dummy value so preflight.check_api_key() passes without hitting the
# network; AnthropicLLMClient is monkeypatched to the same scripted,
# offline client used above instead of a real SDK client.

def _cli_args(repo_root, guide_path, workdir, force_flag=None):
    args = ["run", "--repo", repo_root, "--guide", guide_path, "--workdir", workdir,
            "--skip-fix-generation", "--no-verify-install"]
    if force_flag is not None:
        args.append(force_flag)
    return args


def test_cli_unknown_force_name_is_a_clean_stopped_not_a_traceback(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    monkeypatch.setattr(cli, "AnthropicLLMClient", lambda model=None: ScriptedLLMClient(_script()))

    repo_root, guide_path = _setup(tmp_path)
    workdir = str(tmp_path / "workdir")

    with pytest.raises(SystemExit):
        cli.main(_cli_args(repo_root, guide_path, workdir, "--force=not_a_real_guard"))

    err = capsys.readouterr().err
    assert "STOPPED" in err
    assert "unknown guard name" in err
    assert not os.path.exists(workdir)


def test_cli_named_force_flag_bypasses_only_the_named_guard(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    monkeypatch.setattr(cli, "AnthropicLLMClient", lambda model=None: ScriptedLLMClient(_script()))

    repo_root, guide_path = _setup(tmp_path)
    workdir = str(tmp_path / "workdir")

    with pytest.raises(SystemExit):
        cli.main(_cli_args(repo_root, guide_path, workdir, "--force=factblock_coverage"))

    err = capsys.readouterr().err
    assert "STOPPED" in err
    # The un-named guard is the one that actually stopped the run, and the
    # message tells the user exactly which --force=<name> would clear it.
    assert "Re-run with --force=vocabulary_coverage" in err


def test_cli_bare_force_bypasses_everything_and_names_every_guard_on_stdout(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    monkeypatch.setattr(cli, "AnthropicLLMClient", lambda model=None: ScriptedLLMClient(_script()))

    repo_root, guide_path = _setup(tmp_path)
    workdir = str(tmp_path / "workdir")

    cli.main(_cli_args(repo_root, guide_path, workdir, "--force"))

    out = capsys.readouterr().out
    assert "GUARD BYPASSED [factblock_coverage]" in out
    assert "GUARD BYPASSED [vocabulary_coverage]" in out
    assert "GUARD(S) BYPASSED (--force): factblock_coverage, vocabulary_coverage" in out
