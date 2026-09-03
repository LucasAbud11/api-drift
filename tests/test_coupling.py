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

def test_span_anchor_with_only_uncertain_dependents_now_reaches_a_solo_call(tmp_path):
    # The real run-azeroth/run-youtrack-v2 shape: main.py:3 is the ONLY
    # proposed member, its own related_sites is empty, and the only edges
    # touching it are two UNCERTAIN sites naming IT as their dependency
    # (13 and 16 need to see 3's constructor args). Before the
    # run-youtrack-solo fix, this pulled 3 into an undirected group and
    # declined it via multiline_span_guard with no model call at all --
    # exactly the bug: nothing about 3's OWN correctness depends on 13 or
    # 16 ever resolving, only the reverse. It must now reach its own solo
    # joint call instead (_resolution_groups excludes edges an UNCERTAIN
    # site declares, so 3 has zero RESOLUTION-view connections and gets a
    # synthetic singleton group). See
    # test_solo_call_decline_still_shows_the_full_uncertain_neighborhood
    # below for the companion check: visibility (13/16 in the roster) is
    # preserved even though this site is no longer blocked by them.
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
    response = {
        "fixes": [{"file": "main.py", "line": 3, "end_line": 7,
                   "original_lines": ["mcp = FastMCP(", "    \"name\",", "    host=host,", "    port=port", ")"],
                   "proposed_lines": ["mcp = FastMCP(", "    \"name\",", "    host=host,", "    port=port", ")"],
                   "reason": "class renamed, keyword args unchanged"}],
        "flagged_for_human": [],
    }
    client = FakeLLMClient([response])
    merged = fixgen.run(client, reader, proposed, FACTBLOCK, str(tmp_path / "wd"),
                         uncertain_sites=uncertain, chunk_size=40)

    assert len(client.calls) == 1
    assert client.calls[0]["stage"] == "fixgen_group_main.py_3"
    assert merged["flagged_for_human"] == []
    assert len(merged["fixes"]) == 1
    assert merged["fixes"][0]["line"] == 3
    # Fully-resolved fix still gets stamped with the VISIBILITY group_id
    # (report.py's coordinated-group badge), not the solo RESOLUTION id --
    # main.py:3 has a broader undirected neighborhood (13, 16) even though
    # it was resolved alone.
    assert merged["fixes"][0]["group_id"] == "main.py:3"


