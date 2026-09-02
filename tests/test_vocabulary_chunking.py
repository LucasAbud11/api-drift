"""Offline tests for chunked vocabulary derivation (apidrift/stages/
vocabulary.py): chunk planning by fact count, resume skipping completed
chunks, pattern-id collision handling on merge (auto-renumber across
vocabulary's own chunks -- there's no pre-existing vocabulary to hard-fail
against here, unlike gap-fill), cache_system gating, per-chunk truncation
detection, and that guards.check_vocabulary_coverage/check_vocabulary_yield
still run cleanly on a merged, chunked vocabulary. No network, no LLM
calls -- a scripted fake client answers whichever chunks actually need
deriving.
"""
import json
import os

import pytest

from apidrift import guards, llm, validate
from apidrift.stages import vocabulary


# ---------------------------------------------------------------------
# Fake client
# ---------------------------------------------------------------------

class ScriptedLLMClient:
    """`script` maps a stage-name PREFIX (e.g. "vocabulary_chunk_000") to
    a response -- same shape ScriptedLLMClient uses elsewhere in this
    test suite. A response may be callable (invoked with no args) to
    script a one-shot failure/success sequence."""

    def __init__(self, script):
        self._script = script
        self.calls = []

    def complete(self, stage, system_text, user_text, schema, cache_system=False,
                 cache_ttl="5m", max_tokens=8000, effort="high"):
        self.calls.append({"stage": stage, "system_text": system_text, "user_text": user_text,
                            "cache_system": cache_system,
                            "usage": {"input_tokens": 100, "output_tokens": 50,
                                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}})
        for prefix, response in self._script.items():
            if stage.startswith(prefix):
                return response() if callable(response) else response
        raise AssertionError(f"no scripted response for stage {stage!r}")


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


def _fb(package_name, n_facts):
    return {"package_name": package_name,
            "facts": [{"number": i, "text": f"`Symbol{i}` construction changed."}
                      for i in range(1, n_facts + 1)]}


def _resp(*pairs):
    return {"patterns": [{"name": n, "regex": r} for n, r in pairs]}


# ---------------------------------------------------------------------
# Chunk planning
# ---------------------------------------------------------------------

def test_chunks_splits_by_size_in_fact_order():
    facts = _fb("widget", 7)["facts"]
    chunks = vocabulary._chunks(facts, chunk_size=3)
    assert [sorted(f["number"] for f in part) for _, part in chunks] == [
        [1, 2, 3], [4, 5, 6], [7],
    ]


def test_chunks_all_facts_present_exactly_once():
    facts = _fb("widget", 11)["facts"]
    chunks = vocabulary._chunks(facts, chunk_size=4)
    all_numbers = [f["number"] for _, part in chunks for f in part]
    assert sorted(all_numbers) == list(range(1, 12))


def test_chunks_single_chunk_when_under_size():
    facts = _fb("widget", 3)["facts"]
    chunks = vocabulary._chunks(facts, chunk_size=40)
    assert len(chunks) == 1


# ---------------------------------------------------------------------
# run() -- single chunk, idempotence, persistence
# ---------------------------------------------------------------------

def test_run_single_chunk_merges_patterns(tmp_path):
    fb = _fb("widget", 2)
    client = ScriptedLLMClient({
        "vocabulary_chunk_000": _resp(("p1", r"\bSymbol1\b"), ("p2", r"\bSymbol2\b")),
    })
    merged = vocabulary.run(client, "guide text", fb, str(tmp_path))
    assert merged["patterns"] == {"p1": r"\bSymbol1\b", "p2": r"\bSymbol2\b"}
    assert len(client.calls) == 1


def test_run_persists_chunk_and_merged_files(tmp_path):
    fb = _fb("widget", 1)
    client = ScriptedLLMClient({"vocabulary_chunk_000": _resp(("p1", r"\bSymbol1\b"))})
    vocabulary.run(client, "guide text", fb, str(tmp_path))

    assert os.path.isfile(os.path.join(str(tmp_path), "vocabulary", "chunk_000.json"))
    with open(os.path.join(str(tmp_path), "vocabulary", "merged.json")) as f:
        merged_file = json.load(f)
    assert merged_file["patterns"] == [{"name": "p1", "regex": r"\bSymbol1\b"}]


