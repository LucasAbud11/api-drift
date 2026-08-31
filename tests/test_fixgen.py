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
                 cache_ttl="5m", max_tokens=8000, effort="high"):
        self.calls.append({"stage": stage, "user_text": user_text,
                            "cache_system": cache_system, "cache_ttl": cache_ttl})
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
            "file": "pkg/mod.py", "line": 1, "end_line": 1,
            "original_lines": ["import old_pkg"], "proposed_lines": ["import new_pkg"],
            "reason": "fact 1: package renamed",
        }],
        "flagged_for_human": [],
    }
    client = FakeLLMClient([response])
    workdir = str(tmp_path / "workdir")

    merged = fixgen.run(client, reader, sites, FACTBLOCK, workdir, chunk_size=40)

    validate.validate_fixgen_dict(merged)  # does not raise
    assert merged["fixes"][0]["proposed_lines"] == ["import new_pkg"]
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
            "file": "pkg/mod.py", "line": 1, "end_line": 1,
            "original_lines": ["import old_pkg"], "proposed_lines": ["import new_pkg"],
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
        "fixes": [{"file": "pkg/mod.py", "line": 1, "end_line": 1,
                    "original_lines": ["import old_pkg"], "proposed_lines": ["import new_pkg"],
                    "reason": "already done"}],
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
        "fixes": [{"file": "a.py", "line": 5, "end_line": 5,
                    "original_lines": ["x = old_pkg.f()"], "proposed_lines": ["x = new_pkg.f()"],
                    "reason": "renamed"}],
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
        assert item["end_line"] == item["line"]
        assert item["proposed_lines"] == ["x = new_pkg.f()"]  # same replacement text
    flagged_lines = sorted(item["line"] for item in expanded["flagged_for_human"])
    assert flagged_lines == [20, 30]


def test_expand_duplicates_passes_through_non_collapsed_sites():
    merged = {
        "fixes": [{"file": "a.py", "line": 5, "end_line": 5,
                    "original_lines": ["x"], "proposed_lines": ["y"], "reason": "r"}],
        "flagged_for_human": [],
    }
    expanded = fixgen.expand_duplicates(merged, expansion_map={})
    assert expanded["fixes"] == merged["fixes"]


# ---------------------------------------------------------------------
# Multi-line-span guard -- reproduces the tonyzorin/youtrack-mcp gap:
# `mcp = FastMCP(\n    ...,\n    host=host,\n    port=port,\n)` at main.py:27
# had its opening line renamed correctly while the model never looked at
# the rest of the call, which still passed `host=`/`port=` that v2 moved
# off the constructor -- the fix set imported cleanly and then blew up at
# runtime. Tier 1/2 verification both passed because they check each fix's
# self-consistency, never whether the fix set is sufficient. These fixtures
# reproduce that exact shape: a multi-line assignment-call spanning lines
# 5-9, plus a single-line call for contrast.
# ---------------------------------------------------------------------

MULTILINE_CALL_BODY = (
    "from old_pkg import OldMCP\n"      # line 1
    "\n"                                # line 2
    "\n"                                # line 3
    "def create_server(host=\"0.0.0.0\", port=8000):\n"  # line 4
    "    mcp = OldMCP(\n"               # line 5 -- opening line, candidate A
    "        \"name\",\n"               # line 6
    "        host=host,\n"              # line 7 -- non-opening line, candidate C
    "        port=port,\n"              # line 8
    "    )\n"                           # line 9
    "    return mcp\n"                  # line 10
)


def test_multiline_span_opening_line_flags_without_calling_model(tmp_path):
    reader = _make_repo(tmp_path, body=MULTILINE_CALL_BODY)
    sites = [{"file": "pkg/mod.py", "line": 5, "snippet": "    mcp = OldMCP(",
              "pattern": "1", "reason": "constructor of the renamed class"}]
    client = FakeLLMClient([])  # any complete() call would IndexError -- proves the model is never asked
    workdir = str(tmp_path / "workdir")

    merged = fixgen.run(client, reader, sites, FACTBLOCK, workdir, chunk_size=40)

    validate.validate_fixgen_dict(merged)
    assert merged["fixes"] == []
    assert len(merged["flagged_for_human"]) == 1
    flag = merged["flagged_for_human"][0]
    assert flag["file"] == "pkg/mod.py"
    assert flag["line"] == 5
    assert flag["flag_source"] == "multiline_span_guard"
    assert flag["span"] == [5, 9]
    assert client.calls == []


