"""Offline tests for prompt-cache wiring: the len(chunks) > 1 gate in
adjudicate.py/fixgen.py (a single chunk can never redeem its own cache
write within a run, so caching it by default is pure premium for no
benefit) and the --cache-ttl plumbing that lets a caller opt a
single-chunk run back into caching anyway, signaling cross-run reuse is
intended. No network, no LLM calls -- fake clients capture what each
stage actually asked for.
"""
import types

import pytest

from apidrift import cli
from apidrift.llm import AnthropicLLMClient
from apidrift.reposafe import RepoReader
from apidrift.stages import adjudicate, fixgen

SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}

FACTBLOCK = {
    "package_name": "old_pkg",
    "facts": [{"number": 1, "text": "`old_pkg` is renamed to `new_pkg`."}],
}


class RecordingFakeClient:
    """Records the cache_system/cache_ttl each call actually received;
    answers deterministically from `respond`."""

    def __init__(self, respond):
        self._respond = respond
        self.calls = []

    def complete(self, stage, system_text, user_text, schema, cache_system=False,
                 cache_ttl="5m", max_tokens=8000, effort="high"):
        self.calls.append({"stage": stage, "cache_system": cache_system, "cache_ttl": cache_ttl})
        return self._respond(stage)


def _candidate(n):
    return {"file": "a.py", "line": n, "snippet": f"old_pkg.f({n})", "pattern": "1", "reason": "r"}


def _adjudicate_response_rejecting(chunk_candidates):
    return {
        "proposed_sites": [],
        "flag_uncertain": [],
        "considered_and_rejected": [
            {"file": c["file"], "line": c["line"], "snippet": c["snippet"], "reason": "r"}
            for c in chunk_candidates
        ],
    }


def _make_repo(tmp_path):
    full = tmp_path / "pkg" / "mod.py"
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text("\n".join(f"old_pkg.f({i})" for i in range(1, 4)) + "\n")
    return RepoReader(str(tmp_path))


# ---------------------------------------------------------------------
# adjudicate.py: the len(chunks) > 1 / cache_ttl gate
# ---------------------------------------------------------------------

def test_adjudicate_single_chunk_does_not_cache_by_default(tmp_path):
    candidates = [_candidate(1)]

    def respond(stage):
        return _adjudicate_response_rejecting(candidates)

    client = RecordingFakeClient(respond)
    adjudicate.run(client, candidates, FACTBLOCK, str(tmp_path / "wd"), chunk_size=40)

    assert len(client.calls) == 1
    assert client.calls[0]["cache_system"] is False
    assert client.calls[0]["cache_ttl"] == "5m"


def test_adjudicate_single_chunk_caches_when_ttl_explicitly_raised(tmp_path):
    candidates = [_candidate(1)]

    def respond(stage):
        return _adjudicate_response_rejecting(candidates)

    client = RecordingFakeClient(respond)
    adjudicate.run(client, candidates, FACTBLOCK, str(tmp_path / "wd"),
                    chunk_size=40, cache_ttl="1h")

    assert len(client.calls) == 1
    assert client.calls[0]["cache_system"] is True
    assert client.calls[0]["cache_ttl"] == "1h"


def test_adjudicate_multi_chunk_caches_even_at_default_ttl(tmp_path):
    candidates = [_candidate(1), _candidate(2)]

    def respond(stage):
        idx = int(stage.rsplit("_", 1)[1])
        return _adjudicate_response_rejecting([candidates[idx]])

    client = RecordingFakeClient(respond)
    adjudicate.run(client, candidates, FACTBLOCK, str(tmp_path / "wd"), chunk_size=1)

    assert len(client.calls) == 2
    assert all(c["cache_system"] is True for c in client.calls)
    assert all(c["cache_ttl"] == "5m" for c in client.calls)


# ---------------------------------------------------------------------
# fixgen.py: same gate
# ---------------------------------------------------------------------

def _fixgen_response_flagging(chunk_sites):
    return {
        "fixes": [],
        "flagged_for_human": [
            {"file": s["file"], "line": s["line"], "reason": "r"} for s in chunk_sites
        ],
    }


def test_fixgen_single_chunk_does_not_cache_by_default(tmp_path):
    reader = _make_repo(tmp_path)
    sites = [{"file": "pkg/mod.py", "line": 1, "snippet": "old_pkg.f(1)", "pattern": "1", "reason": "r"}]

    def respond(stage):
        return _fixgen_response_flagging(sites)

    client = RecordingFakeClient(respond)
    fixgen.run(client, reader, sites, FACTBLOCK, str(tmp_path / "wd"), chunk_size=40)

    assert len(client.calls) == 1
    assert client.calls[0]["cache_system"] is False
    assert client.calls[0]["cache_ttl"] == "5m"


def test_fixgen_single_chunk_caches_when_ttl_explicitly_raised(tmp_path):
    reader = _make_repo(tmp_path)
    sites = [{"file": "pkg/mod.py", "line": 1, "snippet": "old_pkg.f(1)", "pattern": "1", "reason": "r"}]

    def respond(stage):
        return _fixgen_response_flagging(sites)

    client = RecordingFakeClient(respond)
    fixgen.run(client, reader, sites, FACTBLOCK, str(tmp_path / "wd"),
               chunk_size=40, cache_ttl="1h")

    assert len(client.calls) == 1
    assert client.calls[0]["cache_system"] is True
    assert client.calls[0]["cache_ttl"] == "1h"