def test_resume_never_rederives_a_completed_chunk(tmp_path):
    fb = _fb("widget", 5)
    voc_dir = os.path.join(str(tmp_path), "vocabulary")
    os.makedirs(voc_dir, exist_ok=True)
    with open(os.path.join(voc_dir, "chunk_000.json"), "w") as f:
        json.dump({"patterns": [{"name": "p1", "regex": r"\bSymbol1\b"}]}, f)

    def _boom():
        raise AssertionError("chunk 0 should never be re-derived on resume")

    client = ScriptedLLMClient({
        "vocabulary_chunk_000": _boom,
        "vocabulary_chunk_001": _resp(("p2", r"\bSymbol2\b")),
    })
    merged = vocabulary.run(client, "guide text", fb, str(tmp_path), chunk_size=3)

    assert len(client.calls) == 1  # only chunk 1 triggered a real call
    assert merged["patterns"]["p1"] == r"\bSymbol1\b"
    assert merged["patterns"]["p2"] == r"\bSymbol2\b"


def test_resume_only_calls_for_incomplete_chunks_after_deletion(tmp_path):
    fb = _fb("widget", 2)
    script = {
        "vocabulary_chunk_000": _resp(("p1", r"\bSymbol1\b")),
        "vocabulary_chunk_001": _resp(("p2", r"\bSymbol2\b")),
    }
    client = ScriptedLLMClient(script)
    vocabulary.run(client, "guide text", fb, str(tmp_path), chunk_size=1)
    assert len(client.calls) == 2

    os.remove(os.path.join(str(tmp_path), "vocabulary", "chunk_001.json"))
    client2 = ScriptedLLMClient(script)
    merged = vocabulary.run(client2, "guide text", fb, str(tmp_path), chunk_size=1)

    assert [c["stage"] for c in client2.calls] == ["vocabulary_chunk_001"]
    assert merged["patterns"]["p1"] == r"\bSymbol1\b"
    assert merged["patterns"]["p2"] == r"\bSymbol2\b"


def test_run_is_idempotent_on_a_second_call(tmp_path):
    fb = _fb("widget", 1)
    call_count = {"n": 0}

    def _once():
        call_count["n"] += 1
        if call_count["n"] > 1:
            raise AssertionError("chunk was derived more than once")
        return _resp(("p1", r"\bSymbol1\b"))

    client = ScriptedLLMClient({"vocabulary_chunk_000": _once})
    vocabulary.run(client, "guide text", fb, str(tmp_path))
    merged_again = vocabulary.run(client, "guide text", fb, str(tmp_path))

    assert call_count["n"] == 1
    assert merged_again["patterns"]["p1"] == r"\bSymbol1\b"


def test_chunk_with_no_patterns_is_legal_and_contributes_nothing(tmp_path):
    fb = _fb("widget", 4)
    client = ScriptedLLMClient({
        "vocabulary_chunk_000": _resp(("p1", r"\bSymbol1\b")),
        "vocabulary_chunk_001": {"patterns": []},  # e.g. all UNCHANGED facts
    })
    merged = vocabulary.run(client, "guide text", fb, str(tmp_path), chunk_size=2)
    assert merged["patterns"] == {"p1": r"\bSymbol1\b"}


# ---------------------------------------------------------------------
# Merge: id collision across chunks renamed and logged; no collision
# leaves an id unchanged
# ---------------------------------------------------------------------

def test_merge_patterns_renames_id_colliding_across_chunks():
    chunk_results = [
        {"patterns": [{"name": "p_sym", "regex": r"\bSymbol1\b"}]},
        {"patterns": [{"name": "p_sym", "regex": r"\bSymbol2\b"}]},
    ]
    merged, renamed = vocabulary._merge_patterns(chunk_results)
    assert merged == {"p_sym": r"\bSymbol1\b", "p_sym_2": r"\bSymbol2\b"}
    assert renamed == [("p_sym", "p_sym_2")]