def test_multiline_span_non_opening_line_also_flags(tmp_path):
    reader = _make_repo(tmp_path, body=MULTILINE_CALL_BODY)
    sites = [{"file": "pkg/mod.py", "line": 7, "snippet": "        host=host,",
              "pattern": "1", "reason": "keyword argument moved off the constructor"}]
    client = FakeLLMClient([])
    workdir = str(tmp_path / "workdir")

    merged = fixgen.run(client, reader, sites, FACTBLOCK, workdir, chunk_size=40)

    assert merged["fixes"] == []
    assert len(merged["flagged_for_human"]) == 1
    flag = merged["flagged_for_human"][0]
    assert flag["line"] == 7
    assert flag["flag_source"] == "multiline_span_guard"
    assert flag["span"] == [5, 9]
    assert client.calls == []


def test_multiline_span_flag_reason_includes_full_span_range(tmp_path):
    reader = _make_repo(tmp_path, body=MULTILINE_CALL_BODY)
    sites = [{"file": "pkg/mod.py", "line": 5, "snippet": "    mcp = OldMCP(",
              "pattern": "1", "reason": "constructor of the renamed class"}]
    client = FakeLLMClient([])
    workdir = str(tmp_path / "workdir")

    merged = fixgen.run(client, reader, sites, FACTBLOCK, workdir, chunk_size=40)

    reason = merged["flagged_for_human"][0]["reason"]
    assert "5-9" in reason
    assert "not evaluated" in reason


def test_same_rename_on_single_line_call_still_fixes(tmp_path):
    # Same class-rename fact, same identifier, but the call fits on one
    # physical line -- must go through the model and come back as a FIX,
    # not get swept into the guard.
    body = (
        "from old_pkg import OldMCP\n"          # line 1
        "\n"                                    # line 2
        "def create_server():\n"                # line 3
        "    mcp = OldMCP(\"name\")\n"          # line 4 -- single-line call
        "    return mcp\n"                      # line 5
    )
    reader = _make_repo(tmp_path, body=body)
    sites = [{"file": "pkg/mod.py", "line": 4, "snippet": "    mcp = OldMCP(\"name\")",
              "pattern": "1", "reason": "constructor of the renamed class"}]
    response = {
        "fixes": [{
            "file": "pkg/mod.py", "line": 4, "end_line": 4,
            "original_lines": ["    mcp = OldMCP(\"name\")"],
            "proposed_lines": ["    mcp = NewMCP(\"name\")"],
            "reason": "fact 1: class renamed",
        }],
        "flagged_for_human": [],
    }
    client = FakeLLMClient([response])
    workdir = str(tmp_path / "workdir")

    merged = fixgen.run(client, reader, sites, FACTBLOCK, workdir, chunk_size=40)

    assert merged["flagged_for_human"] == []
    assert len(merged["fixes"]) == 1
    assert merged["fixes"][0]["proposed_lines"] == ["    mcp = NewMCP(\"name\")"]
    assert len(client.calls) == 1  # the model WAS asked, unlike the multi-line cases above


def test_multiline_and_singleline_sites_mixed_in_one_run(tmp_path):
    # One site inside the multi-line call (must FLAG, no model call for it)
    # and one ordinary single-line site (must FIX via the model) in the
    # same run -- proves the guard filters per-site, not per-run.
    reader = _make_repo(tmp_path, body=MULTILINE_CALL_BODY)
    sites = [
        {"file": "pkg/mod.py", "line": 5, "snippet": "    mcp = OldMCP(",
         "pattern": "1", "reason": "constructor of the renamed class"},
        {"file": "pkg/mod.py", "line": 1, "snippet": "from old_pkg import OldMCP",
         "pattern": "1", "reason": "import of the renamed package"},
    ]
    response = {
        "fixes": [{
            "file": "pkg/mod.py", "line": 1, "end_line": 1,
            "original_lines": ["from old_pkg import OldMCP"],
            "proposed_lines": ["from new_pkg import NewMCP"],
            "reason": "fact 1",
        }],
        "flagged_for_human": [],
    }
    client = FakeLLMClient([response])
    workdir = str(tmp_path / "workdir")

    merged = fixgen.run(client, reader, sites, FACTBLOCK, workdir, chunk_size=40)

    assert len(merged["fixes"]) == 1
    assert merged["fixes"][0]["line"] == 1
    assert len(merged["flagged_for_human"]) == 1
    assert merged["flagged_for_human"][0]["line"] == 5
    assert merged["flagged_for_human"][0]["flag_source"] == "multiline_span_guard"
    # only the single-line site was ever sent to the model
    assert len(client.calls) == 1
    assert "pkg/mod.py:5" not in client.calls[0]["user_text"]
    assert "pkg/mod.py:1" in client.calls[0]["user_text"]


