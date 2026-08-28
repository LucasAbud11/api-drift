"""Offline tests for gap-fill (apidrift/stages/gapfill.py): target-set
construction from the coverage guard's own output, chunk planning, the
offline cost estimate, idempotent per-chunk persistence, pattern-id
collision handling on merge (hard fail against the pre-existing
vocabulary, auto-renumber across gap-fill's own chunks), and the
declined/unresolved bookkeeping. No network, no LLM calls -- a scripted
fake client answers whichever chunks actually need deriving.
"""
import json
import os

import pytest

from apidrift import guards, llm
from apidrift.stages import gapfill


# ---------------------------------------------------------------------
# Fake client
# ---------------------------------------------------------------------

class FakeGapfillClient:
    """`response` is either one response reused for every chunk, or a
    dict keyed by stage name (e.g. "gapfill_chunk_000") for scripting
    different chunks differently -- same shape ScriptedLLMClient uses
    elsewhere in this test suite."""
    def __init__(self, response):
        self._response = response
        self.calls = []

    def complete(self, stage, system_text, user_text, schema, cache_system=False,
                 cache_ttl="5m", max_tokens=8000, effort="high"):
        self.calls.append({"stage": stage, "system_text": system_text, "user_text": user_text,
                            "cache_system": cache_system,
                            "usage": {"input_tokens": 100, "output_tokens": 50,
                                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}})
        # A single-response dict has "patterns"/"declined" directly; a
        # per-stage script is a dict of {stage_name: response}.
        if isinstance(self._response, dict) and "patterns" not in self._response:
            resp = self._response[stage]
        else:
            resp = self._response
        return resp() if callable(resp) else resp


class TruncatingLLMClient:
    """Always raises llm.TruncatedResponseError, exactly like the real
    AnthropicLLMClient does when stop_reason == 'max_tokens' -- used to
    check gap-fill wraps the error with chunk-specific guidance rather
    than letting the bare SDK-shaped message through."""
    def __init__(self):
        self.calls = []

    def complete(self, stage, system_text, user_text, schema, cache_system=False,
                 cache_ttl="5m", max_tokens=8000, effort="high"):
        self.calls.append(stage)
        raise llm.TruncatedResponseError(
            f"[{stage}] the model's response was cut off at the {max_tokens}-token "
            f"max_tokens limit before it finished."
        )


def _fb(package_name, texts):
    return {"package_name": package_name,
            "facts": [{"number": i + 1, "text": t} for i, t in enumerate(texts)]}


# ---------------------------------------------------------------------
# build_targets -- exercised directly against row-shaped dicts (the
# exact shape guards.compute_fact_pattern_coverage returns) so these
# tests pin build_targets' own filtering logic in isolation, without
# also depending on the regex-matching behavior compute_fact_pattern_
# coverage has its own dedicated tests for in test_guards.py.
# ---------------------------------------------------------------------

def _row(number, status, spans):
    return {"number": number, "text": f"fact {number}", "status": status, "spans": spans}


def _span(text, searchable=True, covering=None):
    return {"span": text, "searchable": searchable, "covering": covering or [],
            "category": None if searchable else "some_category"}


def test_build_targets_only_partial_and_uncovered():
    rows = [
        _row(1, "uncovered", [_span("WidgetSession")]),
        _row(2, "covered", [_span("widget.Client", covering=["p1"])]),
        _row(3, "no_identifier", []),
        _row(4, "non_breaking", []),
        _row(5, "unsearchable", [_span("TypeError", searchable=False)]),
    ]
    targets = gapfill.build_targets(rows)
    assert set(targets) == {1}
    assert targets[1]["spans"] == ["WidgetSession"]


def test_build_targets_partial_fact_lists_only_the_uncovered_span():
    rows = [
        _row(1, "partial", [
            _span("WidgetSession"),  # uncovered
            _span("widget.Client", covering=["p1"]),  # covered
            _span("TypeError", searchable=False),  # structurally excluded
        ]),
    ]
    targets = gapfill.build_targets(rows)
    assert targets[1]["spans"] == ["WidgetSession"]


