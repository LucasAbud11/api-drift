"""Offline tests for adjudication's max_tokens=16000 ceiling (raised from
8000 after a real Pydantic v1->v2 run truncated adjudicate_chunk_003 at
292 post-prefilter candidates) and its per-chunk truncation-error message
naming the chunk and pointing at --adjudicate-chunk-size, same shape
gapfill.py's own truncation test already uses. Also covers
--adjudicate-chunk-size's CLI wiring, including --chunk-size as a working
alias for the same flag. No network, no LLM calls.
"""
import types

import pytest

from apidrift import cli, llm
from apidrift.stages import adjudicate

FACTBLOCK = {
    "package_name": "old_pkg",
    "facts": [{"number": 1, "text": "`old_pkg` is renamed to `new_pkg`."}],
}


def _candidate(n):
    return {"file": "a.py", "line": n, "snippet": f"old_pkg.f({n})", "pattern": "1", "reason": "r"}


class RecordingLLMClient:
    def __init__(self, respond):
        self._respond = respond
        self.calls = []

    def complete(self, stage, system_text, user_text, schema, cache_system=False,
                 cache_ttl="5m", max_tokens=8000, effort="high"):
        self.calls.append({"stage": stage, "max_tokens": max_tokens})
        return self._respond(stage)


class TruncatingLLMClient:
    """Always raises llm.TruncatedResponseError, exactly like the real
    AnthropicLLMClient does when stop_reason == 'max_tokens'."""

    def __init__(self):
        self.calls = []

    def complete(self, stage, system_text, user_text, schema, cache_system=False,
                 cache_ttl="5m", max_tokens=8000, effort="high"):
        self.calls.append(stage)
        raise llm.TruncatedResponseError(
            f"[{stage}] the model's response was cut off at the {max_tokens}-token "
            f"max_tokens limit before it finished."
        )


def _rejecting(chunk_candidates):
    return {
        "proposed_sites": [],
        "flag_uncertain": [],
        "considered_and_rejected": [
            {"file": c["file"], "line": c["line"], "snippet": c["snippet"], "reason": "r"}
            for c in chunk_candidates
        ],
    }


# ---------------------------------------------------------------------
# max_tokens ceiling
# ---------------------------------------------------------------------

def test_adjudicate_requests_16000_max_tokens(tmp_path):
    candidates = [_candidate(1)]
    client = RecordingLLMClient(lambda stage: _rejecting(candidates))
    adjudicate.run(client, candidates, FACTBLOCK, str(tmp_path / "wd"), chunk_size=40)

    assert client.calls[0]["max_tokens"] == 16000


# ---------------------------------------------------------------------
# Per-chunk truncation detection
# ---------------------------------------------------------------------

def test_truncation_error_names_the_chunk_and_suggests_lowering_chunk_size(tmp_path):
    candidates = [_candidate(1)]
    client = TruncatingLLMClient()

    with pytest.raises(llm.TruncatedResponseError, match="adjudicate_chunk_000"):
        adjudicate.run(client, candidates, FACTBLOCK, str(tmp_path / "wd"), chunk_size=40)
    with pytest.raises(llm.TruncatedResponseError, match="--adjudicate-chunk-size"):
        adjudicate.run(TruncatingLLMClient(), candidates, FACTBLOCK, str(tmp_path / "wd"), chunk_size=40)


def test_truncation_does_not_write_a_chunk_file(tmp_path):
    candidates = [_candidate(1)]
    client = TruncatingLLMClient()
    with pytest.raises(llm.TruncatedResponseError):
        adjudicate.run(client, candidates, FACTBLOCK, str(tmp_path / "wd"), chunk_size=40)

    import os
    assert not os.path.isfile(os.path.join(str(tmp_path / "wd"), "adjudication", "chunk_000.json"))


def test_truncation_on_a_later_chunk_names_that_chunk(tmp_path):
    candidates = [_candidate(1), _candidate(2)]

    class MixedClient:
        def __init__(self):
            self.calls = []

        def complete(self, stage, system_text, user_text, schema, cache_system=False,
                     cache_ttl="5m", max_tokens=8000, effort="high"):
            self.calls.append(stage)
            if stage.endswith("001"):
                raise llm.TruncatedResponseError(
                    f"[{stage}] the model's response was cut off at the {max_tokens}-token "
                    f"max_tokens limit before it finished."
                )
            return _rejecting([candidates[0]])

    with pytest.raises(llm.TruncatedResponseError, match="adjudicate_chunk_001"):
        adjudicate.run(MixedClient(), candidates, FACTBLOCK, str(tmp_path / "wd"), chunk_size=1)


# ---------------------------------------------------------------------
# CLI: --adjudicate-chunk-size, and --chunk-size as a working alias
# ---------------------------------------------------------------------

def _cli_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    repo = tmp_path / "repo"
    repo.mkdir()
    guide = tmp_path / "guide.md"
    guide.write_text("`old_pkg` is renamed to `new_pkg`.")
    monkeypatch.setattr(cli, "AnthropicLLMClient", lambda model: types.SimpleNamespace(calls=[]))
    return str(repo), str(guide)


def test_cli_chunk_size_defaults_to_40(tmp_path, monkeypatch):
    repo, guide = _cli_env(tmp_path, monkeypatch)
    captured = {}
    monkeypatch.setattr(cli.pipeline, "run", lambda **kwargs: captured.update(kwargs))

    cli.main(["run", "--repo", repo, "--guide", guide])

    assert captured["chunk_size"] == 40


def test_cli_adjudicate_chunk_size_flag_reaches_pipeline_run(tmp_path, monkeypatch):
    repo, guide = _cli_env(tmp_path, monkeypatch)
    captured = {}
    monkeypatch.setattr(cli.pipeline, "run", lambda **kwargs: captured.update(kwargs))

    cli.main(["run", "--repo", repo, "--guide", guide, "--adjudicate-chunk-size", "10"])

    assert captured["chunk_size"] == 10


def test_cli_chunk_size_flag_still_works_as_an_alias(tmp_path, monkeypatch):
    repo, guide = _cli_env(tmp_path, monkeypatch)
    captured = {}
    monkeypatch.setattr(cli.pipeline, "run", lambda **kwargs: captured.update(kwargs))

    cli.main(["run", "--repo", repo, "--guide", guide, "--chunk-size", "15"])

    assert captured["chunk_size"] == 15
