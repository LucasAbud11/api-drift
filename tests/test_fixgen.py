"""Unit tests for the fix-generation stage -- all offline, a fake LLM
client stands in for the real one so these exercise chunking, the
two-bucket hard-fail contract, and duplicate expansion without any network
call or API cost."""
import json
import os

import pytest

from apidrift import validate
from apidrift.reposafe import RepoReader
from apidrift.stages import fixgen


class FakeLLMClient:
    """Returns pre-canned responses, keyed by call order (a list) so a test
    can hand fixgen.run() one response per expected chunk."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def complete(self, stage, system_text, user_text, schema, cache_system=False,
                 max_tokens=8000, effort="high"):
        self.calls.append({"stage": stage, "user_text": user_text})
        return self._responses.pop(0)


def _make_repo(tmp_path, filename="pkg/mod.py", body=None):
    if body is None:
        body = "import old_pkg\n\ndef f():\n    old_pkg.thing()\n"
    full = tmp_path / filename
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(body)
    return RepoReader(str(tmp_path))


FACTBLOCK = {
    "package_name": "old_pkg",
    "facts": [{"number": 1, "text": "`old_pkg` is renamed to `new_pkg`."}],
}


def test_run_produces_validated_merged_fixes(tmp_path):
    reader = _make_repo(tmp_path)
    sites = [{"file": "pkg/mod.py", "line": 1, "snippet": "import old_pkg", "pattern": "1",
              "reason": "import of the renamed package"}]
    response = {
        "fixes": [{
            "file": "pkg/mod.py", "line": 1,
            "original_line": "import old_pkg", "proposed_line": "import new_pkg",
            "reason": "fact 1: package renamed",
        }],
        "flagged_for_human": [],
    }
    client = FakeLLMClient([response])
    workdir = str(tmp_path / "workdir")

    merged = fixgen.run(client, reader, sites, FACTBLOCK, workdir, chunk_size=40)

    validate.validate_fixgen_dict(merged)  # does not raise
    assert merged["fixes"][0]["proposed_line"] == "import new_pkg"
    assert os.path.isfile(os.path.join(workdir, "fixgen", "merged.json"))
    assert os.path.isfile(os.path.join(workdir, "fixgen", "chunk_000.json"))


def test_run_raises_on_incomplete_chunk_coverage(tmp_path):
    reader = _make_repo(tmp_path)
    sites = [
        {"file": "pkg/mod.py", "line": 1, "snippet": "import old_pkg", "pattern": "1", "reason": "r1"},
        {"file": "pkg/mod.py", "line": 4, "snippet": "    old_pkg.thing()", "pattern": "1", "reason": "r2"},
    ]
    # Only covers one of the two sites given -- must be rejected, not
    # silently accepted with the other site missing.
    response = {
        "fixes": [{
            "file": "pkg/mod.py", "line": 1,
            "original_line": "import old_pkg", "proposed_line": "import new_pkg",
            "reason": "fact 1",
        }],
        "flagged_for_human": [],
    }
    client = FakeLLMClient([response])
    workdir = str(tmp_path / "workdir")

    with pytest.raises(ValueError, match="does not cover exactly the sites"):
        fixgen.run(client, reader, sites, FACTBLOCK, workdir, chunk_size=40)


def test_run_resumes_from_a_valid_existing_chunk(tmp_path):
    reader = _make_repo(tmp_path)
    sites = [{"file": "pkg/mod.py", "line": 1, "snippet": "import old_pkg", "pattern": "1", "reason": "r"}]
    workdir = str(tmp_path / "workdir")
    fg_dir = os.path.join(workdir, "fixgen")
    os.makedirs(fg_dir, exist_ok=True)
    precomputed = {
        "fixes": [{"file": "pkg/mod.py", "line": 1, "original_line": "import old_pkg",
                    "proposed_line": "import new_pkg", "reason": "already done"}],
        "flagged_for_human": [],
    }
    with open(os.path.join(fg_dir, "chunk_000.json"), "w") as f:
        json.dump(precomputed, f)

    # No responses queued -- if fixgen.run() tried to call the model again
    # for an already-done chunk, this would raise IndexError (pop from
    # empty list), failing the test loudly.
    client = FakeLLMClient([])
    merged = fixgen.run(client, reader, sites, FACTBLOCK, workdir, chunk_size=40)

    assert client.calls == []
    assert merged["fixes"][0]["reason"] == "already done"


def test_expand_duplicates_fans_out_fixes_and_flags():
    merged = {
        "fixes": [{"file": "a.py", "line": 5, "original_line": "x = old_pkg.f()",
                    "proposed_line": "x = new_pkg.f()", "reason": "renamed"}],
        "flagged_for_human": [{"file": "a.py", "line": 20, "reason": "structural"}],
    }
    expansion_map = {
        ("a.py", 5): [
            {"line": 5, "snippet": "x = old_pkg.f()"},
            {"line": 9, "snippet": "x = old_pkg.f()"},
        ],
        ("a.py", 20): [
            {"line": 20, "snippet": "y = old_pkg.g()"},
            {"line": 30, "snippet": "y = old_pkg.g()"},
        ],
    }
    expanded = fixgen.expand_duplicates(merged, expansion_map)

    fix_lines = sorted(item["line"] for item in expanded["fixes"])
    assert fix_lines == [5, 9]
    for item in expanded["fixes"]:
        assert item["proposed_line"] == "x = new_pkg.f()"  # same replacement text
    flagged_lines = sorted(item["line"] for item in expanded["flagged_for_human"])
    assert flagged_lines == [20, 30]


def test_expand_duplicates_passes_through_non_collapsed_sites():
    merged = {
        "fixes": [{"file": "a.py", "line": 5, "original_line": "x", "proposed_line": "y", "reason": "r"}],
        "flagged_for_human": [],
    }
    expanded = fixgen.expand_duplicates(merged, expansion_map={})
    assert expanded["fixes"] == merged["fixes"]
