"""Offline tests for gap-fill (apidrift/stages/gapfill.py): target-set
construction from the coverage guard's own output, the offline cost
estimate, idempotent single-pass persistence, pattern-id collision
detection on merge, and the declined/unresolved bookkeeping. No
network, no LLM calls -- a scripted fake client answers the one call a
pass makes.
"""
import json
import os

import pytest

from apidrift import guards
from apidrift.stages import gapfill


# ---------------------------------------------------------------------
# Fake client
# ---------------------------------------------------------------------

class FakeGapfillClient:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def complete(self, stage, system_text, user_text, schema, cache_system=False,
                 cache_ttl="5m", max_tokens=8000, effort="high"):
        self.calls.append({"stage": stage, "system_text": system_text, "user_text": user_text,
                            "usage": {"input_tokens": 100, "output_tokens": 50,
                                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}})
        return self._response() if callable(self._response) else self._response


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
    assert "no API call made yet" in joined


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


def test_run_persists_pass_file_and_report(tmp_path):
    factblock, vocabulary, rows, workdir = _setup(tmp_path)
    response = {"patterns": [{"name": "gf_widgetsess", "regex": r"\bWidgetSession\b"}], "declined": []}
    client = FakeGapfillClient(response)
    gapfill.run(client, "guide text", factblock, vocabulary, rows, workdir)

    assert os.path.isfile(os.path.join(workdir, "gapfill", "pass_000.json"))
    with open(os.path.join(workdir, "gapfill", "report.json")) as f:
        report = json.load(f)
    assert report["new_patterns"] == ["gf_widgetsess"]


def test_run_invalid_gapfill_output_raises_and_leaves_no_pass_file(tmp_path):
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
    assert not os.path.isfile(os.path.join(workdir, "gapfill", "pass_000.json"))