def test_build_targets_empty_when_nothing_uncovered():
    rows = [_row(1, "covered", [_span("widget.Client", covering=["p1"])])]
    assert gapfill.build_targets(rows) == {}


def test_build_targets_against_real_coverage_computation():
    # One end-to-end check against the real guards.compute_fact_pattern_
    # coverage output, to catch a row-shape mismatch the isolated tests
    # above (using hand-built rows) wouldn't. A fact naming only a bare
    # Python builtin must not appear as a target at all.
    factblock = _fb("widget", [
        "`WidgetSession` construction now requires a `timeout` kwarg.",
        "Calling the loader with a bad path now raises `TypeError` instead of returning nothing.",
    ])
    rows = guards.compute_fact_pattern_coverage(factblock, {"patterns": {}})
    targets = gapfill.build_targets(rows)
    assert set(targets) == {1}
    assert "WidgetSession" in targets[1]["spans"]


# ---------------------------------------------------------------------
# estimate_cost_report -- pure, offline
# ---------------------------------------------------------------------

def test_estimate_cost_report_makes_no_call_and_reports_target_count():
    factblock = _fb("widget", ["`WidgetSession` needs a `timeout` kwarg."])
    vocabulary = {"patterns": {}}
    rows = guards.compute_fact_pattern_coverage(factblock, vocabulary)
    targets = gapfill.build_targets(rows)
    lines = gapfill.estimate_cost_report("guide text " * 50, vocabulary, factblock, targets)
    joined = "\n".join(lines)
    assert "1 target fact(s)" in joined
    assert "1 planned chunk(s)" in joined
    assert "no API calls made yet" in joined


def test_estimate_cost_report_includes_dollar_estimate_for_known_model():
    factblock = _fb("widget", ["`WidgetSession` needs a `timeout` kwarg."])
    vocabulary = {"patterns": {}}
    rows = guards.compute_fact_pattern_coverage(factblock, vocabulary)
    targets = gapfill.build_targets(rows)
    lines = gapfill.estimate_cost_report("guide text", vocabulary, factblock, targets, model="claude-opus-5")
    assert any("estimated input-token cost" in line for line in lines)


def test_estimate_cost_report_unknown_model_has_no_dollar_estimate():
    lines = gapfill.estimate_cost_report("guide text", {"patterns": {}}, _fb("w", []), {}, model="not-a-real-model")
    assert any("no pricing data" in line for line in lines)


# ---------------------------------------------------------------------
# run() -- single pass, idempotent, merge/collision, unresolved bookkeeping
# ---------------------------------------------------------------------

def _setup(tmp_path):
    # A non-empty starting vocabulary, matching every real pipeline.run()
    # invocation -- vocabulary["patterns"] has already passed
    # validate_vocabulary's own non-empty requirement by the time
    # gap-fill ever sees it, whether freshly derived or loaded.
    factblock = _fb("widget", [
        "`WidgetSession` construction now requires a positional timeout argument.",
        "Calling the loader with a bad path now raises `TypeError` instead of returning nothing.",
        "`widget.Client` is unaffected.",
    ])
    vocabulary = {"patterns": {"p1": r"\bwidget\.Client\b"}}
    rows = guards.compute_fact_pattern_coverage(factblock, vocabulary)
    workdir = str(tmp_path)
    return factblock, vocabulary, rows, workdir


