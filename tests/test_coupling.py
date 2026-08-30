"""Offline tests for the coupling-group increment: adjudicate.py's
related_sites field, fixgen.py's deterministic group-consistency guard,
and report.py's coupled-group rendering. No network, no LLM calls.

Fixtures below reproduce the two real shapes the design pass measured on
run-azeroth and run-youtrack-v2 (see REPORT.md): a proposed constructor
site coupled to two flag_uncertain sites via related_sites, where the
proposed site is itself multi-line and so already caught by the existing
span guard; and, separately, a hypothetical single-line-anchor case (not
present in any run's evidence, per the design pass's own scoping) used to
exercise the deterministic-decline path the span guard alone can't reach.
"""
import json
import os

import pytest

from apidrift import validate
from apidrift.reposafe import RepoReader
from apidrift.stages import fixgen, report
from apidrift.stages.fixgen import _group_by_related_sites


class FakeLLMClient:
    """Same shape as test_fixgen.py's -- any call the guard should have
    prevented raises IndexError (pop from an empty list), failing loudly."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def complete(self, stage, system_text, user_text, schema, cache_system=False,
                 cache_ttl="5m", max_tokens=8000, effort="high"):
        self.calls.append({"stage": stage, "user_text": user_text})
        return self._responses.pop(0)


def _make_repo(tmp_path, filename="main.py", body="x = 1\n"):
    full = tmp_path / filename
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(body)
    return RepoReader(str(tmp_path))


FACTBLOCK = {"package_name": "mcp", "facts": [{"number": 1, "text": "test fact"}]}

# Mirrors run-azeroth's real main.py:68-72/153/170 shape: a multi-line
# constructor (lines 3-7) whose host/port kwargs move to a later run()
# call, plus an unrelated import-shaped rename with no dependency on
# anything (main.py:29's real-world counterpart).
AZEROTH_SHAPED_BODY = (
    "import os\n"                        # line 1
    "\n"                                 # line 2
    "mcp = FastMCP(\n"                   # line 3 -- multi-line anchor
    "    \"name\",\n"                    # line 4
    "    host=MCP_HOST,\n"               # line 5
    "    port=MCP_PORT\n"                # line 6
    ")\n"                                # line 7
    "\n"                                 # line 8
    "def other():\n"                     # line 9
    "    pass\n"                         # line 10
    "\n"                                 # line 11
    "async def _run_with_auth():\n"      # line 12
    "    starlette_app = mcp.sse_app()\n"  # line 13
    "\n"                                 # line 14
    "if __name__ == \"__main__\":\n"     # line 15
    "    mcp.run(transport=\"sse\")\n"   # line 16
)


# ---------------------------------------------------------------------
# _group_by_related_sites -- the union-find grouping itself
# ---------------------------------------------------------------------

def test_grouping_links_sites_via_related_sites_not_fact_citation():
    # Fact-citation was measured to over-group (an import sharing fact
    # numbers with a constructor it doesn't depend on) and under-group
    # (the actually-coupled constructor/run() pair sharing zero fact
    # numbers) on real run-azeroth data -- see REPORT.md. Grouping must
    # come only from related_sites.
    proposed = [
        {"file": "main.py", "line": 68, "pattern": "98, 134", "reason": "constructor",
         "related_sites": [{"file": "main.py", "line": 170}]},
        {"file": "main.py", "line": 29, "pattern": "2, 98, 99, 134", "reason": "import rename",
         "related_sites": []},
    ]
    uncertain = [
        {"file": "main.py", "line": 153, "reason": "depends on line 68",
         "related_sites": [{"file": "main.py", "line": 68}]},
        {"file": "main.py", "line": 170, "reason": "needs host/port from line 68",
         "related_sites": [{"file": "main.py", "line": 68}]},
    ]
    sites_by_key, group_id_by_key, group_members_by_id = _group_by_related_sites(proposed, uncertain)

    assert group_id_by_key[("main.py", 68)] == group_id_by_key[("main.py", 153)] == group_id_by_key[("main.py", 170)]
    assert ("main.py", 29) not in group_id_by_key
    gid = group_id_by_key[("main.py", 68)]
    assert group_members_by_id[gid] == [("main.py", 68), ("main.py", 153), ("main.py", 170)]


def test_related_site_outside_given_sites_forms_no_edge():
    proposed = [
        {"file": "main.py", "line": 1, "reason": "r",
         "related_sites": [{"file": "main.py", "line": 999}]},  # never a candidate at all
    ]
    _, group_id_by_key, group_members_by_id = _group_by_related_sites(proposed, [])
    assert group_id_by_key == {}
    assert group_members_by_id == {}


def test_singleton_sites_get_no_group_id():
    proposed = [{"file": "a.py", "line": 1, "reason": "r", "related_sites": []}]
    _, group_id_by_key, _ = _group_by_related_sites(proposed, [])
    assert group_id_by_key == {}


def test_sites_missing_related_sites_field_are_tolerated():
    # fixgen.run() may be handed sites built directly (bypassing
    # adjudicate.py's now-mandatory schema field), e.g. in older/simpler
    # tests -- grouping must degrade to "no group" rather than KeyError.
    proposed = [{"file": "a.py", "line": 1, "reason": "r"}]
    _, group_id_by_key, _ = _group_by_related_sites(proposed, [])
    assert group_id_by_key == {}


# ---------------------------------------------------------------------
# fixgen.run() -- deterministic pre-model group decline
# ---------------------------------------------------------------------

def test_span_declined_anchor_propagates_group_to_uncertain_siblings(tmp_path):
    # The real run-azeroth/run-youtrack-v2 shape: the group's only
    # proposed member is already caught by the multi-line-span guard, so
    # no group_consistency_guard entry is produced -- but group_id/
    # group_members must still be attached to that span entry so the
    # coupling is visible at all.
    reader = _make_repo(tmp_path, body=AZEROTH_SHAPED_BODY)
    proposed = [{"file": "main.py", "line": 3, "snippet": "mcp = FastMCP(", "pattern": "1",
                 "reason": "constructor referencing FastMCP", "related_sites": []}]
    uncertain = [
        {"file": "main.py", "line": 13, "snippet": "    starlette_app = mcp.sse_app()",
         "reason": "depends on what was passed to the FastMCP( constructor at line 3",
         "related_sites": [{"file": "main.py", "line": 3}]},
        {"file": "main.py", "line": 16, "snippet": "    mcp.run(transport=\"sse\")",
         "reason": "host/port formerly given to the constructor must now be passed here",
         "related_sites": [{"file": "main.py", "line": 3}]},
    ]
    client = FakeLLMClient([])
    merged = fixgen.run(client, reader, proposed, FACTBLOCK, str(tmp_path / "wd"),
                         uncertain_sites=uncertain, chunk_size=40)

    assert client.calls == []
    assert merged["fixes"] == []
    assert len(merged["flagged_for_human"]) == 1
    flag = merged["flagged_for_human"][0]
    assert flag["line"] == 3
    assert flag["flag_source"] == "multiline_span_guard"  # unchanged -- still the real reason
    assert flag["group_id"] == "main.py:3"
    member_keys = {(m["file"], m["line"]) for m in flag["group_members"]}
    assert member_keys == {("main.py", 3), ("main.py", 13), ("main.py", 16)}
    roles = {(m["file"], m["line"]): m["role"] for m in flag["group_members"]}
    assert roles[("main.py", 3)] == "proposed"
    assert roles[("main.py", 13)] == "uncertain"
    assert roles[("main.py", 16)] == "uncertain"


def test_single_line_anchor_coupled_to_uncertain_sibling_declines_without_model_call(tmp_path):
    # Not present in any run's evidence (the design pass scoped the
    # model-facing joint-resolution path out explicitly for this shape),
    # but the deterministic decline must still fire: fixgen "cannot
    # produce a jointly-consistent set" for a group containing an
    # uncertain member regardless of whether the anchor itself is
    # multi-line.
    body = "x = 1\ny = 2\nz = call(x)\n"
    reader = _make_repo(tmp_path, body=body)
    proposed = [{"file": "main.py", "line": 1, "snippet": "x = 1", "pattern": "1",
                 "reason": "x must change", "related_sites": [{"file": "main.py", "line": 3}]}]
    uncertain = [{"file": "main.py", "line": 3, "snippet": "z = call(x)",
                  "reason": "depends on x's new value",
                  "related_sites": [{"file": "main.py", "line": 1}]}]
    client = FakeLLMClient([])  # never called -- IndexError if it were
    merged = fixgen.run(client, reader, proposed, FACTBLOCK, str(tmp_path / "wd"),
                         uncertain_sites=uncertain, chunk_size=40)

    assert client.calls == []
    assert merged["fixes"] == []
    flag = merged["flagged_for_human"][0]
    assert flag["file"] == "main.py" and flag["line"] == 1
    assert flag["flag_source"] == "group_consistency_guard"
    assert "main.py:3" in flag["reason"]
    assert "not confirmed by adjudication" in flag["reason"]


def test_uncertain_site_never_appears_as_its_own_fix_or_flag(tmp_path):
    body = "x = 1\ny = 2\nz = call(x)\n"
    reader = _make_repo(tmp_path, body=body)
    proposed = [{"file": "main.py", "line": 1, "snippet": "x = 1", "pattern": "1",
                 "reason": "x must change", "related_sites": [{"file": "main.py", "line": 3}]}]
    uncertain = [{"file": "main.py", "line": 3, "snippet": "z = call(x)",
                  "reason": "depends on x", "related_sites": [{"file": "main.py", "line": 1}]}]
    client = FakeLLMClient([])
    merged = fixgen.run(client, reader, proposed, FACTBLOCK, str(tmp_path / "wd"),
                         uncertain_sites=uncertain, chunk_size=40)

    all_keys = {(i["file"], i["line"]) for i in merged["fixes"] + merged["flagged_for_human"]}
    assert ("main.py", 3) not in all_keys  # only the proposed companion (line 1) is a bucket entry


def test_ungrouped_confident_sites_reach_the_model_unaffected(tmp_path):
    body = "import old_pkg\n"
    reader = _make_repo(tmp_path, body=body)
    proposed = [{"file": "main.py", "line": 1, "snippet": "import old_pkg", "pattern": "1",
                 "reason": "import rename", "related_sites": []}]
    response = {
        "fixes": [{"file": "main.py", "line": 1, "end_line": 1, "original_lines": ["import old_pkg"], "proposed_lines": ["import new_pkg"], "reason": "renamed"}],
        "flagged_for_human": [],
    }
    client = FakeLLMClient([response])
    merged = fixgen.run(client, reader, proposed, FACTBLOCK, str(tmp_path / "wd"),
                         uncertain_sites=[], chunk_size=40)

    assert len(client.calls) == 1
    assert merged["fixes"][0]["proposed_lines"] == ["import new_pkg"]


def test_uncertain_sites_default_to_no_grouping(tmp_path):
    # Omitting uncertain_sites (the default) must behave exactly as
    # before this increment -- no site is ever grouped with anything.
    body = "x = 1\ny = 2\n"
    reader = _make_repo(tmp_path, body=body)
    proposed = [{"file": "main.py", "line": 1, "snippet": "x = 1", "pattern": "1", "reason": "r",
                 "related_sites": [{"file": "main.py", "line": 2}]}]
    response = {
        "fixes": [{"file": "main.py", "line": 1, "end_line": 1, "original_lines": ["x = 1"], "proposed_lines": ["x = 10"], "reason": "fixed"}],
        "flagged_for_human": [],
    }
    client = FakeLLMClient([response])
    merged = fixgen.run(client, reader, proposed, FACTBLOCK, str(tmp_path / "wd"), chunk_size=40)

    assert len(client.calls) == 1
    assert merged["fixes"][0]["line"] == 1


def test_two_confident_coupled_sites_both_reach_the_model_together(tmp_path):
    body = "x = 1\ny = 2\n"
    reader = _make_repo(tmp_path, body=body)
    proposed = [
        {"file": "main.py", "line": 1, "snippet": "x = 1", "pattern": "1", "reason": "r1",
         "related_sites": [{"file": "main.py", "line": 2}]},
        {"file": "main.py", "line": 2, "snippet": "y = 2", "pattern": "1", "reason": "r2",
         "related_sites": [{"file": "main.py", "line": 1}]},
    ]
    response = {
        "fixes": [
            {"file": "main.py", "line": 1, "end_line": 1, "original_lines": ["x = 1"], "proposed_lines": ["x = 10"], "reason": "r"},
            {"file": "main.py", "line": 2, "end_line": 2, "original_lines": ["y = 2"], "proposed_lines": ["y = 20"], "reason": "r"},
        ],
        "flagged_for_human": [],
    }
    client = FakeLLMClient([response])
    merged = fixgen.run(client, reader, proposed, FACTBLOCK, str(tmp_path / "wd"), chunk_size=40)

    assert len(client.calls) == 1  # no model-facing group prompt built -- both just land in one chunk
    assert len(merged["fixes"]) == 2


def test_torn_group_is_a_hard_validation_failure(tmp_path):
    body = "x = 1\ny = 2\n"
    reader = _make_repo(tmp_path, body=body)
    proposed = [
        {"file": "main.py", "line": 1, "snippet": "x = 1", "pattern": "1", "reason": "r1",
         "related_sites": [{"file": "main.py", "line": 2}]},
        {"file": "main.py", "line": 2, "snippet": "y = 2", "pattern": "1", "reason": "r2",
         "related_sites": [{"file": "main.py", "line": 1}]},
    ]
    # The model splits a coupled pair -- one fixed, one flagged. Must be
    # rejected outright, never silently accepted with one site fixed alone
    # (exactly the youtrack-mcp failure shape).
    response = {
        "fixes": [{"file": "main.py", "line": 1, "end_line": 1, "original_lines": ["x = 1"], "proposed_lines": ["x = 10"], "reason": "fixed"}],
        "flagged_for_human": [{"file": "main.py", "line": 2, "reason": "unrelated decline"}],
    }
    client = FakeLLMClient([response])
    with pytest.raises(ValueError, match="split across buckets"):
        fixgen.run(client, reader, proposed, FACTBLOCK, str(tmp_path / "wd"), chunk_size=40)


# ---------------------------------------------------------------------
# validate.py -- related_sites schema enforcement
# ---------------------------------------------------------------------

def test_validate_adjudication_requires_related_sites_on_proposed_sites():
    data = {
        "proposed_sites": [{"file": "a.py", "line": 1, "snippet": "x", "pattern": "1", "reason": "r"}],
        "flag_uncertain": [], "considered_and_rejected": [],
    }
    with pytest.raises(ValueError, match="related_sites"):
        validate.validate_adjudication_dict(data)


def test_validate_adjudication_requires_related_sites_on_flag_uncertain():
    data = {
        "proposed_sites": [], "considered_and_rejected": [],
        "flag_uncertain": [{"file": "a.py", "line": 1, "snippet": "x", "reason": "r"}],
    }
    with pytest.raises(ValueError, match="related_sites"):
        validate.validate_adjudication_dict(data)


def test_validate_adjudication_does_not_require_related_sites_on_rejected():
    data = {
        "proposed_sites": [], "flag_uncertain": [],
        "considered_and_rejected": [{"file": "a.py", "line": 1, "snippet": "x", "reason": "r"}],
    }
    validate.validate_adjudication_dict(data)  # does not raise


def test_validate_adjudication_accepts_empty_related_sites_list():
    data = {
        "proposed_sites": [{"file": "a.py", "line": 1, "snippet": "x", "pattern": "1",
                             "reason": "r", "related_sites": []}],
        "flag_uncertain": [], "considered_and_rejected": [],
    }
    validate.validate_adjudication_dict(data)  # does not raise


def test_validate_adjudication_rejects_malformed_related_sites_item():
    data = {
        "proposed_sites": [{"file": "a.py", "line": 1, "snippet": "x", "pattern": "1",
                             "reason": "r", "related_sites": [{"file": "b.py"}]}],  # missing "line"
        "flag_uncertain": [], "considered_and_rejected": [],
    }
    with pytest.raises(ValueError, match="related_sites\\[0\\]\\.line"):
        validate.validate_adjudication_dict(data)


# ---------------------------------------------------------------------
# report.py -- coupled-group rendering
# ---------------------------------------------------------------------

def test_report_renders_group_section_with_apply_together_note(tmp_path):
    fixgen_expanded = {
        "fixes": [],
        "flagged_for_human": [{
            "file": "main.py", "line": 1,
            "reason": "this site is part of a coupled edit group with main.py:3 -- ...",
            "flag_source": "group_consistency_guard",
            "group_id": "main.py:1",
            "group_members": [
                {"file": "main.py", "line": 1, "role": "proposed", "reason": "x must change"},
                {"file": "main.py", "line": 3, "role": "uncertain", "reason": "depends on x"},
            ],
        }],
    }
    expanded_merged = {
        "proposed_sites": [{"file": "main.py", "line": 1, "snippet": "x = 1", "pattern": "1",
                             "reason": "x must change"}],
        "flag_uncertain": [{"file": "main.py", "line": 3, "snippet": "z = call(x)",
                             "reason": "depends on x"}],
        "considered_and_rejected": [],
    }
    path = report.write(
        str(tmp_path), expanded_merged, {}, FACTBLOCK, {"patterns": {"p1": "x"}},
        fixgen_expanded=fixgen_expanded, verification_report=None,
    )
    text = open(path).read()
    assert "Coupled edit group" in text
    assert "together or not at all" in text
    assert "**Group `main.py:1`**" in text
    assert "main.py:1" in text and "main.py:3" in text
    assert "not confirmed by adjudication" in text


def test_report_renders_span_declined_group_without_duplicating_the_span_entry(tmp_path):
    # The real azeroth/youtrack-v2 shape: no group_consistency_guard entry
    # exists at all, only an enriched multiline_span_guard one.
    fixgen_expanded = {
        "fixes": [],
        "flagged_for_human": [{
            "file": "main.py", "line": 3,
            "reason": "this line is part of a multi-line statement spanning lines 3-7; ...",
            "flag_source": "multiline_span_guard",
            "span": [3, 7],
            "group_id": "main.py:3",
            "group_members": [
                {"file": "main.py", "line": 3, "role": "proposed", "reason": "constructor"},
                {"file": "main.py", "line": 13, "role": "uncertain", "reason": "depends on line 3"},
            ],
        }],
    }
    expanded_merged = {
        "proposed_sites": [{"file": "main.py", "line": 3, "snippet": "mcp = FastMCP(",
                             "pattern": "1", "reason": "constructor"}],
        "flag_uncertain": [{"file": "main.py", "line": 13, "snippet": "starlette_app = mcp.sse_app()",
                             "reason": "depends on line 3"}],
        "considered_and_rejected": [],
    }
    path = report.write(
        str(tmp_path), expanded_merged, {}, FACTBLOCK, {"patterns": {"p1": "x"}},
        fixgen_expanded=fixgen_expanded, verification_report=None,
    )
    text = open(path).read()
    assert "### Not evaluated -- multi-line statement (1)" in text
    assert "### Coupled edit group" in text
    # main.py:3's own reason appears once under "Not evaluated", and is
    # cross-referenced (not duplicated with its own bullet reason text)
    # under the group section.
    assert text.count("this line is part of a multi-line statement spanning lines 3-7") == 1
    assert "declined above as a multi-line statement" in text


# ---------------------------------------------------------------------
# Joint resolution -- a group with NO uncertain member but a member the
# multi-line-span guard would otherwise decline alone (the youtrack-mcp
# shape) is sent to the model as one coordinated call instead of being
# auto-declined. Same body shape as AZEROTH_SHAPED_BODY, but both sites
# are CONFIRMED (proposed), not uncertain -- the exact classification
# boundary that routes a group to _run_joint_group instead of pass 2's
# automatic decline.
# ---------------------------------------------------------------------

AZEROTH_JOINT_BODY = (
    "import os\n"                        # line 1
    "\n"                                 # line 2
    "mcp = FastMCP(\n"                   # line 3 -- multi-line anchor
    "    \"name\",\n"                    # line 4
    "    host=host,\n"                   # line 5
    "    port=port\n"                    # line 6
    ")\n"                                # line 7
    "\n"                                 # line 8
    "if __name__ == \"__main__\":\n"     # line 9
    "    mcp.run(transport=\"sse\")\n"   # line 10
)

_JOINT_PROPOSED = [
    {"file": "main.py", "line": 3, "snippet": "mcp = FastMCP(", "pattern": "1",
     "reason": "constructor referencing FastMCP",
     "related_sites": [{"file": "main.py", "line": 10}]},
    {"file": "main.py", "line": 10, "snippet": "    mcp.run(transport=\"sse\")", "pattern": "1",
     "reason": "host/port formerly given to the constructor must now be passed here",
     "related_sites": [{"file": "main.py", "line": 3}]},
]

_JOINT_SUCCESS_RESPONSE = {
    "fixes": [
        {"file": "main.py", "line": 3, "end_line": 7,
         "original_lines": ["mcp = FastMCP(", "    \"name\",", "    host=host,", "    port=port", ")"],
         "proposed_lines": ["mcp = FastMCP(", "    \"name\",", ")"],
         "reason": "host/port moved off the constructor"},
        {"file": "main.py", "line": 10, "end_line": 10,
         "original_lines": ["    mcp.run(transport=\"sse\")"],
         "proposed_lines": ["    mcp.run(transport=\"sse\", host=host, port=port)"],
         "reason": "host/port now passed to run()"},
    ],
    "flagged_for_human": [],
}


def test_joint_resolve_group_ships_a_verified_coordinated_fix(tmp_path):
    reader = _make_repo(tmp_path, body=AZEROTH_JOINT_BODY)
    client = FakeLLMClient([_JOINT_SUCCESS_RESPONSE])

    merged = fixgen.run(client, reader, _JOINT_PROPOSED, FACTBLOCK, str(tmp_path / "wd"),
                         uncertain_sites=[], chunk_size=40)

    assert len(client.calls) == 1  # one joint call, no per-site chunk call needed
    assert client.calls[0]["stage"] == "fixgen_group_main.py_3"
    assert merged["flagged_for_human"] == []
    assert len(merged["fixes"]) == 2
    assert {f["line"] for f in merged["fixes"]} == {3, 10}
    for f in merged["fixes"]:
        assert f["group_id"] == "main.py:3"


def test_joint_resolve_group_shows_full_statement_span_in_context(tmp_path):
    reader = _make_repo(tmp_path, body=AZEROTH_JOINT_BODY)
    client = FakeLLMClient([_JOINT_SUCCESS_RESPONSE])

    fixgen.run(client, reader, _JOINT_PROPOSED, FACTBLOCK, str(tmp_path / "wd"),
               uncertain_sites=[], chunk_size=40)

    user_text = client.calls[0]["user_text"]
    assert "Statement span: lines 3-7" in user_text
    assert "mcp = FastMCP(" in user_text
    assert ")" in user_text  # the constructor's closing line is shown too, not just its opener


def test_joint_resolve_group_falls_back_to_flagged_when_value_flow_guard_fails(tmp_path):
    bad_response = {
        "fixes": [
            {"file": "main.py", "line": 3, "end_line": 7,
             "original_lines": ["mcp = FastMCP(", "    \"name\",", "    host=host,", "    port=port", ")"],
             "proposed_lines": ["mcp = FastMCP(", "    \"name\",", ")"],
             "reason": "host/port moved off the constructor"},
            {"file": "main.py", "line": 10, "end_line": 10,
             "original_lines": ["    mcp.run(transport=\"sse\")"],
             "proposed_lines": ["    mcp.run(transport=\"sse\")"],  # host/port never threaded through
             "reason": "no change needed here"},
        ],
        "flagged_for_human": [],
    }
    reader = _make_repo(tmp_path, body=AZEROTH_JOINT_BODY)
    client = FakeLLMClient([bad_response])

    merged = fixgen.run(client, reader, _JOINT_PROPOSED, FACTBLOCK, str(tmp_path / "wd"),
                         uncertain_sites=[], chunk_size=40)

    assert merged["fixes"] == []
    assert len(merged["flagged_for_human"]) == 2
    for flag in merged["flagged_for_human"]:
        assert flag["flag_source"] == "value_flow_guard"
        assert flag["group_id"] == "main.py:3"
        assert "host" in flag["reason"] and "port" in flag["reason"]


def test_joint_resolve_group_model_declines_jointly(tmp_path):
    decline_response = {
        "fixes": [],
        "flagged_for_human": [
            {"file": "main.py", "line": 3, "reason": "not confident about the default host value"},
            {"file": "main.py", "line": 10, "reason": "companion at line 3 was declined"},
        ],
    }
    reader = _make_repo(tmp_path, body=AZEROTH_JOINT_BODY)
    client = FakeLLMClient([decline_response])

    merged = fixgen.run(client, reader, _JOINT_PROPOSED, FACTBLOCK, str(tmp_path / "wd"),
                         uncertain_sites=[], chunk_size=40)

    assert merged["fixes"] == []
    assert len(merged["flagged_for_human"]) == 2
    for flag in merged["flagged_for_human"]:
        assert flag["flag_source"] == "joint_resolution_declined"
        assert flag["group_id"] == "main.py:3"


def test_joint_resolve_group_torn_response_raises(tmp_path):
    torn_response = {
        "fixes": [{
            "file": "main.py", "line": 3, "end_line": 7,
            "original_lines": ["mcp = FastMCP(", "    \"name\",", "    host=host,", "    port=port", ")"],
            "proposed_lines": ["mcp = FastMCP(", "    \"name\",", ")"],
            "reason": "host/port moved off the constructor",
        }],
        "flagged_for_human": [{"file": "main.py", "line": 10, "reason": "declined anyway"}],
    }
    reader = _make_repo(tmp_path, body=AZEROTH_JOINT_BODY)
    client = FakeLLMClient([torn_response])

    with pytest.raises(ValueError, match="split across buckets"):
        fixgen.run(client, reader, _JOINT_PROPOSED, FACTBLOCK, str(tmp_path / "wd"),
                   uncertain_sites=[], chunk_size=40)


def test_joint_resolve_group_resumes_without_a_model_call(tmp_path):
    reader = _make_repo(tmp_path, body=AZEROTH_JOINT_BODY)
    workdir = str(tmp_path / "wd")
    fg_dir = os.path.join(workdir, "fixgen")
    os.makedirs(fg_dir, exist_ok=True)
    with open(os.path.join(fg_dir, "group_main.py_3.json"), "w") as f:
        json.dump(_JOINT_SUCCESS_RESPONSE, f)

    client = FakeLLMClient([])  # any call would IndexError -- proves the model is never asked
    merged = fixgen.run(client, reader, _JOINT_PROPOSED, FACTBLOCK, workdir,
                         uncertain_sites=[], chunk_size=40)

    assert client.calls == []
    assert len(merged["fixes"]) == 2


def test_joint_resolve_does_not_fire_for_a_group_with_no_span_member(tmp_path):
    # A group with no uncertain member and no span member at all (both
    # sites ordinary and single-line) is NOT routed to joint resolution --
    # it reaches the model independently, same chunk, no group framing,
    # exactly as test_two_confident_coupled_sites_both_reach_the_model_together
    # already covers. This just confirms the classification boundary from
    # the joint-resolution side: no span anywhere in the group means no
    # "fixgen_group_*" call is ever made.
    body = "x = 1\ny = 2\n"
    reader = _make_repo(tmp_path, body=body)
    proposed = [
        {"file": "main.py", "line": 1, "snippet": "x = 1", "pattern": "1", "reason": "r1",
         "related_sites": [{"file": "main.py", "line": 2}]},
        {"file": "main.py", "line": 2, "snippet": "y = 2", "pattern": "1", "reason": "r2",
         "related_sites": [{"file": "main.py", "line": 1}]},
    ]
    response = {
        "fixes": [
            {"file": "main.py", "line": 1, "end_line": 1,
             "original_lines": ["x = 1"], "proposed_lines": ["x = 10"], "reason": "r"},
            {"file": "main.py", "line": 2, "end_line": 2,
             "original_lines": ["y = 2"], "proposed_lines": ["y = 20"], "reason": "r"},
        ],
        "flagged_for_human": [],
    }
    client = FakeLLMClient([response])

    merged = fixgen.run(client, reader, proposed, FACTBLOCK, str(tmp_path / "wd"), chunk_size=40)

    assert len(client.calls) == 1
    assert not client.calls[0]["stage"].startswith("fixgen_group_")
    assert len(merged["fixes"]) == 2


# ---------------------------------------------------------------------
# report.py -- rendering for the joint-resolution outcomes above
# ---------------------------------------------------------------------

def test_report_renders_coordinated_group_badge_on_a_shipped_joint_fix(tmp_path):
    fixgen_expanded = {
        "fixes": [
            {"file": "main.py", "line": 3, "end_line": 7,
             "original_lines": ["mcp = FastMCP(", "    \"name\",", "    host=host,", "    port=port", ")"],
             "proposed_lines": ["mcp = FastMCP(", "    \"name\",", ")"],
             "reason": "host/port moved off the constructor", "group_id": "main.py:3"},
            {"file": "main.py", "line": 10, "end_line": 10,
             "original_lines": ["    mcp.run(transport=\"sse\")"],
             "proposed_lines": ["    mcp.run(transport=\"sse\", host=host, port=port)"],
             "reason": "host/port now passed to run()", "group_id": "main.py:3"},
        ],
        "flagged_for_human": [],
    }
    expanded_merged = {
        "proposed_sites": [
            {"file": "main.py", "line": 3, "snippet": "mcp = FastMCP(", "pattern": "1", "reason": "constructor"},
            {"file": "main.py", "line": 10, "snippet": "    mcp.run(transport=\"sse\")", "pattern": "1", "reason": "run call"},
        ],
        "flag_uncertain": [], "considered_and_rejected": [],
    }
    path = report.write(
        str(tmp_path), expanded_merged, {}, FACTBLOCK, {"patterns": {"p1": "x"}},
        fixgen_expanded=fixgen_expanded, verification_report=None,
    )
    text = open(path).read()
    assert "## FIX (2)" in text
    assert text.count("coordinated group main.py:3") == 2
    assert "## FLAG-FOR-HUMAN (0)" in text


def test_report_renders_value_flow_guard_rejection(tmp_path):
    fixgen_expanded = {
        "fixes": [],
        "flagged_for_human": [
            {"file": "main.py", "line": 3,
             "reason": "this site's confident-looking joint fix for coordinated group "
                       "main.py:3 was rejected by the deterministic value-flow guard: "
                       "value(s) removed with no matching reappearance elsewhere in the "
                       "group: main.py:3 keyword 'host', main.py:3 keyword 'port'.",
             "flag_source": "value_flow_guard", "group_id": "main.py:3",
             "group_members": [
                 {"file": "main.py", "line": 3, "role": "proposed", "reason": "constructor"},
                 {"file": "main.py", "line": 10, "role": "proposed", "reason": "run call"},
             ]},
            {"file": "main.py", "line": 10,
             "reason": "this site's confident-looking joint fix for coordinated group "
                       "main.py:3 was rejected by the deterministic value-flow guard: ...",
             "flag_source": "value_flow_guard", "group_id": "main.py:3",
             "group_members": [
                 {"file": "main.py", "line": 3, "role": "proposed", "reason": "constructor"},
                 {"file": "main.py", "line": 10, "role": "proposed", "reason": "run call"},
             ]},
        ],
    }
    expanded_merged = {
        "proposed_sites": [
            {"file": "main.py", "line": 3, "snippet": "mcp = FastMCP(", "pattern": "1", "reason": "constructor"},
            {"file": "main.py", "line": 10, "snippet": "    mcp.run(transport=\"sse\")", "pattern": "1", "reason": "run call"},
        ],
        "flag_uncertain": [], "considered_and_rejected": [],
    }
    path = report.write(
        str(tmp_path), expanded_merged, {}, FACTBLOCK, {"patterns": {"p1": "x"}},
        fixgen_expanded=fixgen_expanded, verification_report=None,
    )
    text = open(path).read()
    assert "### Coupled edit group" in text
    assert text.count("declined here -- a jointly-resolved fix was rejected by the value-flow guard") == 2
    # never rendered a second time under "Model judgment call" -- it's
    # excluded from model_flagged specifically so it isn't double-listed.
    assert "### Model judgment call" not in text


def test_report_renders_model_own_joint_decline(tmp_path):
    fixgen_expanded = {
        "fixes": [],
        "flagged_for_human": [
            {"file": "main.py", "line": 3, "reason": "not confident about the default host value",
             "flag_source": "joint_resolution_declined", "group_id": "main.py:3",
             "group_members": [
                 {"file": "main.py", "line": 3, "role": "proposed", "reason": "constructor"},
                 {"file": "main.py", "line": 10, "role": "proposed", "reason": "run call"},
             ]},
            {"file": "main.py", "line": 10, "reason": "companion at line 3 was declined",
             "flag_source": "joint_resolution_declined", "group_id": "main.py:3",
             "group_members": [
                 {"file": "main.py", "line": 3, "role": "proposed", "reason": "constructor"},
                 {"file": "main.py", "line": 10, "role": "proposed", "reason": "run call"},
             ]},
        ],
    }
    expanded_merged = {
        "proposed_sites": [
            {"file": "main.py", "line": 3, "snippet": "mcp = FastMCP(", "pattern": "1", "reason": "constructor"},
            {"file": "main.py", "line": 10, "snippet": "    mcp.run(transport=\"sse\")", "pattern": "1", "reason": "run call"},
        ],
        "flag_uncertain": [], "considered_and_rejected": [],
    }
    path = report.write(
        str(tmp_path), expanded_merged, {}, FACTBLOCK, {"patterns": {"p1": "x"}},
        fixgen_expanded=fixgen_expanded, verification_report=None,
    )
    text = open(path).read()
    assert "### Coupled edit group" in text
    assert text.count("declined here -- the model itself chose not to resolve this group jointly") == 2
    assert "### Model judgment call" not in text