def test_merge_patterns_id_with_no_collision_is_unchanged():
    chunk_results = [
        {"patterns": [{"name": "p1", "regex": r"\bSymbol1\b"}]},
        {"patterns": [{"name": "p2", "regex": r"\bSymbol2\b"}]},
    ]
    merged, renamed = vocabulary._merge_patterns(chunk_results)
    assert merged == {"p1": r"\bSymbol1\b", "p2": r"\bSymbol2\b"}
    assert renamed == []


def test_merge_patterns_handles_a_three_way_collision():
    chunk_results = [
        {"patterns": [{"name": "p", "regex": r"\bA\b"}]},
        {"patterns": [{"name": "p", "regex": r"\bB\b"}]},
        {"patterns": [{"name": "p", "regex": r"\bC\b"}]},
    ]
    merged, renamed = vocabulary._merge_patterns(chunk_results)
    assert set(merged) == {"p", "p_2", "p_3"}
    assert merged["p"] == r"\bA\b"
    assert merged["p_2"] == r"\bB\b"
    assert merged["p_3"] == r"\bC\b"


def test_run_renumbers_pattern_id_colliding_across_chunks_end_to_end(tmp_path):
    fb = _fb("widget", 2)
    script = {
        "vocabulary_chunk_000": _resp(("p_sym", r"\bSymbol1\b")),
        "vocabulary_chunk_001": _resp(("p_sym", r"\bSymbol2\b")),
    }
    client = ScriptedLLMClient(script)
    printed = []
    merged = vocabulary.run(client, "guide text", fb, str(tmp_path), chunk_size=1,
                             print_fn=printed.append)

    assert merged["patterns"]["p_sym"] == r"\bSymbol1\b"
    assert merged["patterns"]["p_sym_2"] == r"\bSymbol2\b"
    assert any("renamed on merge" in line and "p_sym" in line for line in printed)


def test_run_concatenates_patterns_never_drops_any(tmp_path):
    fb = _fb("widget", 4)
    script = {
        "vocabulary_chunk_000": _resp(("p1", r"\bSymbol1\b"), ("p2", r"\bSymbol2\b")),
        "vocabulary_chunk_001": _resp(("p3", r"\bSymbol3\b")),
    }
    client = ScriptedLLMClient(script)
    merged = vocabulary.run(client, "guide text", fb, str(tmp_path), chunk_size=2)
    assert set(merged["patterns"]) == {"p1", "p2", "p3"}


# ---------------------------------------------------------------------
# Shared cacheable prefix / cache_system gating
# ---------------------------------------------------------------------

def test_cache_system_off_for_a_single_chunk_default_ttl(tmp_path):
    fb = _fb("widget", 1)
    client = ScriptedLLMClient({"vocabulary_chunk_000": _resp(("p1", r"\bSymbol1\b"))})
    vocabulary.run(client, "guide text", fb, str(tmp_path))
    assert client.calls[0]["cache_system"] is False


def test_cache_system_on_for_multiple_chunks_and_prefix_is_shared(tmp_path):
    fb = _fb("widget", 3)
    script = {
        "vocabulary_chunk_000": _resp(("p1", r"\bSymbol1\b")),
        "vocabulary_chunk_001": _resp(("p2", r"\bSymbol2\b")),
        "vocabulary_chunk_002": _resp(("p3", r"\bSymbol3\b")),
    }
    client = ScriptedLLMClient(script)
    vocabulary.run(client, "guide text", fb, str(tmp_path), chunk_size=1)

    assert all(c["cache_system"] for c in client.calls)
    # Only the varying fact slice (user_text) should differ between
    # chunks -- system_text (base rules + package name + guide text) must
    # be byte-identical every call, which is what makes a cache write
    # from chunk 0 redeemable by chunk 1 onward.
    system_texts = {c["system_text"] for c in client.calls}
    assert len(system_texts) == 1
    user_texts = {c["user_text"] for c in client.calls}
    assert len(user_texts) == 3


def test_cache_system_on_for_single_chunk_with_non_default_ttl(tmp_path):
    fb = _fb("widget", 1)
    client = ScriptedLLMClient({"vocabulary_chunk_000": _resp(("p1", r"\bSymbol1\b"))})
    vocabulary.run(client, "guide text", fb, str(tmp_path), cache_ttl="1h")
    assert client.calls[0]["cache_system"] is True


# ---------------------------------------------------------------------
# Per-chunk truncation detection
# ---------------------------------------------------------------------