def test_run_merges_new_pattern_and_recomputes_coverage(tmp_path):
    factblock, vocabulary, rows, workdir = _setup(tmp_path)
    response = {
        "patterns": [{"name": "gf_widgetsess", "regex": r"\bWidgetSession\b"}],
        "declined": [],
    }
    client = FakeGapfillClient(response)

    merged, report, new_rows = gapfill.run(client, "guide text", factblock, vocabulary, rows, workdir)

    assert len(client.calls) == 1
    assert "gf_widgetsess" in merged["patterns"]
    assert report["new_patterns"] == ["gf_widgetsess"]
    by_number = {r["number"]: r for r in new_rows}
    assert by_number[1]["status"] == "covered"


def test_run_resumes_without_a_second_call(tmp_path):
    factblock, vocabulary, rows, workdir = _setup(tmp_path)
    response = {"patterns": [{"name": "gf_widgetsess", "regex": r"\bWidgetSession\b"}], "declined": []}
    client = FakeGapfillClient(response)

    gapfill.run(client, "guide text", factblock, vocabulary, rows, workdir)
    assert len(client.calls) == 1

    # A second run() against the same workdir must not re-invoke the
    # client -- the pass file already validates.
    merged2, report2, _ = gapfill.run(client, "guide text", factblock, vocabulary, rows, workdir)
    assert len(client.calls) == 1
    assert "gf_widgetsess" in merged2["patterns"]


def test_run_declined_and_unresolved_are_distinct(tmp_path):
    factblock, vocabulary, rows, workdir = _setup(tmp_path)
    # Only WidgetSession's span is covered; TypeError was already
    # excluded from the target set by build_targets (it's a bare Python
    # builtin), so there is exactly one target fact/span to begin with.
    response = {"patterns": [{"name": "gf_widgetsess", "regex": r"\bWidgetSession\b"}], "declined": []}
    client = FakeGapfillClient(response)
    merged, report, new_rows = gapfill.run(client, "guide text", factblock, vocabulary, rows, workdir)

    assert report["target_fact_count"] == 1
    assert report["declined"] == []
    assert report["unresolved"] == []


def test_run_unresolved_when_target_left_untouched(tmp_path):
    factblock, vocabulary, rows, workdir = _setup(tmp_path)
    # The model returns nothing at all for the one target fact -- neither
    # a pattern nor a decline. This must show up as "unresolved", not be
    # silently dropped (that silence is exactly the defect gap-fill
    # exists to fix).
    response = {"patterns": [], "declined": []}
    client = FakeGapfillClient(response)
    merged, report, new_rows = gapfill.run(client, "guide text", factblock, vocabulary, rows, workdir)

    assert report["unresolved"] == [{"fact": 1, "span": "WidgetSession"}]


def test_run_records_explicit_decline(tmp_path):
    factblock, vocabulary, rows, workdir = _setup(tmp_path)
    response = {
        "patterns": [],
        "declined": [{"fact": 1, "span": "WidgetSession", "reason": "no distinguishing "
                      "co-occurring token found in the guide's own example"}],
    }
    client = FakeGapfillClient(response)
    merged, report, new_rows = gapfill.run(client, "guide text", factblock, vocabulary, rows, workdir)

    assert report["declined"][0]["span"] == "WidgetSession"
    assert report["unresolved"] == []


def test_run_id_collision_with_existing_vocabulary_raises(tmp_path):
    factblock, vocabulary, rows, workdir = _setup(tmp_path)
    vocabulary = {"patterns": {"gf_widgetsess": r"\bSomethingElse\b"}}
    rows = guards.compute_fact_pattern_coverage(factblock, vocabulary)
    response = {"patterns": [{"name": "gf_widgetsess", "regex": r"\bWidgetSession\b"}], "declined": []}
    client = FakeGapfillClient(response)

    with pytest.raises(ValueError, match="collides with an existing vocabulary pattern id"):
        gapfill.run(client, "guide text", factblock, vocabulary, rows, workdir)