def test_fixgen_multi_chunk_caches_even_at_default_ttl(tmp_path):
    reader = _make_repo(tmp_path)
    sites = [
        {"file": "pkg/mod.py", "line": 1, "snippet": "old_pkg.f(1)", "pattern": "1", "reason": "r"},
        {"file": "pkg/mod.py", "line": 2, "snippet": "old_pkg.f(2)", "pattern": "1", "reason": "r"},
    ]

    def respond(stage):
        idx = int(stage.rsplit("_", 1)[1])
        return _fixgen_response_flagging([sites[idx]])

    client = RecordingFakeClient(respond)
    fixgen.run(client, reader, sites, FACTBLOCK, str(tmp_path / "wd"), chunk_size=1)

    assert len(client.calls) == 2
    assert all(c["cache_system"] is True for c in client.calls)
    assert all(c["cache_ttl"] == "5m" for c in client.calls)


# ---------------------------------------------------------------------
# llm.py: cache_ttl actually lands in the cache_control dict sent to the
# SDK, and an invalid ttl fails loudly before any network call.
# ---------------------------------------------------------------------

class _FakeStreamContext:
    def __init__(self, response):
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get_final_message(self):
        return self._response


class _FakeMessages:
    """Captures the kwargs passed to messages.stream() so a test can
    inspect the exact `system` value (and therefore cache_control) sent,
    without touching the network."""

    def __init__(self, response):
        self._response = response
        self.last_kwargs = None

    def stream(self, **kwargs):
        self.last_kwargs = kwargs
        return _FakeStreamContext(self._response)


class _FakeAnthropicClient:
    def __init__(self, response):
        self.messages = _FakeMessages(response)


def _fake_response(text='{"ok": true}'):
    usage = types.SimpleNamespace(input_tokens=10, output_tokens=5,
                                   cache_creation_input_tokens=0, cache_read_input_tokens=0)
    content = [types.SimpleNamespace(type="text", text=text)]
    return types.SimpleNamespace(stop_reason="end_turn", usage=usage, content=content)


@pytest.mark.parametrize("ttl", ["5m", "1h"])
def test_cache_control_dict_carries_the_requested_ttl(ttl):
    fake_anthropic = _FakeAnthropicClient(_fake_response())
    client = AnthropicLLMClient(anthropic_client=fake_anthropic)

    client.complete("some_stage", "sys", "user", SCHEMA, cache_system=True, cache_ttl=ttl)

    system_sent = fake_anthropic.messages.last_kwargs["system"]
    assert system_sent == [{"type": "text", "text": "sys",
                             "cache_control": {"type": "ephemeral", "ttl": ttl}}]


def test_cache_system_false_sends_plain_string_system_regardless_of_ttl():
    fake_anthropic = _FakeAnthropicClient(_fake_response())
    client = AnthropicLLMClient(anthropic_client=fake_anthropic)

    client.complete("some_stage", "sys", "user", SCHEMA, cache_system=False, cache_ttl="1h")

    assert fake_anthropic.messages.last_kwargs["system"] == "sys"


def test_invalid_cache_ttl_raises_before_any_network_call():
    fake_anthropic = _FakeAnthropicClient(_fake_response())
    client = AnthropicLLMClient(anthropic_client=fake_anthropic)

    with pytest.raises(ValueError, match="cache_ttl"):
        client.complete("some_stage", "sys", "user", SCHEMA, cache_system=True, cache_ttl="1d")

    assert fake_anthropic.messages.last_kwargs is None  # never reached the SDK call


# ---------------------------------------------------------------------
# cli.py: --cache-ttl argument shape, and that it actually reaches
# pipeline.run() -- no network: AnthropicLLMClient construction and
# pipeline.run() are both stubbed out.
# ---------------------------------------------------------------------

def _cli_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    repo = tmp_path / "repo"
    repo.mkdir()
    guide = tmp_path / "guide.md"
    guide.write_text("`old_pkg` is renamed to `new_pkg`.")
    monkeypatch.setattr(cli, "AnthropicLLMClient",
                         lambda model: types.SimpleNamespace(calls=[]))
    return str(repo), str(guide)


def test_cli_cache_ttl_defaults_to_5m_and_reaches_pipeline_run(tmp_path, monkeypatch):
    repo, guide = _cli_env(tmp_path, monkeypatch)
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(cli.pipeline, "run", fake_run)

    cli.main(["run", "--repo", repo, "--guide", guide])

    assert captured["cache_ttl"] == "5m"


def test_cli_cache_ttl_1h_reaches_pipeline_run(tmp_path, monkeypatch):
    repo, guide = _cli_env(tmp_path, monkeypatch)
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(cli.pipeline, "run", fake_run)

    cli.main(["run", "--repo", repo, "--guide", guide, "--cache-ttl", "1h"])

    assert captured["cache_ttl"] == "1h"


def test_cli_rejects_invalid_cache_ttl_choice(capsys):
    with pytest.raises(SystemExit):
        cli.main(["run", "--repo", "r", "--guide", "g", "--cache-ttl", "30m"])
    err = capsys.readouterr().err
    assert "--cache-ttl" in err
    assert "invalid choice" in err.lower()