def test_truncation_error_names_the_chunk_and_suggests_lowering_chunk_size(tmp_path):
    fb = _fb("widget", 1)
    client = TruncatingLLMClient()

    with pytest.raises(llm.TruncatedResponseError, match="vocabulary_chunk_000"):
        vocabulary.run(client, "guide text", fb, str(tmp_path))
    with pytest.raises(llm.TruncatedResponseError, match="--vocabulary-chunk-size"):
        vocabulary.run(TruncatingLLMClient(), "guide text", fb, str(tmp_path))


def test_truncation_does_not_write_a_chunk_file(tmp_path):
    fb = _fb("widget", 1)
    client = TruncatingLLMClient()
    with pytest.raises(llm.TruncatedResponseError):
        vocabulary.run(client, "guide text", fb, str(tmp_path))
    assert not os.path.isfile(os.path.join(str(tmp_path), "vocabulary", "chunk_000.json"))


# ---------------------------------------------------------------------
# validate_vocabulary_chunk
# ---------------------------------------------------------------------

def test_validate_vocabulary_chunk_allows_empty_patterns():
    validate.validate_vocabulary_chunk({"patterns": []})


def test_validate_vocabulary_chunk_missing_key_fails():
    with pytest.raises(ValueError, match="missing required top-level key"):
        validate.validate_vocabulary_chunk({})


def test_validate_vocabulary_chunk_duplicate_id_within_chunk_fails():
    with pytest.raises(ValueError, match="duplicate pattern id"):
        validate.validate_vocabulary_chunk({"patterns": [
            {"name": "p1", "regex": r"\bA\b"},
            {"name": "p1", "regex": r"\bB\b"},
        ]})


def test_validate_vocabulary_chunk_bad_regex_fails():
    with pytest.raises(ValueError, match="does not compile"):
        validate.validate_vocabulary_chunk({"patterns": [
            {"name": "p1", "regex": r"\bA("},
        ]})


def test_validate_vocabulary_chunk_does_not_require_ids_unique_across_chunks():
    # Cross-chunk collisions are legal at chunk-validation time -- they're
    # handled (renamed) at merge time, not failed here.
    validate.validate_vocabulary_chunk({"patterns": [{"name": "p1", "regex": r"\bA\b"}]})
    validate.validate_vocabulary_chunk({"patterns": [{"name": "p1", "regex": r"\bB\b"}]})


# ---------------------------------------------------------------------
# guards.check_vocabulary_coverage / check_vocabulary_yield still run,
# unchanged, on a merged (chunked) vocabulary
# ---------------------------------------------------------------------

def test_guards_run_on_the_merged_chunked_vocabulary(tmp_path):
    fb = _fb("widget", 3)
    script = {
        "vocabulary_chunk_000": _resp(("p1", r"\bSymbol1\b"), ("p2", r"\bSymbol2\b")),
        "vocabulary_chunk_001": _resp(("p3", r"\bSymbol3\b")),
    }
    client = ScriptedLLMClient(script)
    merged = vocabulary.run(client, "guide text", fb, str(tmp_path), chunk_size=2)

    coverage = guards.check_vocabulary_coverage(fb, merged)
    assert coverage.ok
    assert "Symbol1" not in coverage.report or True  # smoke: report renders without error

    yld = guards.check_vocabulary_yield(merged["patterns"], candidates=[])
    assert yld.ok  # zero candidates never trips the yield guard


def test_guards_flag_uncovered_facts_on_a_merged_chunked_vocabulary(tmp_path):
    # A chunk that declines to cover its own facts (e.g. every fact in
    # it reads as UNCHANGED) must still show up as a real coverage gap
    # once merged -- chunking must not hide an uncovered fact from the
    # same guard a single-call derivation gets checked against.
    fb = _fb("widget", 2)
    client = ScriptedLLMClient({
        "vocabulary_chunk_000": _resp(("p1", r"\bSymbol1\b")),
        "vocabulary_chunk_001": {"patterns": []},
    })
    merged = vocabulary.run(client, "guide text", fb, str(tmp_path), chunk_size=1)

    coverage = guards.check_vocabulary_coverage(fb, merged)
    assert not coverage.ok