def test_run_persists_chunk_file_merged_file_and_report(tmp_path):
    factblock, vocabulary, rows, workdir = _setup(tmp_path)
    response = {"patterns": [{"name": "gf_widgetsess", "regex": r"\bWidgetSession\b"}], "declined": []}
    client = FakeGapfillClient(response)
    gapfill.run(client, "guide text", factblock, vocabulary, rows, workdir)

    assert os.path.isfile(os.path.join(workdir, "gapfill", "chunk_000.json"))
    assert os.path.isfile(os.path.join(workdir, "gapfill", "merged.json"))
    with open(os.path.join(workdir, "gapfill", "report.json")) as f:
        report = json.load(f)
    assert report["new_patterns"] == ["gf_widgetsess"]
    assert report["chunk_count"] == 1
    assert report["renamed_on_merge"] == []


def test_run_invalid_gapfill_output_raises_and_leaves_no_chunk_file(tmp_path):
    factblock, vocabulary, rows, workdir = _setup(tmp_path)
    # A pattern that violates the anti-Goodhart alternation cap -- must
    # hard-fail via validate_gapfill_dict, not get silently accepted or
    # partially written.
    response = {
        "patterns": [{"name": "gf_misc", "regex": r"\b(A|B|C|D)\b"}],
        "declined": [],
    }
    client = FakeGapfillClient(response)

    with pytest.raises(ValueError):
        gapfill.run(client, "guide text", factblock, vocabulary, rows, workdir)
    assert not os.path.isfile(os.path.join(workdir, "gapfill", "chunk_000.json"))


# ---------------------------------------------------------------------
# Chunking: plan, multi-chunk merge/renumbering, resume, truncation
# ---------------------------------------------------------------------

def _targets(n):
    """n distinct target facts, each with its own single searchable,
    uncovered span -- built directly as build_targets' own output shape
    rather than through a real coverage computation, since these tests
    are about chunk planning/merging, not span matching."""
    return {i: {"text": f"fact {i} text", "spans": [f"Symbol{i}"]} for i in range(1, n + 1)}


def test_plan_chunks_splits_by_size_in_fact_order():
    chunks = gapfill.plan_chunks(_targets(7), chunk_size=3)
    assert [sorted(c) for c in chunks] == [[1, 2, 3], [4, 5, 6], [7]]


def test_plan_chunks_empty_targets_is_zero_chunks():
    assert gapfill.plan_chunks({}, chunk_size=3) == []


def test_plan_chunks_all_facts_present_exactly_once():
    targets = _targets(11)
    chunks = gapfill.plan_chunks(targets, chunk_size=4)
    all_numbers = [n for c in chunks for n in c]
    assert sorted(all_numbers) == sorted(targets)


def _multi_setup(tmp_path, n_facts):
    texts = [f"`Symbol{i}` construction changed." for i in range(1, n_facts + 1)]
    factblock = _fb("widget", texts)
    vocabulary = {"patterns": {"p1": r"\bwidget\.Client\b"}}
    rows = guards.compute_fact_pattern_coverage(factblock, vocabulary)
    return factblock, vocabulary, rows, str(tmp_path)


def test_run_splits_into_multiple_chunks_and_makes_one_call_each(tmp_path):
    factblock, vocabulary, rows, workdir = _multi_setup(tmp_path, n_facts=5)
    script = {
        "gapfill_chunk_000": {
            "patterns": [
                {"name": "gf_symbol1", "regex": r"\bSymbol1\b"},
                {"name": "gf_symbol2", "regex": r"\bSymbol2\b"},
            ],
            "declined": [],
        },
        "gapfill_chunk_001": {
            "patterns": [{"name": "gf_symbol3", "regex": r"\bSymbol3\b"}],
            "declined": [{"fact": 4, "span": "Symbol4", "reason": "no qualifying context stated"}],
        },
        "gapfill_chunk_002": {"patterns": [], "declined": []},
    }
    client = FakeGapfillClient(script)

    merged, report, new_rows = gapfill.run(
        client, "guide text", factblock, vocabulary, rows, workdir, chunk_size=2,
    )

    assert sorted(c["stage"] for c in client.calls) == [
        "gapfill_chunk_000", "gapfill_chunk_001", "gapfill_chunk_002",
    ]
    assert report["chunk_count"] == 3
    assert set(report["new_patterns"]) == {"gf_symbol1", "gf_symbol2", "gf_symbol3"}
    assert report["declined"] == [{"fact": 4, "span": "Symbol4", "reason": "no qualifying context stated"}]
    # fact 5 (Symbol5) got neither a pattern nor a decline from chunk_002.
    assert report["unresolved"] == [{"fact": 5, "span": "Symbol5"}]
    assert "gf_symbol1" in merged["patterns"] and "gf_symbol3" in merged["patterns"]


