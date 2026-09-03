"""Offline tests for fixgen's max_tokens=16000 ceiling (raised from 8000
after a real Pydantic v1->v2 run truncated fixgen_chunk_008 at 229
proposed sites -- the preceding attempt's malformed-looking result, a fix
arriving with an empty proposed_lines, was almost certainly the same
truncation cutting the response mid-object) and its per-chunk
truncation-error message naming the chunk and pointing at
--fixgen-chunk-size, same shape adjudicate.py's own truncation test uses.
No network, no LLM calls.
"""
import os

import pytest

from apidrift import llm
from apidrift.reposafe import RepoReader
from apidrift.stages import fixgen

FACTBLOCK = {
    "package_name": "old_pkg",
    "facts": [{"number": 1, "text": "`old_pkg` is renamed to `new_pkg`."}],
}


def _make_repo(tmp_path):
    body = "import old_pkg\n\ndef f():\n    old_pkg.thing()\n"
    full = tmp_path / "pkg" / "mod.py"
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(body)
    return RepoReader(str(tmp_path))


def _site(line):
    return {"file": "pkg/mod.py", "line": line, "snippet": f"old_pkg.thing({line})",
            "pattern": "1", "reason": "plain confirmed rename site"}


def _declined(sites):
    return {
        "fixes": [],
        "flagged_for_human": [{"file": s["file"], "line": s["line"], "reason": "r"} for s in sites],
    }


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


# ---------------------------------------------------------------------
# max_tokens ceiling
# ---------------------------------------------------------------------

def test_fixgen_requests_16000_max_tokens(tmp_path):
    reader = _make_repo(tmp_path)
    sites = [_site(4)]
    client = RecordingLLMClient(lambda stage: _declined(sites))

    fixgen.run(client, reader, sites, FACTBLOCK, str(tmp_path / "wd"), chunk_size=40)

    assert client.calls[0]["max_tokens"] == 16000


# ---------------------------------------------------------------------
# Per-chunk truncation detection
# ---------------------------------------------------------------------

def test_truncation_error_names_the_chunk_and_suggests_lowering_chunk_size(tmp_path):
    reader = _make_repo(tmp_path)
    sites = [_site(4)]

    with pytest.raises(llm.TruncatedResponseError, match="fixgen_chunk_000"):
        fixgen.run(TruncatingLLMClient(), reader, sites, FACTBLOCK, str(tmp_path / "wd"), chunk_size=40)
    with pytest.raises(llm.TruncatedResponseError, match="--fixgen-chunk-size"):
        fixgen.run(TruncatingLLMClient(), reader, sites, FACTBLOCK, str(tmp_path / "wd2"), chunk_size=40)


def test_truncation_does_not_write_a_chunk_file(tmp_path):
    reader = _make_repo(tmp_path)
    sites = [_site(4)]
    workdir = str(tmp_path / "wd")

    with pytest.raises(llm.TruncatedResponseError):
        fixgen.run(TruncatingLLMClient(), reader, sites, FACTBLOCK, workdir, chunk_size=40)

    assert not os.path.isfile(os.path.join(workdir, "fixgen", "chunk_000.json"))


def test_truncation_on_a_later_chunk_names_that_chunk(tmp_path):
    reader = _make_repo(tmp_path)
    sites = [_site(4), _site(400)]

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
            return _declined([sites[0]])

    with pytest.raises(llm.TruncatedResponseError, match="fixgen_chunk_001"):
        fixgen.run(MixedClient(), reader, sites, FACTBLOCK, str(tmp_path / "wd"), chunk_size=1)