# ---------------------------------------------------------------------
# validate.py -- block-fix schema (end_line/original_lines/proposed_lines)
# ---------------------------------------------------------------------

def _valid_fix(**overrides):
    fix = {"file": "a.py", "line": 1, "end_line": 1,
           "original_lines": ["x = 1"], "proposed_lines": ["x = 2"], "reason": "r"}
    fix.update(overrides)
    return fix


def test_validate_fixgen_accepts_ordinary_single_line_shape():
    data = {"fixes": [_valid_fix()], "flagged_for_human": []}
    validate.validate_fixgen_dict(data)  # does not raise


def test_validate_fixgen_accepts_block_fix_with_a_different_line_count():
    # proposed_lines may have a different length than original_lines -- a
    # fix may add or remove lines, unlike the old one-line-in-one-line-out
    # shape.
    data = {"fixes": [_valid_fix(
        end_line=3, original_lines=["a", "b", "c"], proposed_lines=["x"],
    )], "flagged_for_human": []}
    validate.validate_fixgen_dict(data)  # does not raise


def test_validate_fixgen_rejects_end_line_before_line():
    data = {"fixes": [_valid_fix(end_line=0)], "flagged_for_human": []}
    with pytest.raises(ValueError, match="end_line"):
        validate.validate_fixgen_dict(data)


def test_validate_fixgen_rejects_original_lines_count_mismatch_with_span():
    data = {"fixes": [_valid_fix(end_line=3, original_lines=["a", "b"])], "flagged_for_human": []}
    with pytest.raises(ValueError, match="original_lines"):
        validate.validate_fixgen_dict(data)


def test_validate_fixgen_rejects_empty_proposed_lines():
    data = {"fixes": [_valid_fix(proposed_lines=[])], "flagged_for_human": []}
    with pytest.raises(ValueError, match="proposed_lines"):
        validate.validate_fixgen_dict(data)


def test_validate_fixgen_rejects_blank_line_in_block():
    data = {"fixes": [_valid_fix(original_lines=[""])], "flagged_for_human": []}
    with pytest.raises(ValueError, match=r"original_lines\[0\]"):
        validate.validate_fixgen_dict(data)


def test_validate_fixgen_accepts_omitted_group_id():
    data = {"fixes": [_valid_fix()], "flagged_for_human": []}
    validate.validate_fixgen_dict(data)  # does not raise -- group_id is optional


def test_validate_fixgen_accepts_null_group_id():
    data = {"fixes": [_valid_fix(group_id=None)], "flagged_for_human": []}
    validate.validate_fixgen_dict(data)  # does not raise


def test_validate_fixgen_accepts_string_group_id():
    data = {"fixes": [_valid_fix(group_id="a.py:1")], "flagged_for_human": []}
    validate.validate_fixgen_dict(data)  # does not raise


def test_validate_fixgen_rejects_blank_group_id():
    data = {"fixes": [_valid_fix(group_id="")], "flagged_for_human": []}
    with pytest.raises(ValueError, match="group_id"):
        validate.validate_fixgen_dict(data)


# ---------------------------------------------------------------------
# _check_group_value_flow -- deterministic, model-free safety net for a
# jointly-resolved group's fixes. See fixgen.py's own docstring for why
# this exists: a coordinated edit can parse fine, pass ordinary line-match
# verification, and still silently drop a value.
# ---------------------------------------------------------------------

def _group_fix(file, line, end_line, original_lines, proposed_lines):
    return {"file": file, "line": line, "end_line": end_line,
            "original_lines": original_lines, "proposed_lines": proposed_lines,
            "reason": "r", "group_id": "g"}


def test_value_flow_guard_passes_when_value_correctly_threaded():
    group = [
        _group_fix("main.py", 3, 7,
                   ["mcp = FastMCP(", "    \"name\",", "    host=host,", "    port=port", ")"],
                   ["mcp = FastMCP(", "    \"name\",", ")"]),
        _group_fix("main.py", 16, 16,
                   ["    mcp.run(transport=\"sse\")"],
                   ["    mcp.run(transport=\"sse\", host=host, port=port)"]),
    ]
    assert fixgen._check_group_value_flow(group) is None