def test_run_caches_system_prompt_when_more_than_one_chunk(tmp_path):
    factblock, vocabulary, rows, workdir = _multi_setup(tmp_path, n_facts=3)
    script = {
        "gapfill_chunk_000": {"patterns": [{"name": "gf_symbol1", "regex": r"\bSymbol1\b"}], "declined": []},
        "gapfill_chunk_001": {"patterns": [{"name": "gf_symbol2", "regex": r"\bSymbol2\b"}], "declined": []},
        "gapfill_chunk_002": {"patterns": [{"name": "gf_symbol3", "regex": r"\bSymbol3\b"}], "declined": []},
    }
    client = FakeGapfillClient(script)
    gapfill.run(client, "guide text", factblock, vocabulary, rows, workdir, chunk_size=1)

    assert all(c["cache_system"] for c in client.calls)
    # Every chunk's system_text is byte-identical -- only user_text
    # (the chunk's own target-fact slice) should vary, which is what
    # makes a cache write from chunk 0 redeemable by chunk 1 onward.
    system_texts = {c["system_text"] for c in client.calls}
    assert len(system_texts) == 1


def test_run_does_not_cache_system_prompt_for_a_single_chunk_default_ttl(tmp_path):
    factblock, vocabulary, rows, workdir = _setup(tmp_path)
    response = {"patterns": [{"name": "gf_widgetsess", "regex": r"\bWidgetSession\b"}], "declined": []}
    client = FakeGapfillClient(response)
    gapfill.run(client, "guide text", factblock, vocabulary, rows, workdir)

    assert client.calls[0]["cache_system"] is False


def test_run_renumbers_pattern_id_colliding_across_chunks(tmp_path):
    factblock, vocabulary, rows, workdir = _multi_setup(tmp_path, n_facts=2)
    # Both chunks independently pick the same id for a different symbol
    # -- an expected consequence of deriving each chunk with no
    # visibility into what id any other chunk chose, not a model defect.
    script = {
        "gapfill_chunk_000": {"patterns": [{"name": "gf_symbol", "regex": r"\bSymbol1\b"}], "declined": []},
        "gapfill_chunk_001": {"patterns": [{"name": "gf_symbol", "regex": r"\bSymbol2\b"}], "declined": []},
    }
    client = FakeGapfillClient(script)

    merged, report, _ = gapfill.run(
        client, "guide text", factblock, vocabulary, rows, workdir, chunk_size=1,
    )

    assert "gf_symbol" in merged["patterns"]
    assert "gf_symbol_2" in merged["patterns"]
    assert merged["patterns"]["gf_symbol"] == r"\bSymbol1\b"
    assert merged["patterns"]["gf_symbol_2"] == r"\bSymbol2\b"
    assert report["renamed_on_merge"] == [{"from": "gf_symbol", "to": "gf_symbol_2"}]