def test_solo_call_decline_still_shows_the_full_uncertain_neighborhood(tmp_path):
    # Companion to the test above: when the solo call DOES decline (or
    # fails value-flow), the resulting flag must still show the full
    # undirected VISIBILITY roster (13, 16) -- report visibility is a real
    # requirement, unaffected by RESOLUTION-view eligibility narrowing.
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
    response = {"fixes": [],
                "flagged_for_human": [{"file": "main.py", "line": 3,
                                        "reason": "not confident without seeing the call sites"}]}
    client = FakeLLMClient([response])
    merged = fixgen.run(client, reader, proposed, FACTBLOCK, str(tmp_path / "wd"),
                         uncertain_sites=uncertain, chunk_size=40)

    assert len(client.calls) == 1
    assert merged["fixes"] == []
    assert len(merged["flagged_for_human"]) == 1
    flag = merged["flagged_for_human"][0]
    assert flag["line"] == 3
    assert flag["flag_source"] == "joint_resolution_declined"
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
    # One-directional on purpose: site 1 names site 3 as its dependency,
    # site 3 names nothing (an uncertain site's own related_sites plays no
    # role in whether IT declines -- it always does, being uncertain).
    # Reciprocating the edge here would make this pair a mutual-dependency
    # contradiction instead (see the mutual_dependency_guard tests below),
    # which is a different case than the one this test targets.
    proposed = [{"file": "main.py", "line": 1, "snippet": "x = 1", "pattern": "1",
                 "reason": "x must change", "related_sites": [{"file": "main.py", "line": 3}]}]
    uncertain = [{"file": "main.py", "line": 3, "snippet": "z = call(x)",
                  "reason": "depends on x's new value", "related_sites": []}]
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
                  "reason": "depends on x", "related_sites": []}]
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
    # One-directional on purpose (site 2 depends on nothing) -- a single
    # edge is enough to union the pair into one group; reciprocating it
    # would make this a mutual-dependency contradiction instead, a
    # different case (see the mutual_dependency_guard tests below).
    proposed = [
        {"file": "main.py", "line": 1, "snippet": "x = 1", "pattern": "1", "reason": "r1",
         "related_sites": [{"file": "main.py", "line": 2}]},
        {"file": "main.py", "line": 2, "snippet": "y = 2", "pattern": "1", "reason": "r2",
         "related_sites": []},
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


def test_torn_group_demotes_the_dependent_fix_instead_of_aborting(tmp_path):
    body = "x = 1\ny = 2\n"
    reader = _make_repo(tmp_path, body=body)
    # One-directional on purpose (site 2 depends on nothing) -- a single
    # edge is enough to union the pair into one group; reciprocating it
    # would make this a mutual-dependency contradiction instead, a
    # different case (see the mutual_dependency_guard tests below).
    proposed = [
        {"file": "main.py", "line": 1, "snippet": "x = 1", "pattern": "1", "reason": "r1",
         "related_sites": [{"file": "main.py", "line": 2}]},
        {"file": "main.py", "line": 2, "snippet": "y = 2", "pattern": "1", "reason": "r2",
         "related_sites": []},
    ]
    # The model splits a coupled pair -- one fixed, one flagged. This must
    # never ship 1 alone (exactly the youtrack-mcp failure shape), but it
    # also must not abort the whole run over it (the real Pydantic run
    # this fallback is grounded in: one torn pair out of 229 sites) -- 1
    # is demoted to flagged_for_human, alongside 2's own independent
    # decline, and the run still completes.
    response = {
        "fixes": [{"file": "main.py", "line": 1, "end_line": 1, "original_lines": ["x = 1"], "proposed_lines": ["x = 10"], "reason": "fixed"}],
        "flagged_for_human": [{"file": "main.py", "line": 2, "reason": "unrelated decline"}],
    }
    client = FakeLLMClient([response])
    merged = fixgen.run(client, reader, proposed, FACTBLOCK, str(tmp_path / "wd"), chunk_size=40)

    assert merged["fixes"] == []
    assert len(merged["flagged_for_human"]) == 2
    by_line = {f["line"]: f for f in merged["flagged_for_human"]}
    assert by_line[1]["flag_source"] == "unresolved_dependency_guard"
    assert "main.py:2" in by_line[1]["reason"]
    assert by_line[1]["group_id"] == "main.py:1"
    assert {(m["file"], m["line"]) for m in by_line[1]["group_members"]} == {
        ("main.py", 1), ("main.py", 2),
    }
    # 2's own independent decline is untouched -- still whatever the model
    # itself said, not rewritten by this guard.
    assert by_line[2]["flag_source"] == "model_declined"
    assert by_line[2]["reason"] == "unrelated decline"


def test_torn_group_does_not_block_unrelated_fixes_in_the_same_run(tmp_path):
    # The actual bug report this fallback fixes: one torn coupled pair
    # must not abort a run with 200+ other, unrelated confident fixes.
    # Two chunks here stand in for that shape at a scale a unit test can
    # afford -- chunk_size=2 forces the coupled pair and the unrelated
    # site into separate per-chunk calls, same as the real run's 229
    # sites landing across many chunks.
    body = "x = 1\ny = 2\nz = 3\n"
    reader = _make_repo(tmp_path, body=body)
    proposed = [
        {"file": "main.py", "line": 1, "snippet": "x = 1", "pattern": "1", "reason": "r1",
         "related_sites": [{"file": "main.py", "line": 2}]},
        {"file": "main.py", "line": 2, "snippet": "y = 2", "pattern": "1", "reason": "r2",
         "related_sites": []},
        {"file": "main.py", "line": 3, "snippet": "z = 3", "pattern": "1", "reason": "r3",
         "related_sites": []},
    ]
    responses = [
        {
            "fixes": [{"file": "main.py", "line": 1, "end_line": 1,
                       "original_lines": ["x = 1"], "proposed_lines": ["x = 10"], "reason": "fixed"}],
            "flagged_for_human": [{"file": "main.py", "line": 2, "reason": "unrelated decline"}],
        },
        {
            "fixes": [{"file": "main.py", "line": 3, "end_line": 3,
                       "original_lines": ["z = 3"], "proposed_lines": ["z = 30"], "reason": "fixed"}],
            "flagged_for_human": [],
        },
    ]
    client = FakeLLMClient(responses)
    merged = fixgen.run(client, reader, proposed, FACTBLOCK, str(tmp_path / "wd"), chunk_size=2)

    assert [f["line"] for f in merged["fixes"]] == [3]
    assert {f["line"] for f in merged["flagged_for_human"]} == {1, 2}


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
    # One-directional on purpose (site 2 depends on nothing) -- a single
    # edge is enough to union the pair into one group; reciprocating it
    # would make this a mutual-dependency contradiction instead, a
    # different case (see the mutual_dependency_guard tests below).
    proposed = [
        {"file": "main.py", "line": 1, "snippet": "x = 1", "pattern": "1", "reason": "r1",
         "related_sites": [{"file": "main.py", "line": 2}]},
        {"file": "main.py", "line": 2, "snippet": "y = 2", "pattern": "1", "reason": "r2",
         "related_sites": []},
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


def test_report_renders_unresolved_dependency_guard_decline(tmp_path):
    # The fallback fixgen.run() now takes instead of aborting the whole
    # run: a fix demoted because its own dependency didn't also ship as a
    # fix must show up as a coupling decline, not under "Model judgment
    # call" (that would misrepresent this tool's own guard as the model's
    # verdict).
    fixgen_expanded = {
        "fixes": [],
        "flagged_for_human": [
            {"file": "constraint.py", "line": 508,
             "reason": "this site shipped as a confident fix, but its own dependency "
                       "constraint.py:512 did not also ship as a fix (bucket: "
                       "flagged_for_human) -- declined together with its dependency "
                       "instead of aborting the whole run.",
             "flag_source": "unresolved_dependency_guard", "group_id": "constraint.py:508",
             "group_members": [
                 {"file": "constraint.py", "line": 508, "role": "proposed", "reason": "default value"},
                 {"file": "constraint.py", "line": 512, "role": "proposed", "reason": "validator"},
             ]},
            {"file": "constraint.py", "line": 512, "reason": "unrelated model decline",
             "flag_source": "model_declined"},
        ],
    }
    expanded_merged = {
        "proposed_sites": [
            {"file": "constraint.py", "line": 508, "snippet": "x: int = None", "pattern": "1", "reason": "default value"},
            {"file": "constraint.py", "line": 512, "snippet": "always=True", "pattern": "1", "reason": "validator"},
        ],
        "flag_uncertain": [], "considered_and_rejected": [],
    }
    path = report.write(
        str(tmp_path), expanded_merged, {}, FACTBLOCK, {"patterns": {"p1": "x"}},
        fixgen_expanded=fixgen_expanded, verification_report=None,
    )
    text = open(path).read()
    assert "### Coupled edit group" in text
    assert ("declined here -- shipped as a fix independently, but its own dependency "
            "elsewhere in this group did not also ship as a fix") in text
    # Not under "Model judgment call" -- this is the tool's own guard
    # deciding, not the model.
    if "### Model judgment call" in text:
        section = text.split("### Model judgment call", 1)[1]
        assert "constraint.py:508" not in section


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


def test_report_renders_ordinary_chunk_decline_under_model_judgment_call(tmp_path):
    # An ordinary, non-span, non-grouped confirmed site declined in a plain
    # per-chunk call (fixgen.run()'s "model_declined" tag) -- no group_id,
    # so it belongs under "Model judgment call", not "Coupled edit group".
    # A second, group_flagged entry is included alongside it so more than
    # one category is present -- report.py only prints the "### Model
    # judgment call" subheading itself when n_categories > 1, otherwise
    # the lone category's items render directly under FLAG-FOR-HUMAN with
    # no subheading at all (see test above for that single-category case).
    fixgen_expanded = {
        "fixes": [],
        "flagged_for_human": [
            {"file": "main.py", "line": 20,
             "reason": "requires coordinated restructuring, not a single-line fix",
             "flag_source": "model_declined"},
            {"file": "other.py", "line": 5, "reason": "not confident jointly",
             "flag_source": "joint_resolution_declined", "group_id": "other.py:5",
             "group_members": [{"file": "other.py", "line": 5, "role": "proposed",
                                 "reason": "constructor"}]},
        ],
    }
    expanded_merged = {
        "proposed_sites": [
            {"file": "main.py", "line": 20, "snippet": "old_pkg.thing()", "pattern": "1",
             "reason": "call site"},
            {"file": "other.py", "line": 5, "snippet": "OldMCP(", "pattern": "1",
             "reason": "constructor"},
        ],
        "flag_uncertain": [], "considered_and_rejected": [],
    }
    path = report.write(
        str(tmp_path), expanded_merged, {}, FACTBLOCK, {"patterns": {"p1": "x"}},
        fixgen_expanded=fixgen_expanded, verification_report=None,
    )
    text = open(path).read()
    model_section = text.split("### Model judgment call")[1]
    assert "### Coupled edit group" not in model_section
    assert "requires coordinated restructuring, not a single-line fix" in model_section
    assert "not confident jointly" not in model_section


# ---------------------------------------------------------------------
# Directional dependency -- reproduces the run-youtrack-joint regression
# exactly: related_sites is directional (a site names what IT depends on,
# never what depends on it), but grouping was treating it as an
# undirected edge. Four sites, one connected undirected component:
#
#   P main.py:10  related: []        -- import rename, no dependency
#   P main.py:25  related: [10]      -- return annotation, depends on 10
#   P main.py:27  related: [10]      -- multi-line constructor, depends on 10
#   U main.py:70  related: [27, 25]  -- uncertain, depends on 27 and 25
#
# Correct outcome: 10 and 25 are self-contained and must be fixable
# regardless of 70's status (nothing about their own correctness depends
# on 70 ever resolving); 27 declines on its own multi-line span,
# independent of the coupling logic; 70 declines as uncertain.
# ---------------------------------------------------------------------

def _line_padded_body(content_by_line, total_lines):
    lines = ["\n"] * total_lines
    for lineno, text in content_by_line.items():
        lines[lineno - 1] = text if text.endswith("\n") else text + "\n"
    return "".join(lines)


YOUTRACK_JOINT_BODY = _line_padded_body({
    10: "from mcp.server.fastmcp import FastMCP",
    25: "def create_server(host=\"0.0.0.0\", port=8000) -> FastMCP:",
    27: "    mcp = FastMCP(",
    28: "        \"name\",",
    29: "        host=host,",
    30: "        port=port",
    31: "    )",
    70: "mcp.run(transport=\"sse\")",
}, total_lines=70)

_YOUTRACK_PROPOSED = [
    {"file": "main.py", "line": 10, "snippet": "from mcp.server.fastmcp import FastMCP",
     "pattern": "1", "reason": "import path renamed", "related_sites": []},
    {"file": "main.py", "line": 25, "snippet": "def create_server(host=\"0.0.0.0\", port=8000) -> FastMCP:",
     "pattern": "1", "reason": "return annotation references the renamed class",
     "related_sites": [{"file": "main.py", "line": 10}]},
    {"file": "main.py", "line": 27, "snippet": "    mcp = FastMCP(",
     "pattern": "1", "reason": "constructor references the renamed class",
     "related_sites": [{"file": "main.py", "line": 10}]},
]
_YOUTRACK_UNCERTAIN = [
    {"file": "main.py", "line": 70, "snippet": "mcp.run(transport=\"sse\")",
     "reason": "may need host/port depending on how the constructor at 27 is resolved",
     "related_sites": [{"file": "main.py", "line": 27}, {"file": "main.py", "line": 25}]},
]


def test_directional_dependency_group_now_gets_a_real_joint_attempt(tmp_path):
    # _YOUTRACK_PROPOSED's 25 and 27 each have a REAL edge of their own
    # (both -> 10) -- unlike run-youtrack-solo's shape (see the dedicated
    # tests below), this ISN'T the "uncertain dependent contaminates an
    # unrelated site" bug; 10/25/27 form one genuine RESOLUTION group via
    # their OWN proposed-declared edges, same as before this fix. What
    # changes: group_class used to read has_uncertain off the UNDIRECTED
    # (VISIBILITY) view, which included uncertain 70 (only connected via
    # 70's OWN edges to 27/25) and declined the whole group as
    # "uncertain_decline" -- 27 auto-flagged, 10/25 saved only by the
    # separate directional-unsafe closure. Now group_class reads
    # has_uncertain off the RESOLUTION view, which correctly excludes
    # 70's edges: none of 10/25/27 are themselves uncertain, so the group
    # is "joint_resolve" -- all three get one real, coordinated attempt
    # instead of 27 being auto-declined on sight.
    reader = _make_repo(tmp_path, body=YOUTRACK_JOINT_BODY)
    response = {
        "fixes": [
            {"file": "main.py", "line": 10, "end_line": 10,
             "original_lines": ["from mcp.server.fastmcp import FastMCP"],
             "proposed_lines": ["from mcp.server.mcpserver import MCPServer"],
             "reason": "import path renamed"},
            {"file": "main.py", "line": 25, "end_line": 25,
             "original_lines": ["def create_server(host=\"0.0.0.0\", port=8000) -> FastMCP:"],
             "proposed_lines": ["def create_server(host=\"0.0.0.0\", port=8000) -> MCPServer:"],
             "reason": "return annotation renamed"},
            {"file": "main.py", "line": 27, "end_line": 31,
             "original_lines": ["    mcp = FastMCP(", "        \"name\",",
                                 "        host=host,", "        port=port", "    )"],
             "proposed_lines": ["    mcp = MCPServer(", "        \"name\",",
                                 "        host=host,", "        port=port", "    )"],
             "reason": "constructor renamed, keyword args unchanged"},
        ],
        "flagged_for_human": [],
    }
    client = FakeLLMClient([response])

    merged = fixgen.run(client, reader, _YOUTRACK_PROPOSED, FACTBLOCK, str(tmp_path / "wd"),
                         uncertain_sites=_YOUTRACK_UNCERTAIN, chunk_size=40)

    assert merged["flagged_for_human"] == []
    fixed_lines = {f["line"] for f in merged["fixes"]}
    assert fixed_lines == {10, 25, 27}
    assert len(client.calls) == 1
    assert client.calls[0]["stage"] == "fixgen_group_main.py_10"


def test_directional_dependency_decline_still_shows_10_25_27_and_70(tmp_path):
    # Companion: if the (now real) joint attempt for {10, 25, 27} declines
    # instead, the resulting flags must still show the full undirected
    # VISIBILITY neighborhood, INCLUDING uncertain 70 -- 70 was never sent
    # to the model (member_keys for the call itself is the RESOLUTION
    # view, {10, 25, 27} only), but a human reviewing the decline still
    # benefits from seeing that 70 depends on this group resolving.
    reader = _make_repo(tmp_path, body=YOUTRACK_JOINT_BODY)
    response = {
        "fixes": [],
        "flagged_for_human": [
            {"file": "main.py", "line": 10, "reason": "declined jointly with 25 and 27"},
            {"file": "main.py", "line": 25, "reason": "declined jointly with 10 and 27"},
            {"file": "main.py", "line": 27, "reason": "declined jointly with 10 and 25"},
        ],
    }
    client = FakeLLMClient([response])

    merged = fixgen.run(client, reader, _YOUTRACK_PROPOSED, FACTBLOCK, str(tmp_path / "wd"),
                         uncertain_sites=_YOUTRACK_UNCERTAIN, chunk_size=40)

    assert merged["fixes"] == []
    assert len(merged["flagged_for_human"]) == 3
    for flag in merged["flagged_for_human"]:
        assert flag["flag_source"] == "joint_resolution_declined"
        assert flag["group_id"] == "main.py:10"  # visibility root, same as resolution root here
        member_keys = {(m["file"], m["line"]) for m in flag["group_members"]}
        assert member_keys == {("main.py", 10), ("main.py", 25), ("main.py", 27), ("main.py", 70)}


# ---------------------------------------------------------------------
# run-youtrack-solo -- the exact regression this whole increment fixes,
# reproduced verbatim from the real stored artifact
# (~/Projects/api-drift-prs/run-youtrack-solo/adjudication/merged.json):
#
#   P 10 related: []
#   P 25 related: []
#   P 27 related: []      <- span-guarded, own links empty
#   U 70 related: [27, 25]
#
# Unlike _YOUTRACK_PROPOSED above (where 25/27 have REAL edges of their
# own to 10), here NONE of 10/25/27 has any edge of its own -- the ONLY
# edges are 70's (uncertain), naming 27 and 25 as ITS dependencies. Before
# this fix, _group_by_related_sites' undirected union still pulled 27
# into one component with 70 (and, transitively, 25), and group_class
# read has_uncertain off that same undirected component -- so 27 declined
# via multiline_span_guard with no model call, exactly like a site that
# genuinely depended on something unconfirmed, even though nothing about
# 27's OWN correctness depends on 70 ever resolving. The real stored
# run's own fixgen/merged.json confirms this: FIX 10, FIX 25, FLAG 27
# (multiline_span_guard) -- no model call for 27 ever happened.
# ---------------------------------------------------------------------

YOUTRACK_SOLO_BODY = _line_padded_body({
    10: "from mcp.server.fastmcp import FastMCP",
    25: "def create_server(host=\"0.0.0.0\", port=8000) -> FastMCP:",
    27: "    mcp = FastMCP(",
    28: "        \"name\",",
    29: "        host=host,",
    30: "        port=port",
    31: "    )",
    70: "mcp.run(transport=\"sse\")",
}, total_lines=70)

_YOUTRACK_SOLO_PROPOSED = [
    {"file": "main.py", "line": 10, "snippet": "from mcp.server.fastmcp import FastMCP",
     "pattern": "1", "reason": "import path renamed", "related_sites": []},
    {"file": "main.py", "line": 25, "snippet": "def create_server(host=\"0.0.0.0\", port=8000) -> FastMCP:",
     "pattern": "1", "reason": "return annotation references the renamed class", "related_sites": []},
    {"file": "main.py", "line": 27, "snippet": "    mcp = FastMCP(",
     "pattern": "1", "reason": "constructor references the renamed class", "related_sites": []},
]
_YOUTRACK_SOLO_UNCERTAIN = [
    {"file": "main.py", "line": 70, "snippet": "mcp.run(transport=\"sse\")",
     "reason": "may need host/port depending on how the constructor at 27 is resolved",
     "related_sites": [{"file": "main.py", "line": 27}, {"file": "main.py", "line": 25}]},
]


def test_youtrack_solo_shape_27_reaches_its_own_solo_call(tmp_path):
    reader = _make_repo(tmp_path, body=YOUTRACK_SOLO_BODY)
    solo_response = {
        "fixes": [{"file": "main.py", "line": 27, "end_line": 31,
                   "original_lines": ["    mcp = FastMCP(", "        \"name\",",
                                       "        host=host,", "        port=port", "    )"],
                   "proposed_lines": ["    mcp = MCPServer(", "        \"name\",",
                                       "        host=host,", "        port=port", "    )"],
                   "reason": "constructor renamed, keyword args unchanged"}],
        "flagged_for_human": [],
    }
    chunk_response = {
        "fixes": [
            {"file": "main.py", "line": 10, "end_line": 10,
             "original_lines": ["from mcp.server.fastmcp import FastMCP"],
             "proposed_lines": ["from mcp.server.mcpserver import MCPServer"],
             "reason": "import path renamed"},
            {"file": "main.py", "line": 25, "end_line": 25,
             "original_lines": ["def create_server(host=\"0.0.0.0\", port=8000) -> FastMCP:"],
             "proposed_lines": ["def create_server(host=\"0.0.0.0\", port=8000) -> MCPServer:"],
             "reason": "return annotation renamed"},
        ],
        "flagged_for_human": [],
    }
    # Joint-resolution calls (Pass 2) run before ordinary chunk calls.
    client = FakeLLMClient([solo_response, chunk_response])

    merged = fixgen.run(client, reader, _YOUTRACK_SOLO_PROPOSED, FACTBLOCK, str(tmp_path / "wd"),
                         uncertain_sites=_YOUTRACK_SOLO_UNCERTAIN, chunk_size=40)

    assert merged["flagged_for_human"] == []
    fixed_lines = {f["line"] for f in merged["fixes"]}
    assert fixed_lines == {10, 25, 27}
    fix27 = next(f for f in merged["fixes"] if f["line"] == 27)
    # Fix still shows the VISIBILITY neighborhood (70 depends on it),
    # not the bare solo RESOLUTION id.
    assert fix27["group_id"] == "main.py:25"  # visibility root: smallest of {25, 27, 70}

    assert len(client.calls) == 2
    stages = {c["stage"] for c in client.calls}
    assert stages == {"fixgen_group_main.py_27", "fixgen_chunk_000"}
    # 10 and 25 reach the model as ordinary, unrelated sites -- 25 has no
    # edges of its own either, so it's not swept into 27's solo call.
    chunk_call = next(c for c in client.calls if c["stage"] == "fixgen_chunk_000")
    assert "main.py:10" in chunk_call["user_text"] and "main.py:25" in chunk_call["user_text"]
    assert "main.py:27" not in chunk_call["user_text"]


def test_youtrack_solo_shape_decline_still_shows_25_27_and_70(tmp_path):
    # If 27's solo call declines, the flag must still show the full
    # undirected VISIBILITY neighborhood (25 and 70), even though neither
    # was sent to the model with it -- 25 has no edge to 27 either; it's
    # connected only via 70's own edges to both.
    reader = _make_repo(tmp_path, body=YOUTRACK_SOLO_BODY)
    solo_response = {
        "fixes": [],
        "flagged_for_human": [{"file": "main.py", "line": 27,
                                "reason": "not confident without seeing the call site"}],
    }
    chunk_response = {
        "fixes": [
            {"file": "main.py", "line": 10, "end_line": 10,
             "original_lines": ["from mcp.server.fastmcp import FastMCP"],
             "proposed_lines": ["from mcp.server.mcpserver import MCPServer"],
             "reason": "import path renamed"},
            {"file": "main.py", "line": 25, "end_line": 25,
             "original_lines": ["def create_server(host=\"0.0.0.0\", port=8000) -> FastMCP:"],
             "proposed_lines": ["def create_server(host=\"0.0.0.0\", port=8000) -> MCPServer:"],
             "reason": "return annotation renamed"},
        ],
        "flagged_for_human": [],
    }
    client = FakeLLMClient([solo_response, chunk_response])

    merged = fixgen.run(client, reader, _YOUTRACK_SOLO_PROPOSED, FACTBLOCK, str(tmp_path / "wd"),
                         uncertain_sites=_YOUTRACK_SOLO_UNCERTAIN, chunk_size=40)

    assert {f["line"] for f in merged["fixes"]} == {10, 25}
    flag27 = next(f for f in merged["flagged_for_human"] if f["line"] == 27)
    assert flag27["flag_source"] == "joint_resolution_declined"
    assert flag27["group_id"] == "main.py:25"
    member_keys = {(m["file"], m["line"]) for m in flag27["group_members"]}
    assert member_keys == {("main.py", 25), ("main.py", 27), ("main.py", 70)}


def test_directional_dependency_no_site_is_blocked_by_its_own_dependent(tmp_path):
    # Direct exercise of _compute_unsafe_sites over the exact reported
    # graph, independent of fixgen.run()'s surrounding machinery: 10 and
    # 25 must never appear as unsafe, since nothing they depend on is
    # unsafe -- only what depends on THEM is.
    sites_by_key = {
        ("main.py", 10): {"role": "proposed", "site": {"related_sites": []}},
        ("main.py", 25): {"role": "proposed", "site": {"related_sites": [{"file": "main.py", "line": 10}]}},
        ("main.py", 27): {"role": "proposed", "site": {"related_sites": [{"file": "main.py", "line": 10}]}},
        ("main.py", 70): {"role": "uncertain", "site": {"related_sites": [
            {"file": "main.py", "line": 27}, {"file": "main.py", "line": 25},
        ]}},
    }
    depends_on = fixgen._direct_dependencies(sites_by_key)
    self_unsafe = {("main.py", 70), ("main.py", 27)}  # uncertain, and span-declined respectively
    unsafe_cause = fixgen._compute_unsafe_sites(sites_by_key.keys(), depends_on, self_unsafe)

    assert ("main.py", 10) not in unsafe_cause
    assert ("main.py", 25) not in unsafe_cause
    assert unsafe_cause[("main.py", 27)] == ("main.py", 27)
    assert unsafe_cause[("main.py", 70)] == ("main.py", 70)


def test_directional_dependency_transitive_chain_still_blocks_forward(tmp_path):
    # A depends on B depends on C(uncertain) -- A must still be blocked,
    # transitively, since blocking DOES flow forward along a dependency
    # chain; only the reverse direction (a dependent blocking its
    # dependency) is what got fixed.
    sites_by_key = {
        ("a.py", 1): {"role": "proposed", "site": {"related_sites": [{"file": "a.py", "line": 2}]}},
        ("a.py", 2): {"role": "proposed", "site": {"related_sites": [{"file": "a.py", "line": 3}]}},
        ("a.py", 3): {"role": "uncertain", "site": {"related_sites": []}},
    }
    depends_on = fixgen._direct_dependencies(sites_by_key)
    unsafe_cause = fixgen._compute_unsafe_sites(sites_by_key.keys(), depends_on, {("a.py", 3)})

    assert unsafe_cause[("a.py", 1)] == ("a.py", 2)
    assert unsafe_cause[("a.py", 2)] == ("a.py", 3)
    assert unsafe_cause[("a.py", 3)] == ("a.py", 3)


def test_describe_unsafe_cause_names_the_concrete_base_reason():
    sites_by_key = {
        ("a.py", 1): {"role": "proposed", "site": {}},
        ("a.py", 2): {"role": "proposed", "site": {}},
        ("a.py", 3): {"role": "uncertain", "site": {}},
    }
    unsafe_cause = {("a.py", 1): ("a.py", 2), ("a.py", 2): ("a.py", 3), ("a.py", 3): ("a.py", 3)}
    reason = fixgen._describe_unsafe_cause(("a.py", 1), unsafe_cause, sites_by_key,
                                            span_map={}, mutual_partners={})
    assert "a.py:2" in reason
    assert "a.py:3" in reason
    assert "not confirmed by adjudication" in reason


def test_check_no_fix_depends_on_an_unresolved_site_passes_when_all_deps_fixed():
    depends_on = {("a.py", 1): [], ("a.py", 2): [("a.py", 1)]}
    merged_bucketed = {("a.py", 1): "fixes", ("a.py", 2): "fixes"}
    fixgen._check_no_fix_depends_on_an_unresolved_site(merged_bucketed, depends_on, what="test")


def test_check_no_fix_depends_on_an_unresolved_site_raises_when_dependency_unfixed():
    depends_on = {("a.py", 1): [], ("a.py", 2): [("a.py", 1)]}
    merged_bucketed = {("a.py", 1): "flagged_for_human", ("a.py", 2): "fixes"}
    with pytest.raises(ValueError, match="split across buckets"):
        fixgen._check_no_fix_depends_on_an_unresolved_site(merged_bucketed, depends_on, what="test")


def test_check_no_fix_depends_on_an_unresolved_site_passes_when_dependent_alone_is_unfixed():
    # The directional half of the fix: a FIX (1) whose dependent (2) was
    # not also fixed is fine -- only the reverse (a fix depending on an
    # unfixed site) is the real problem.
    depends_on = {("a.py", 1): [], ("a.py", 2): [("a.py", 1)]}
    merged_bucketed = {("a.py", 1): "fixes", ("a.py", 2): "flagged_for_human"}
    fixgen._check_no_fix_depends_on_an_unresolved_site(merged_bucketed, depends_on, what="test")


# ---------------------------------------------------------------------
# _demote_dependents_of_unresolved_sites -- the run-wide fallback that
# replaced aborting the whole run over one torn coupled pair.
# ---------------------------------------------------------------------

def _fix(f, l):
    return {"file": f, "line": l, "end_line": l, "original_lines": ["x"],
            "proposed_lines": ["y"], "reason": "r"}


def _flag(f, l, **extra):
    return {"file": f, "line": l, "reason": "r", **extra}


def test_demote_moves_only_the_dependent_fix_leaving_its_dependency_alone():
    merged = {
        "fixes": [_fix("a.py", 1)],
        "flagged_for_human": [_flag("a.py", 2, flag_source="model_declined")],
    }
    depends_on = {("a.py", 1): [("a.py", 2)], ("a.py", 2): []}
    sites_by_key = {
        ("a.py", 1): {"role": "proposed", "site": {"reason": "r"}},
        ("a.py", 2): {"role": "proposed", "site": {"reason": "r"}},
    }
    group_id_by_key = {("a.py", 1): "a.py:1", ("a.py", 2): "a.py:1"}
    group_members_by_id = {"a.py:1": [("a.py", 1), ("a.py", 2)]}

    fixgen._demote_dependents_of_unresolved_sites(
        merged, depends_on, group_id_by_key, group_members_by_id, sites_by_key,
    )

    assert merged["fixes"] == []
    assert len(merged["flagged_for_human"]) == 2
    by_line = {f["line"]: f for f in merged["flagged_for_human"]}
    assert by_line[1]["flag_source"] == "unresolved_dependency_guard"
    assert by_line[1]["group_id"] == "a.py:1"
    assert by_line[2]["flag_source"] == "model_declined"  # untouched


def test_demote_does_not_touch_an_unrelated_fix():
    merged = {
        "fixes": [_fix("a.py", 1), _fix("a.py", 3)],
        "flagged_for_human": [_flag("a.py", 2, flag_source="model_declined")],
    }
    depends_on = {("a.py", 1): [("a.py", 2)], ("a.py", 2): [], ("a.py", 3): []}
    sites_by_key = {k: {"role": "proposed", "site": {"reason": "r"}}
                     for k in [("a.py", 1), ("a.py", 2), ("a.py", 3)]}
    group_id_by_key = {("a.py", 1): "a.py:1", ("a.py", 2): "a.py:1"}
    group_members_by_id = {"a.py:1": [("a.py", 1), ("a.py", 2)]}

    fixgen._demote_dependents_of_unresolved_sites(
        merged, depends_on, group_id_by_key, group_members_by_id, sites_by_key,
    )

    assert [f["line"] for f in merged["fixes"]] == [3]


def test_demote_cascades_through_a_transitive_chain():
    # A depends on B depends on C. C never shipped as a fix (it's flagged),
    # so B must demote -- and once B is no longer a fix, A (which depends
    # on B) must demote too, in the same call, not require a second pass
    # from the caller.
    merged = {
        "fixes": [_fix("a.py", 1), _fix("a.py", 2)],
        "flagged_for_human": [_flag("a.py", 3, flag_source="model_declined")],
    }
    depends_on = {
        ("a.py", 1): [("a.py", 2)],
        ("a.py", 2): [("a.py", 3)],
        ("a.py", 3): [],
    }
    sites_by_key = {k: {"role": "proposed", "site": {"reason": "r"}}
                     for k in [("a.py", 1), ("a.py", 2), ("a.py", 3)]}
    group_id_by_key = {k: "a.py:1" for k in [("a.py", 1), ("a.py", 2), ("a.py", 3)]}
    group_members_by_id = {"a.py:1": [("a.py", 1), ("a.py", 2), ("a.py", 3)]}

    fixgen._demote_dependents_of_unresolved_sites(
        merged, depends_on, group_id_by_key, group_members_by_id, sites_by_key,
    )

    assert merged["fixes"] == []
    by_line = {f["line"]: f for f in merged["flagged_for_human"]}
    assert by_line[1]["flag_source"] == "unresolved_dependency_guard"
    assert by_line[2]["flag_source"] == "unresolved_dependency_guard"
    assert by_line[3]["flag_source"] == "model_declined"


def test_demote_is_a_noop_when_every_dependency_is_also_a_fix():
    merged = {"fixes": [_fix("a.py", 1), _fix("a.py", 2)], "flagged_for_human": []}
    depends_on = {("a.py", 1): [("a.py", 2)], ("a.py", 2): []}
    sites_by_key = {k: {"role": "proposed", "site": {"reason": "r"}}
                     for k in [("a.py", 1), ("a.py", 2)]}
    group_id_by_key = {("a.py", 1): "a.py:1", ("a.py", 2): "a.py:1"}
    group_members_by_id = {"a.py:1": [("a.py", 1), ("a.py", 2)]}

    fixgen._demote_dependents_of_unresolved_sites(
        merged, depends_on, group_id_by_key, group_members_by_id, sites_by_key,
    )

    assert {f["line"] for f in merged["fixes"]} == {1, 2}
    assert merged["flagged_for_human"] == []


# ---------------------------------------------------------------------
# Mutual (backwards) related_sites -- _detect_mutual_dependencies and the
# mutual_dependency_guard it feeds. related_sites is specified as one-way
# (adjudication_system.md: "this relation runs ONE way"), so an edge
# present in BOTH directions between the same two sites is always a
# contradiction to a directed reader, even though it cannot say which end
# is wrong. The real case this is grounded in: run-azeroth-joint's
# adjudication output (both the -coupled and -joint reruns) has
# main.py:68 (the FastMCP constructor) list 153 and 170 in ITS OWN
# related_sites, while 153 and 170 correctly list 68 in theirs --
#
#   29  -> [68]            (import, correctly depends on the constructor)
#   68  -> [29, 153, 170]  (constructor -- WRONG: also claims to depend
#                            on its own downstream call sites)
#   153 -> [68]             (correct: needs the constructor's args)
#   170 -> [68]             (correct: needs the constructor's args)
#
# Every edge touching 68 is therefore a real 2-cycle in the stored data,
# not a one-sided backward link -- see the fixture below, taken directly
# from run-azeroth-joint/adjudication/merged.json.
# ---------------------------------------------------------------------

def test_detect_mutual_dependencies_finds_a_reciprocal_pair():
    depends_on = {("a.py", 1): [("a.py", 2)], ("a.py", 2): [("a.py", 1)]}
    assert fixgen._detect_mutual_dependencies(depends_on) == [(("a.py", 1), ("a.py", 2))]


def test_detect_mutual_dependencies_ignores_a_one_directional_edge():
    # A depends on B; B depends on nothing. No contradiction -- this is
    # the ordinary, overwhelmingly common shape (youtrack-directional's
    # 25 -> [10], 27 -> [10], with 10 -> [] and nothing pointing back).
    depends_on = {("a.py", 1): [("a.py", 2)], ("a.py", 2): []}
    assert fixgen._detect_mutual_dependencies(depends_on) == []


def test_detect_mutual_dependencies_ignores_a_self_loop():
    # A site naming itself is a different (degenerate) defect, not a
    # mutual-PAIR contradiction -- this function has nothing to say about it.
    depends_on = {("a.py", 1): [("a.py", 1)]}
    assert fixgen._detect_mutual_dependencies(depends_on) == []


def test_detect_mutual_dependencies_reports_each_pair_once_regardless_of_iteration_order():
    depends_on = {("a.py", 1): [("a.py", 2)], ("a.py", 2): [("a.py", 1)]}
    pairs = fixgen._detect_mutual_dependencies(depends_on)
    assert len(pairs) == 1
    a, b = pairs[0]
    assert (a, b) == (("a.py", 1), ("a.py", 2))  # canonical sorted order, not insertion order


def test_detect_mutual_dependencies_matches_the_real_azeroth_joint_shape():
    # Verbatim from run-azeroth-joint/adjudication/merged.json (and
    # reproduced identically in run-azeroth-coupled): this is NOT a
    # one-sided backward link -- 68's own related_sites reciprocates both
    # 153's and 170's (correct) edges back at them, and 29's (also
    # correct) edge back at it too. A mutual-pair check finds all three.
    depends_on = {
        ("main.py", 29): [("main.py", 68)],
        ("main.py", 68): [("main.py", 29), ("main.py", 153), ("main.py", 170)],
        ("main.py", 153): [("main.py", 68)],
        ("main.py", 170): [("main.py", 68)],
    }
    pairs = fixgen._detect_mutual_dependencies(depends_on)
    assert pairs == [
        (("main.py", 29), ("main.py", 68)),
        (("main.py", 68), ("main.py", 153)),
        (("main.py", 68), ("main.py", 170)),
    ]


def test_detect_mutual_dependencies_finds_nothing_on_the_real_youtrack_directional_shape():
    # Verbatim from run-youtrack-directional/adjudication/merged.json,
    # the correctly-directional counterpart: no pair here contradicts
    # itself, so the guard must not fire on it -- a clean directed graph
    # produces zero false positives.
    depends_on = {
        ("main.py", 10): [],
        ("main.py", 25): [("main.py", 10)],
        ("main.py", 27): [("main.py", 10)],
        ("main.py", 70): [("main.py", 27), ("main.py", 25)],
    }
    assert fixgen._detect_mutual_dependencies(depends_on) == []


def test_describe_unsafe_cause_names_the_mutual_dependency_reason():
    sites_by_key = {
        ("a.py", 1): {"role": "proposed", "site": {}},
        ("a.py", 2): {"role": "proposed", "site": {}},
    }
    unsafe_cause = {("a.py", 1): ("a.py", 1), ("a.py", 2): ("a.py", 2)}
    mutual_partners = {("a.py", 1): [("a.py", 2)], ("a.py", 2): [("a.py", 1)]}
    reason = fixgen._describe_unsafe_cause(("a.py", 1), unsafe_cause, sites_by_key,
                                            span_map={}, mutual_partners=mutual_partners)
    assert "a.py:1" in reason and "a.py:2" in reason
    assert "name each other" in reason
    # Must NOT fall through to the generic/uncertain-role wording -- that
    # would misreport a self-contradictory pair as an ordinary decline.
    assert "not confirmed by adjudication" not in reason
    assert "was not resolved by a coordinated fix" not in reason


def test_mutual_dependency_guard_declines_both_confident_sites_without_a_model_call(tmp_path):
    # The real new coverage this guard adds: two ordinary PROPOSED sites
    # (no uncertain role, no multi-line span -- nothing else would ever
    # catch this) whose related_sites contradict each other. Before this
    # guard, both would have reached the model as an unremarkable ordinary
    # chunk, no consistency signal anywhere -- see run()'s docstring.
    body = "x = 1\ny = 2\n"
    reader = _make_repo(tmp_path, body=body)
    proposed = [
        {"file": "main.py", "line": 1, "snippet": "x = 1", "pattern": "1", "reason": "r1",
         "related_sites": [{"file": "main.py", "line": 2}]},
        {"file": "main.py", "line": 2, "snippet": "y = 2", "pattern": "1", "reason": "r2",
         "related_sites": [{"file": "main.py", "line": 1}]},  # reciprocates -- the contradiction
    ]
    client = FakeLLMClient([])  # never called -- IndexError if it were
    merged = fixgen.run(client, reader, proposed, FACTBLOCK, str(tmp_path / "wd"), chunk_size=40)

    assert client.calls == []
    assert merged["fixes"] == []
    flagged_lines = {f["line"] for f in merged["flagged_for_human"]}
    assert flagged_lines == {1, 2}
    for flag in merged["flagged_for_human"]:
        assert flag["flag_source"] == "group_consistency_guard"
        assert "name each other in related_sites" in flag["reason"]

    assert len(merged["mutual_dependency_warnings"]) == 1
    warning = merged["mutual_dependency_warnings"][0]
    warned_keys = {(s["file"], s["line"]) for s in warning["sites"]}
    assert warned_keys == {("main.py", 1), ("main.py", 2)}


def test_mutual_dependency_warnings_empty_when_no_pair_contradicts(tmp_path):
    reader = _make_repo(tmp_path, body="import old_pkg\n")
    proposed = [{"file": "main.py", "line": 1, "snippet": "import old_pkg", "pattern": "1",
                 "reason": "import rename", "related_sites": []}]
    response = {
        "fixes": [{"file": "main.py", "line": 1, "end_line": 1,
                   "original_lines": ["import old_pkg"], "proposed_lines": ["import new_pkg"],
                   "reason": "renamed"}],
        "flagged_for_human": [],
    }
    client = FakeLLMClient([response])
    merged = fixgen.run(client, reader, proposed, FACTBLOCK, str(tmp_path / "wd"), chunk_size=40)

    assert merged["mutual_dependency_warnings"] == []


# ---------------------------------------------------------------------
# Solo span groups -- _add_singleton_span_groups. Joint-resolution
# eligibility used to be a property of HAVING a related_sites edge, not
# of BEING span-guarded: a span-guarded site reached _run_joint_group only
# if adjudication happened to link it to a companion. On real run data
# (run-secops, run-youtrack) two essentially identical span-guarded
# constructors got different treatment for a reason that had nothing to
# do with either site's own shape -- one had an edge, the other didn't.
# This gives every span-guarded, ungrouped PROPOSED site its own
# synthetic one-member group so the EXISTING group_class pass (which
# already treats any group with a span member and no uncertain member as
# "joint_resolve", regardless of size) picks it up too, with no changes
# to that pass itself.
# ---------------------------------------------------------------------

def test_add_singleton_span_groups_creates_a_group_for_an_ungrouped_span_site():
    sites_by_key = {("a.py", 5): {"role": "proposed", "site": {"related_sites": []}}}
    span_map = {("a.py", 5): (5, 9)}
    group_id_by_key, group_members_by_id = fixgen._add_singleton_span_groups(
        {}, {}, sites_by_key, span_map,
    )
    assert group_id_by_key == {("a.py", 5): "a.py:5"}
    assert group_members_by_id == {"a.py:5": [("a.py", 5)]}


def test_add_singleton_span_groups_leaves_an_already_grouped_span_site_untouched():
    # A span site that already has a real (>=2-member) group via
    # related_sites must not get a second, synthetic one -- its existing
    # group_id/members are the ones the classification pass sees.
    sites_by_key = {
        ("a.py", 5): {"role": "proposed", "site": {"related_sites": []}},
        ("a.py", 20): {"role": "proposed", "site": {"related_sites": []}},
    }
    span_map = {("a.py", 5): (5, 9)}
    existing_id_by_key = {("a.py", 5): "a.py:20", ("a.py", 20): "a.py:20"}
    existing_members_by_id = {"a.py:20": [("a.py", 5), ("a.py", 20)]}
    group_id_by_key, group_members_by_id = fixgen._add_singleton_span_groups(
        existing_id_by_key, existing_members_by_id, sites_by_key, span_map,
    )
    assert group_id_by_key == existing_id_by_key
    assert group_members_by_id == existing_members_by_id


def test_add_singleton_span_groups_ignores_a_non_span_site():
    sites_by_key = {("a.py", 5): {"role": "proposed", "site": {"related_sites": []}}}
    group_id_by_key, group_members_by_id = fixgen._add_singleton_span_groups(
        {}, {}, sites_by_key, {},  # span_map empty -- (a.py, 5) is not span-guarded
    )
    assert group_id_by_key == {}
    assert group_members_by_id == {}


def test_add_singleton_span_groups_keeps_independent_lone_spans_separate():
    # Two unrelated lone span sites must get two DIFFERENT synthetic
    # groups, never merged into one just because both needed one.
    sites_by_key = {
        ("a.py", 5): {"role": "proposed", "site": {"related_sites": []}},
        ("b.py", 40): {"role": "proposed", "site": {"related_sites": []}},
    }
    span_map = {("a.py", 5): (5, 9), ("b.py", 40): (40, 42)}
    group_id_by_key, group_members_by_id = fixgen._add_singleton_span_groups(
        {}, {}, sites_by_key, span_map,
    )
    assert group_id_by_key == {("a.py", 5): "a.py:5", ("b.py", 40): "b.py:40"}
    assert group_members_by_id == {"a.py:5": [("a.py", 5)], "b.py:40": [("b.py", 40)]}


def test_add_singleton_span_groups_does_not_mutate_its_inputs():
    orig_id_by_key = {}
    orig_members_by_id = {}
    sites_by_key = {("a.py", 5): {"role": "proposed", "site": {"related_sites": []}}}
    span_map = {("a.py", 5): (5, 9)}
    fixgen._add_singleton_span_groups(orig_id_by_key, orig_members_by_id, sites_by_key, span_map)
    assert orig_id_by_key == {}
    assert orig_members_by_id == {}


# ---------------------------------------------------------------------
# _add_singleton_span_groups -- grouping ungrouped span-guarded sites by
# span OVERLAP/CONTAINMENT, not one synthetic group per site. Real-run
# failure (Pydantic v1->v2, 229 proposed sites): align/pdk/finfet/
# digital.py lines 48 and 50 both fall inside one enclosing statement
# (48-50), with no related_sites edge between them -- each got its own
# solo joint call, each produced a fix for the whole shared statement, and
# the two overlapped at apply time. See _resolve_overlapping_fixes below
# for the merge-time backstop this composes with.
# ---------------------------------------------------------------------

def test_add_singleton_span_groups_merges_two_sites_in_the_same_enclosing_statement():
    # _multiline_spans gives every line of ONE statement the exact same
    # (start, end) tuple -- the digital.py 48/50 shape reproduced directly:
    # two keys, identical spans, no related_sites edge.
    sites_by_key = {
        ("digital.py", 48): {"role": "proposed", "site": {"related_sites": []}},
        ("digital.py", 50): {"role": "proposed", "site": {"related_sites": []}},
    }
    span_map = {("digital.py", 48): (48, 50), ("digital.py", 50): (48, 50)}
    group_id_by_key, group_members_by_id = fixgen._add_singleton_span_groups(
        {}, {}, sites_by_key, span_map,
    )
    assert group_id_by_key == {
        ("digital.py", 48): "digital.py:48",
        ("digital.py", 50): "digital.py:48",
    }
    assert group_members_by_id == {
        "digital.py:48": [("digital.py", 48), ("digital.py", 50)],
    }


def test_add_singleton_span_groups_merges_a_contained_span_not_just_an_equal_one():
    # A different shape than digital.py's -- an outer statement's span
    # doesn't equal the inner (nested) statement's tighter span, but one
    # contains the other. Must still merge into one group: a joint call
    # for the outer alone would still be free to rewrite the inner's lines
    # with no visibility into the inner's own separate resolution.
    sites_by_key = {
        ("a.py", 10): {"role": "proposed", "site": {"related_sites": []}},
        ("a.py", 13): {"role": "proposed", "site": {"related_sites": []}},
    }
    span_map = {("a.py", 10): (10, 20), ("a.py", 13): (12, 14)}
    group_id_by_key, group_members_by_id = fixgen._add_singleton_span_groups(
        {}, {}, sites_by_key, span_map,
    )
    assert group_id_by_key == {("a.py", 10): "a.py:10", ("a.py", 13): "a.py:10"}
    assert group_members_by_id == {"a.py:10": [("a.py", 10), ("a.py", 13)]}


def test_add_singleton_span_groups_merges_a_three_way_overlap_chain():
    # A overlaps B, B overlaps C, A does NOT overlap C directly -- must
    # still land in ONE group via transitive union, not two.
    sites_by_key = {k: {"role": "proposed", "site": {"related_sites": []}}
                     for k in [("a.py", 1), ("a.py", 2), ("a.py", 3)]}
    span_map = {("a.py", 1): (1, 5), ("a.py", 2): (4, 8), ("a.py", 3): (7, 10)}
    group_id_by_key, group_members_by_id = fixgen._add_singleton_span_groups(
        {}, {}, sites_by_key, span_map,
    )
    gid = group_id_by_key[("a.py", 1)]
    assert group_id_by_key == {("a.py", 1): gid, ("a.py", 2): gid, ("a.py", 3): gid}
    assert group_members_by_id[gid] == [("a.py", 1), ("a.py", 2), ("a.py", 3)]


def test_add_singleton_span_groups_does_not_merge_across_files():
    # Numerically overlapping line ranges in DIFFERENT files must never be
    # treated as the same statement.
    sites_by_key = {
        ("a.py", 5): {"role": "proposed", "site": {"related_sites": []}},
        ("b.py", 5): {"role": "proposed", "site": {"related_sites": []}},
    }
    span_map = {("a.py", 5): (5, 9), ("b.py", 5): (5, 9)}
    group_id_by_key, group_members_by_id = fixgen._add_singleton_span_groups(
        {}, {}, sites_by_key, span_map,
    )
    assert group_id_by_key == {("a.py", 5): "a.py:5", ("b.py", 5): "b.py:5"}


def test_digital_py_48_50_shape_reaches_one_joint_call_not_two(tmp_path):
    # End-to-end reproduction of the reported real-run shape: one enclosing
    # statement spanning lines 48-50, two confirmed sites inside it (48 and
    # 50), zero related_sites edges. Before this fix: two solo calls. Now:
    # one joint call over both members.
    body = "\n".join(f"x{i} = {i}" for i in range(1, 48)) + "\n"
    body += "result = foo(\n    bar,\n)\n"  # lines 48, 49, 50
    reader = _make_repo(tmp_path, filename="align/pdk/finfet/digital.py", body=body)
    proposed = [
        {"file": "align/pdk/finfet/digital.py", "line": 48, "snippet": "result = foo(",
         "pattern": "1", "reason": "renamed call", "related_sites": []},
        {"file": "align/pdk/finfet/digital.py", "line": 50, "snippet": ")",
         "pattern": "1", "reason": "renamed call, closing paren", "related_sites": []},
    ]
    response = {
        "fixes": [
            {"file": "align/pdk/finfet/digital.py", "line": 48, "end_line": 50,
             "original_lines": ["result = foo(", "    bar,", ")"],
             "proposed_lines": ["result = baz(", "    bar,", ")"], "reason": "renamed"},
            {"file": "align/pdk/finfet/digital.py", "line": 50, "end_line": 50,
             "original_lines": [")"], "proposed_lines": [")"], "reason": "no change needed here"},
        ],
        "flagged_for_human": [],
    }
    client = FakeLLMClient([response])
    merged = fixgen.run(client, reader, proposed, FACTBLOCK, str(tmp_path / "wd"), chunk_size=40)

    assert len(client.calls) == 1
    assert client.calls[0]["stage"] == "fixgen_group_align_pdk_finfet_digital.py_48"


# ---------------------------------------------------------------------
# End-to-end: all three group kinds in ONE run, proving the new solo path
# doesn't disturb the other two. Reuses AZEROTH_JOINT_BODY's shape for the
# multi-member cases (already-verified fixtures from the section above)
# plus a lone span site with no related_sites at all.
# ---------------------------------------------------------------------

_MIXED_BODY = (
    "import os\n"                        # line 1
    "\n"                                 # line 2
    "mcp = FastMCP(\n"                   # line 3 -- multi-member joint_resolve anchor
    "    \"name\",\n"                    # line 4
    "    host=host,\n"                   # line 5
    "    port=port\n"                    # line 6
    ")\n"                                # line 7
    "\n"                                 # line 8
    "if __name__ == \"__main__\":\n"     # line 9
    "    mcp.run(transport=\"sse\")\n"   # line 10
    "\n"                                 # line 11
    "other = OtherThing(\n"              # line 12 -- lone span site, no group at all
    "    \"solo\",\n"                    # line 13
    "    x=x,\n"                         # line 14
    ")\n"                                # line 15
)


def test_solo_multi_and_uncertain_groups_coexist_without_interference(tmp_path):
    reader = _make_repo(tmp_path, body=_MIXED_BODY)
    proposed = [
        # multi-member joint_resolve group (main.py:10 depends on main.py:3
        # -- one-directional on purpose, same reasoning as the mutual-pair
        # fixtures elsewhere in this file: reciprocating it would make this
        # pair a mutual-dependency contradiction instead, a different case).
        {"file": "main.py", "line": 3, "snippet": "mcp = FastMCP(", "pattern": "1",
         "reason": "constructor referencing FastMCP", "related_sites": []},
        {"file": "main.py", "line": 10, "snippet": "    mcp.run(transport=\"sse\")", "pattern": "1",
         "reason": "host/port formerly given to the constructor must now be passed here",
         "related_sites": [{"file": "main.py", "line": 3}]},
        # lone span site, no related_sites, no group at all
        {"file": "main.py", "line": 12, "snippet": "other = OtherThing(", "pattern": "1",
         "reason": "constructor of another renamed class", "related_sites": []},
    ]
    joint_success = {
        "fixes": [
            {"file": "main.py", "line": 3, "end_line": 7,
             "original_lines": ["mcp = FastMCP(", "    \"name\",", "    host=host,", "    port=port", ")"],
             "proposed_lines": ["mcp = FastMCP(", "    \"name\",", ")"],
             "reason": "moved host/port"},
            {"file": "main.py", "line": 10, "end_line": 10,
             "original_lines": ["    mcp.run(transport=\"sse\")"],
             "proposed_lines": ["    mcp.run(transport=\"sse\", host=host, port=port)"],
             "reason": "received host/port"},
        ],
        "flagged_for_human": [],
    }
    solo_success = {
        "fixes": [{"file": "main.py", "line": 12, "end_line": 15,
                   "original_lines": ["other = OtherThing(", "    \"solo\",", "    x=x,", ")"],
                   "proposed_lines": ["other = NewThing(", "    \"solo\",", "    x=x,", ")"],
                   "reason": "renamed, keyword arg unchanged"}],
        "flagged_for_human": [],
    }
    # Pass 2 runs joint gids in sorted order: "main.py:12" (solo) < "main.py:3" (multi).
    client = FakeLLMClient([solo_success, joint_success])
    merged = fixgen.run(client, reader, proposed, FACTBLOCK, str(tmp_path / "wd"), chunk_size=40)

    assert merged["flagged_for_human"] == []
    fixed_lines = {f["line"] for f in merged["fixes"]}
    assert fixed_lines == {3, 10, 12}
    solo_fix = next(f for f in merged["fixes"] if f["line"] == 12)
    assert solo_fix["group_id"] == "main.py:12"
    multi_fix = next(f for f in merged["fixes"] if f["line"] == 3)
    assert multi_fix["group_id"] == "main.py:3"
    stages = {c["stage"] for c in client.calls}
    assert stages == {"fixgen_group_main.py_12", "fixgen_group_main.py_3"}
    assert merged["mutual_dependency_warnings"] == []


def test_solo_span_group_still_declines_when_ITS_OWN_edge_reaches_uncertain(tmp_path):
    # The legitimate uncertain_decline case, not the run-youtrack-solo bug:
    # here site 12 (span-guarded, PROPOSED) names 20 (uncertain) as ITS OWN
    # dependency -- 12's own correctness genuinely depends on unconfirmed
    # content, the mirror of the bug case where an uncertain site named a
    # self-contained span site as ITS dependency. _resolution_groups counts
    # a PROPOSED site's own edges, so this one still unions {12, 20} in the
    # RESOLUTION view, group_class still reads "uncertain_decline" for it,
    # and 12 still declines immediately via Pass 1's span flag, with no
    # model call -- has_uncertain (via a real, directional dependency) still
    # wins over "has a span member", exactly as intended.
    reader = _make_repo(tmp_path, body=_MIXED_BODY)
    proposed = [{"file": "main.py", "line": 12, "snippet": "other = OtherThing(", "pattern": "1",
                 "reason": "constructor of another renamed class",
                 "related_sites": [{"file": "main.py", "line": 20}]}]
    uncertain = [{"file": "main.py", "line": 20, "snippet": "whatever(x)",
                  "reason": "constructor args at line 12 unclear", "related_sites": []}]
    client = FakeLLMClient([])  # never called -- IndexError if it were
    merged = fixgen.run(client, reader, proposed, FACTBLOCK, str(tmp_path / "wd"),
                         uncertain_sites=uncertain, chunk_size=40)

    assert client.calls == []
    assert merged["fixes"] == []
    flag = merged["flagged_for_human"][0]
    assert flag["line"] == 12
    assert flag["flag_source"] == "multiline_span_guard"
    member_keys = {(m["file"], m["line"]) for m in flag["group_members"]}
    assert member_keys == {("main.py", 12), ("main.py", 20)}


def test_solo_span_group_reaches_solo_call_when_only_an_uncertain_dependent_names_it(tmp_path):
    # The run-youtrack-solo bug shape, isolated: site 12 (span-guarded,
    # PROPOSED) has EMPTY related_sites of its own; only an UNCERTAIN
    # sibling (20) names 12 as ITS dependency (the reverse direction from
    # the test above). Since _resolution_groups only counts edges a
    # PROPOSED site declares, this contributes no RESOLUTION edge at all,
    # so 12 gets its own synthetic solo group and reaches a real call --
    # it must NOT be swept into uncertain_decline purely because something
    # depends on it.
    reader = _make_repo(tmp_path, body=_MIXED_BODY)
    proposed = [{"file": "main.py", "line": 12, "snippet": "other = OtherThing(", "pattern": "1",
                 "reason": "constructor of another renamed class", "related_sites": []}]
    uncertain = [{"file": "main.py", "line": 20, "snippet": "whatever(x)",
                  "reason": "depends on line 12's constructor args",
                  "related_sites": [{"file": "main.py", "line": 12}]}]
    response = {"fixes": [{"file": "main.py", "line": 12, "end_line": 15,
                            "original_lines": ["other = OtherThing(", "    \"solo\",", "    x=x,", ")"],
                            "proposed_lines": ["other = NewThing(", "    \"solo\",", "    x=x,", ")"],
                            "reason": "renamed, keyword arg unchanged"}],
                "flagged_for_human": []}
    client = FakeLLMClient([response])
    merged = fixgen.run(client, reader, proposed, FACTBLOCK, str(tmp_path / "wd"),
                         uncertain_sites=uncertain, chunk_size=40)

    assert merged["flagged_for_human"] == []
    assert len(merged["fixes"]) == 1
    assert merged["fixes"][0]["line"] == 12
    assert client.calls[0]["stage"] == "fixgen_group_main.py_12"
    # The fix still shows the full VISIBILITY neighborhood (20 depends on
    # it), even though 20 was never sent to the model.
    assert merged["fixes"][0]["group_id"] == "main.py:12"


# ---------------------------------------------------------------------
# _resolve_overlapping_fixes -- the merge-time backstop for whatever
# _add_singleton_span_groups' own grouping fix doesn't happen to catch (or
# a joint call still resolves inconsistently despite being grouped): two
# overlapping fixes are deduped if they provably agree, or declined
# together if they don't -- never an abort. Real-run shape: a 229-fix
# Pydantic run was blocked ENTIRELY by one overlapping pair.
# ---------------------------------------------------------------------

def _overlap_fix(f, l, end, orig, prop, **extra):
    return {"file": f, "line": l, "end_line": end, "original_lines": orig,
            "proposed_lines": prop, "reason": "r", **extra}


def test_resolve_overlapping_fixes_is_a_noop_with_no_overlap():
    merged = {
        "fixes": [_overlap_fix("a.py", 1, 1, ["x"], ["y"]),
                  _overlap_fix("a.py", 5, 5, ["p"], ["q"])],
        "flagged_for_human": [],
    }
    fixgen._resolve_overlapping_fixes(merged, {}, {})
    assert len(merged["fixes"]) == 2
    assert merged["flagged_for_human"] == []
    assert merged["duplicate_fixes_dropped"] == []


def test_resolve_overlapping_fixes_drops_an_identical_contained_duplicate():
    # The exact digital.py 48/50 shape: both fixes cover the same 48-50
    # statement, one keyed at 48 (the full span) and one keyed at 50 (also
    # claiming the full span) -- equal spans, identical proposed content.
    outer = _overlap_fix("digital.py", 48, 50,
                          ["result = foo(", "    bar,", ")"],
                          ["result = baz(", "    bar,", ")"])
    inner = _overlap_fix("digital.py", 48, 50,
                          ["result = foo(", "    bar,", ")"],
                          ["result = baz(", "    bar,", ")"])
    merged = {"fixes": [outer, inner], "flagged_for_human": []}

    fixgen._resolve_overlapping_fixes(merged, {}, {})

    assert len(merged["fixes"]) == 1
    assert merged["flagged_for_human"] == []
    assert len(merged["duplicate_fixes_dropped"]) == 1
    dropped = merged["duplicate_fixes_dropped"][0]
    assert dropped["kept"]["line"] == 48
    assert dropped["dropped"]["line"] == 48  # same key -- equal spans, arbitrary pick


def test_resolve_overlapping_fixes_drops_a_genuinely_contained_duplicate():
    # A real containment case, not just equal spans: the smaller fix's
    # span nests inside the larger one, and the larger one's own
    # replacement is proven to already say the same thing at that offset.
    outer = _overlap_fix("a.py", 10, 12,
                          ["one", "two", "three"], ["ONE", "TWO", "THREE"])
    inner = _overlap_fix("a.py", 11, 11, ["two"], ["TWO"])
    merged = {"fixes": [outer, inner], "flagged_for_human": []}

    fixgen._resolve_overlapping_fixes(merged, {}, {})

    assert merged["fixes"] == [outer]
    assert len(merged["duplicate_fixes_dropped"]) == 1
    assert merged["duplicate_fixes_dropped"][0]["dropped"]["line"] == 11


def test_resolve_overlapping_fixes_declines_a_real_conflict_together():
    a = _overlap_fix("a.py", 5, 7, ["x", "y", "z"], ["X", "Y", "Z"])
    b = _overlap_fix("a.py", 6, 6, ["y"], ["DIFFERENT"])  # disagrees with a's own "Y"
    merged = {"fixes": [a, b], "flagged_for_human": []}
    sites_by_key = {("a.py", 5): {"role": "proposed", "site": {"reason": "r"}},
                     ("a.py", 6): {"role": "proposed", "site": {"reason": "r"}}}

    fixgen._resolve_overlapping_fixes(merged, {}, sites_by_key)

    assert merged["fixes"] == []
    assert len(merged["flagged_for_human"]) == 2
    by_line = {f["line"]: f for f in merged["flagged_for_human"]}
    assert by_line[5]["flag_source"] == "overlap_conflict_guard"
    assert by_line[6]["flag_source"] == "overlap_conflict_guard"
    assert by_line[5]["group_id"] == by_line[6]["group_id"]
    assert merged["duplicate_fixes_dropped"] == []


def test_resolve_overlapping_fixes_conflict_declines_the_whole_pre_existing_group():
    # a and b already share a real group_id (e.g. from a 3-member joint
    # call) and disagree where they overlap -- the THIRD member (c, no
    # overlap of its own) must be declined too, not left shipped as a fix:
    # tearing the group here is the exact insufficient-fix-set shape the
    # coupling guard exists to prevent.
    a = _overlap_fix("a.py", 5, 7, ["x", "y", "z"], ["X", "Y", "Z"], group_id="a.py:5")
    b = _overlap_fix("a.py", 6, 6, ["y"], ["DIFFERENT"], group_id="a.py:5")
    c = _overlap_fix("a.py", 20, 20, ["w"], ["W"], group_id="a.py:5")
    merged = {"fixes": [a, b, c], "flagged_for_human": []}
    sites_by_key = {k: {"role": "proposed", "site": {"reason": "r"}}
                     for k in [("a.py", 5), ("a.py", 6), ("a.py", 20)]}
    group_members_by_id = {"a.py:5": [("a.py", 5), ("a.py", 6), ("a.py", 20)]}

    fixgen._resolve_overlapping_fixes(merged, group_members_by_id, sites_by_key)

    assert merged["fixes"] == []
    assert {f["line"] for f in merged["flagged_for_human"]} == {5, 6, 20}
    assert all(f["flag_source"] == "overlap_conflict_guard" for f in merged["flagged_for_human"])
    assert all(f["group_id"] == "a.py:5" for f in merged["flagged_for_human"])


def test_resolve_overlapping_fixes_leaves_unrelated_fixes_untouched():
    # The actual bug report's other half: an overlap between two sites
    # must not affect any unrelated fix in the same run.
    a = _overlap_fix("a.py", 5, 7, ["x", "y", "z"], ["X", "Y", "Z"])
    b = _overlap_fix("a.py", 6, 6, ["y"], ["DIFFERENT"])
    unrelated = _overlap_fix("b.py", 1, 1, ["p"], ["q"])
    merged = {"fixes": [a, b, unrelated], "flagged_for_human": []}
    sites_by_key = {("a.py", 5): {"role": "proposed", "site": {"reason": "r"}},
                     ("a.py", 6): {"role": "proposed", "site": {"reason": "r"}}}

    fixgen._resolve_overlapping_fixes(merged, {}, sites_by_key)

    assert merged["fixes"] == [unrelated]


def test_resolve_overlapping_fixes_does_not_treat_a_partial_overlap_as_a_candidate_duplicate():
    # Neither span contains the other -- a genuine partial overlap. Even
    # with matching text in the shared region, this pipeline never treats
    # it as provable duplication (see _nesting_order's docstring): declined
    # as a conflict instead of guessed at.
    a = _overlap_fix("a.py", 5, 8, ["a", "b", "c", "d"], ["A", "B", "C", "D"])
    b = _overlap_fix("a.py", 7, 10, ["c", "d", "e", "f"], ["C", "D", "E", "F"])
    merged = {"fixes": [a, b], "flagged_for_human": []}
    sites_by_key = {("a.py", 5): {"role": "proposed", "site": {"reason": "r"}},
                     ("a.py", 7): {"role": "proposed", "site": {"reason": "r"}}}

    fixgen._resolve_overlapping_fixes(merged, {}, sites_by_key)

    assert merged["fixes"] == []
    assert len(merged["flagged_for_human"]) == 2
    assert all(f["flag_source"] == "overlap_conflict_guard" for f in merged["flagged_for_human"])


# ---------------------------------------------------------------------
# fixgen.run() end-to-end: overlap resolution must never abort the run,
# and unrelated fixes must ship regardless of one torn/duplicate pair.
# ---------------------------------------------------------------------

def test_run_dedupes_the_digital_py_48_50_duplicate_end_to_end(tmp_path):
    body = "\n".join(f"x{i} = {i}" for i in range(1, 48)) + "\n"
    body += "result = foo(\n    bar,\n)\n"
    reader = _make_repo(tmp_path, filename="digital.py", body=body)
    proposed = [
        {"file": "digital.py", "line": 48, "snippet": "result = foo(", "pattern": "1",
         "reason": "renamed call", "related_sites": []},
        {"file": "digital.py", "line": 50, "snippet": ")", "pattern": "1",
         "reason": "renamed call, closing paren", "related_sites": []},
    ]
    response = {
        "fixes": [
            {"file": "digital.py", "line": 48, "end_line": 50,
             "original_lines": ["result = foo(", "    bar,", ")"],
             "proposed_lines": ["result = baz(", "    bar,", ")"], "reason": "renamed"},
            {"file": "digital.py", "line": 50, "end_line": 50,
             "original_lines": [")"], "proposed_lines": [")"], "reason": "no change needed here"},
        ],
        "flagged_for_human": [],
    }
    client = FakeLLMClient([response])
    merged = fixgen.run(client, reader, proposed, FACTBLOCK, str(tmp_path / "wd"), chunk_size=40)

    assert len(merged["fixes"]) == 1
    assert merged["fixes"][0]["line"] == 48
    assert merged["fixes"][0]["end_line"] == 50
    assert merged["flagged_for_human"] == []
    assert len(merged["duplicate_fixes_dropped"]) == 1
    assert merged["duplicate_fixes_dropped"][0]["dropped"]["line"] == 50


def test_run_declines_a_real_overlap_conflict_without_aborting_and_ships_the_rest(tmp_path):
    # Three proposed sites: two share a statement and their joint call
    # produces genuinely CONFLICTING overlapping fixes (a model mistake, or
    # a shape grouping didn't fully resolve); the third is entirely
    # unrelated. The conflicting pair must decline together; the unrelated
    # fix must still ship -- this is the actual bug report: one torn pair
    # must never take a 229-fix run down with it.
    body = "\n".join(f"x{i} = {i}" for i in range(1, 48)) + "\n"
    body += "result = foo(\n    bar,\n)\n"
    body += "other = 1\n"  # line 51, unrelated
    reader = _make_repo(tmp_path, filename="digital.py", body=body)
    proposed = [
        {"file": "digital.py", "line": 48, "snippet": "result = foo(", "pattern": "1",
         "reason": "renamed call", "related_sites": []},
        {"file": "digital.py", "line": 50, "snippet": ")", "pattern": "1",
         "reason": "renamed call, closing paren", "related_sites": []},
        {"file": "digital.py", "line": 51, "snippet": "other = 1", "pattern": "1",
         "reason": "unrelated rename", "related_sites": []},
    ]
    responses = [
        {
            "fixes": [
                {"file": "digital.py", "line": 48, "end_line": 50,
                 "original_lines": ["result = foo(", "    bar,", ")"],
                 "proposed_lines": ["result = baz(", "    bar,", ")"], "reason": "renamed one way"},
                {"file": "digital.py", "line": 50, "end_line": 50,
                 "original_lines": [")"], "proposed_lines": ["# closed differently"],
                 "reason": "a genuinely different, conflicting edit at the same line"},
            ],
            "flagged_for_human": [],
        },
        {
            "fixes": [{"file": "digital.py", "line": 51, "end_line": 51,
                       "original_lines": ["other = 1"], "proposed_lines": ["other = 2"],
                       "reason": "unrelated fix"}],
            "flagged_for_human": [],
        },
    ]
    client = FakeLLMClient(responses)
    merged = fixgen.run(client, reader, proposed, FACTBLOCK, str(tmp_path / "wd"), chunk_size=1)

    assert [f["line"] for f in merged["fixes"]] == [51]
    assert {f["line"] for f in merged["flagged_for_human"]} == {48, 50}
    assert all(f["flag_source"] == "overlap_conflict_guard" for f in merged["flagged_for_human"])


def test_report_renders_overlap_conflict_guard_decline(tmp_path):
    fixgen_expanded = {
        "fixes": [],
        "flagged_for_human": [
            {"file": "digital.py", "line": 48,
             "reason": "this site's proposed fix overlaps another proposed fix "
                       "(digital.py:48-50 and digital.py:50-50), and the two disagree "
                       "where they overlap.",
             "flag_source": "overlap_conflict_guard", "group_id": "digital.py:48",
             "group_members": [
                 {"file": "digital.py", "line": 48, "role": "proposed", "reason": "renamed call"},
                 {"file": "digital.py", "line": 50, "role": "proposed", "reason": "closing paren"},
             ]},
            {"file": "digital.py", "line": 50,
             "reason": "this site's proposed fix overlaps another proposed fix, and the "
                       "two disagree where they overlap.",
             "flag_source": "overlap_conflict_guard", "group_id": "digital.py:48",
             "group_members": [
                 {"file": "digital.py", "line": 48, "role": "proposed", "reason": "renamed call"},
                 {"file": "digital.py", "line": 50, "role": "proposed", "reason": "closing paren"},
             ]},
        ],
    }
    expanded_merged = {
        "proposed_sites": [
            {"file": "digital.py", "line": 48, "snippet": "result = foo(", "pattern": "1", "reason": "renamed call"},
            {"file": "digital.py", "line": 50, "snippet": ")", "pattern": "1", "reason": "closing paren"},
        ],
        "flag_uncertain": [], "considered_and_rejected": [],
    }
    path = report.write(
        str(tmp_path), expanded_merged, {}, FACTBLOCK, {"patterns": {"p1": "x"}},
        fixgen_expanded=fixgen_expanded, verification_report=None,
    )
    text = open(path).read()
    assert "### Coupled edit group" in text
    assert ("declined here -- this fix overlapped another proposed fix's own lines and "
            "the two disagreed where they overlapped") in text
    if "### Model judgment call" in text:
        section = text.split("### Model judgment call", 1)[1]
        assert "digital.py:48" not in section
        assert "digital.py:50" not in section