def test_value_flow_guard_fails_when_value_silently_dropped():
    group = [
        _group_fix("main.py", 3, 7,
                   ["mcp = FastMCP(", "    \"name\",", "    host=host,", "    port=port", ")"],
                   ["mcp = FastMCP(", "    \"name\",", ")"]),
        _group_fix("main.py", 16, 16,
                   ["    mcp.run(transport=\"sse\")"],
                   ["    mcp.run(transport=\"sse\")"]),  # host/port never threaded through
    ]
    failure = fixgen._check_group_value_flow(group)
    assert failure is not None
    assert "host" in failure and "port" in failure


def test_value_flow_guard_fails_when_value_replaced_by_a_different_literal():
    # The exact case named in the design pass: port=port quietly becoming
    # port=8000 at the destination instead of the real threaded variable --
    # same keyword NAME present, different value expression.
    group = [
        _group_fix("main.py", 3, 7,
                   ["mcp = FastMCP(", "    \"name\",", "    port=port", ")"],
                   ["mcp = FastMCP(", "    \"name\",", ")"]),
        _group_fix("main.py", 16, 16,
                   ["    mcp.run(transport=\"sse\")"],
                   ["    mcp.run(transport=\"sse\", port=8000)"]),
    ]
    failure = fixgen._check_group_value_flow(group)
    assert failure is not None
    assert "port" in failure


def test_value_flow_guard_ignores_a_keyword_unchanged_at_the_same_site():
    group = [_group_fix("a.py", 1, 1, ["f(x=x, y=y)"], ["f(x=x, y=y)"])]
    assert fixgen._check_group_value_flow(group) is None


def test_value_flow_guard_fails_when_value_invented_with_no_removal_source():
    # The addition-side blind spot: a keyword appears in a proposed block
    # with no corresponding value removed anywhere else in the group -- a
    # joint call inventing host="0.0.0.0" on run() when the constructor
    # never carried it. Must fail even though nothing was silently dropped.
    group = [
        _group_fix("main.py", 3, 3,
                   ["mcp = FastMCP(\"name\")"],
                   ["mcp = FastMCP(\"name\")"]),  # untouched -- no keywords at all
        _group_fix("main.py", 16, 16,
                   ["    mcp.run(transport=\"sse\")"],
                   ["    mcp.run(transport=\"sse\", host=\"0.0.0.0\")"]),
    ]
    failure = fixgen._check_group_value_flow(group)
    assert failure is not None
    assert "host" in failure


def test_value_flow_guard_passes_when_addition_is_sourced_from_a_real_removal():
    # Mirror of the correctly-threaded test, phrased as the addition side:
    # a keyword that appears newly at one site is fine as long as an
    # AST-equal value was actually removed from another member.
    group = [
        _group_fix("main.py", 3, 7,
                   ["mcp = FastMCP(", "    \"name\",", "    host=host,", ")"],
                   ["mcp = FastMCP(", "    \"name\",", ")"]),
        _group_fix("main.py", 16, 16,
                   ["    mcp.run(transport=\"sse\")"],
                   ["    mcp.run(transport=\"sse\", host=host)"]),
    ]
    assert fixgen._check_group_value_flow(group) is None


def test_value_flow_guard_degrades_gracefully_on_unparseable_original():
    # Original side fails to parse; proposed side parses fine and has
    # keywords. Those keywords must NOT be treated as "added from nowhere"
    # -- the unparseable original might have had them, we just can't tell.
    group = [_group_fix("a.py", 1, 1, ["f(x=x"], ["f(x=x, y=y)"])]
    assert fixgen._check_group_value_flow(group) is None


def test_value_flow_guard_degrades_gracefully_on_unparseable_proposed():
    # Symmetric case: proposed side fails to parse; original side parses
    # fine and has keywords. Those keywords must NOT be treated as
    # "removed with no reappearance" -- the unparseable proposed might
    # still carry them, we just can't tell.
    group = [_group_fix("a.py", 1, 1, ["f(x=x, y=y)"], ["f(x=x"])]
    assert fixgen._check_group_value_flow(group) is None


def test_extract_call_keywords_finds_every_keyword_in_a_call():
    kws = fixgen._extract_call_keywords("f(a=1, b=x)")
    assert set(kws) == {"a", "b"}


def test_extract_call_keywords_returns_empty_dict_for_unparseable_text():
    assert fixgen._extract_call_keywords("f(a=") == {}