def test_run_resume_only_calls_for_incomplete_chunks(tmp_path):
    factblock, vocabulary, rows, workdir = _multi_setup(tmp_path, n_facts=2)
    script = {
        "gapfill_chunk_000": {"patterns": [{"name": "gf_symbol1", "regex": r"\bSymbol1\b"}], "declined": []},
        "gapfill_chunk_001": {"patterns": [{"name": "gf_symbol2", "regex": r"\bSymbol2\b"}], "declined": []},
    }
    client = FakeGapfillClient(script)
    gapfill.run(client, "guide text", factblock, vocabulary, rows, workdir, chunk_size=1)
    assert len(client.calls) == 2

    # Delete chunk 1's file only -- a resumed run must re-derive exactly
    # that one chunk, never chunk 0 again.
    os.remove(os.path.join(workdir, "gapfill", "chunk_001.json"))
    client2 = FakeGapfillClient(script)
    merged, report, _ = gapfill.run(
        client2, "guide text", factblock, vocabulary, rows, workdir, chunk_size=1,
    )
    assert [c["stage"] for c in client2.calls] == ["gapfill_chunk_001"]
    assert "gf_symbol1" in merged["patterns"] and "gf_symbol2" in merged["patterns"]


def test_run_resume_after_a_later_chunk_fails_validation_does_not_recharge_the_earlier_one(tmp_path):
    # The real scenario this guards against: chunk 0's call succeeds and
    # is paid for and persisted; chunk 1's call also succeeds (gets
    # billed) but its OWN response fails validate_gapfill_dict (here: an
    # alternation over the branch cap -- any hard-fail shape exercises
    # the same path). chunk_001.json is therefore never written -- the
    # write only happens after validation passes. A resumed run must
    # not re-request chunk 0 (already valid, already paid for) and must
    # only retry chunk 1.
    factblock, vocabulary, rows, workdir = _multi_setup(tmp_path, n_facts=2)
    bad_script = {
        "gapfill_chunk_000": {"patterns": [{"name": "gf_symbol1", "regex": r"\bSymbol1\b"}], "declined": []},
        "gapfill_chunk_001": {"patterns": [{"name": "gf_bad", "regex": r"\b(A|B|C|D)\b"}], "declined": []},
    }
    client = FakeGapfillClient(bad_script)
    with pytest.raises(ValueError, match="alternation"):
        gapfill.run(client, "guide text", factblock, vocabulary, rows, workdir, chunk_size=1)

    assert os.path.isfile(os.path.join(workdir, "gapfill", "chunk_000.json"))
    assert not os.path.isfile(os.path.join(workdir, "gapfill", "chunk_001.json"))
    assert [c["stage"] for c in client.calls] == ["gapfill_chunk_000", "gapfill_chunk_001"]

    fixed_script = {
        "gapfill_chunk_000": {"patterns": [{"name": "gf_symbol1", "regex": r"\bSymbol1\b"}], "declined": []},
        "gapfill_chunk_001": {"patterns": [{"name": "gf_symbol2", "regex": r"\bSymbol2\b"}], "declined": []},
    }
    client2 = FakeGapfillClient(fixed_script)
    merged, report, _ = gapfill.run(
        client2, "guide text", factblock, vocabulary, rows, workdir, chunk_size=1,
    )
    # Only chunk 1 was re-requested -- chunk 0's already-valid, already-
    # billed output was reused as-is.
    assert [c["stage"] for c in client2.calls] == ["gapfill_chunk_001"]
    assert "gf_symbol1" in merged["patterns"] and "gf_symbol2" in merged["patterns"]


def test_run_truncation_error_names_the_chunk_and_suggests_lowering_chunk_size(tmp_path):
    factblock, vocabulary, rows, workdir = _setup(tmp_path)
    client = TruncatingLLMClient()

    with pytest.raises(llm.TruncatedResponseError, match="gapfill_chunk_000"):
        gapfill.run(client, "guide text", factblock, vocabulary, rows, workdir)
    # The retry-guidance in the wrapped message names the actual flag.
    with pytest.raises(llm.TruncatedResponseError, match="--gapfill-chunk-size"):
        gapfill.run(TruncatingLLMClient(), "guide text", factblock, vocabulary, rows, workdir)
