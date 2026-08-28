"""Offline tests for the gap-fill two-bucket contract (validate.py):
shape checks shared with validate_vocabulary via _validate_pattern_regex,
and the two checks specific to gap-fill's narrower, more exploitable
prompt -- max alternation branches and id-must-reference-symbol. No
network, no LLM calls.
"""
import pytest

from apidrift import validate


def _result(patterns=None, declined=None):
    return {"patterns": patterns or [], "declined": declined or []}


# ---------------------------------------------------------------------
# Two-bucket shape
# ---------------------------------------------------------------------

def test_missing_bucket_fails():
    with pytest.raises(ValueError, match="missing required top-level key 'declined'"):
        validate.validate_gapfill_dict({"patterns": []})
    with pytest.raises(ValueError, match="missing required top-level key 'patterns'"):
        validate.validate_gapfill_dict({"declined": []})


def test_both_buckets_empty_is_valid():
    validate.validate_gapfill_dict(_result())


def test_not_a_dict_fails():
    with pytest.raises(ValueError, match="not a JSON object"):
        validate.validate_gapfill_dict([])


def test_patterns_must_be_a_list():
    with pytest.raises(ValueError, match="'patterns' must be a list"):
        validate.validate_gapfill_dict({"patterns": {"gf_rootmodel": r"\bRootModel\b"}, "declined": []})


def test_malformed_pattern_entry_fails():
    with pytest.raises(ValueError, match="malformed"):
        validate.validate_gapfill_dict(_result(patterns=[{"name": "gf_rootmodel"}]))


def test_duplicate_pattern_id_within_one_pass_fails():
    with pytest.raises(ValueError, match="duplicate pattern id"):
        validate.validate_gapfill_dict(_result(patterns=[
            {"name": "gf_rootmodel", "regex": r"\bRootModel\b"},
            {"name": "gf_rootmodel", "regex": r"\bTypeAliasType\b"},
        ]))


# ---------------------------------------------------------------------
# declined bucket
# ---------------------------------------------------------------------

def test_declined_entry_missing_field_fails():
    with pytest.raises(ValueError, match="missing required field 'reason'"):
        validate.validate_gapfill_dict(_result(declined=[{"fact": 12, "span": "iss"}]))


def test_declined_fact_must_be_int():
    with pytest.raises(ValueError, match="'declined\\[0\\].fact' must be an int"):
        validate.validate_gapfill_dict(_result(declined=[
            {"fact": "12", "span": "iss", "reason": "3-char JWT claim key, too generic to grep for"},
        ]))


def test_declined_blank_reason_fails():
    with pytest.raises(ValueError, match="'declined\\[0\\].reason' is missing, null, or blank"):
        validate.validate_gapfill_dict(_result(declined=[{"fact": 12, "span": "iss", "reason": "  "}]))


def test_valid_declined_entry_passes():
    validate.validate_gapfill_dict(_result(declined=[
        {"fact": 12, "span": "iss", "reason": "3-char JWT claim key -- no qualifying "
                                                "class/call context stated by the guide."},
    ]))


# ---------------------------------------------------------------------
# Shared per-pattern checks (reused from validate_vocabulary)
# ---------------------------------------------------------------------

def test_pattern_that_does_not_compile_fails():
    with pytest.raises(ValueError, match="does not compile"):
        validate.validate_gapfill_dict(_result(patterns=[{"name": "gf_bad", "regex": r"\bRootModel\b("}]))


def test_bare_global_flag_fails():
    with pytest.raises(ValueError, match="bare global inline flag"):
        validate.validate_gapfill_dict(_result(patterns=[{"name": "gf_bad", "regex": r"(?i)\bRootModel\b"}]))


def test_bare_dotted_generic_call_fails():
    with pytest.raises(ValueError, match="unqualified method-call match"):
        validate.validate_gapfill_dict(_result(patterns=[{"name": "gf_bad", "regex": r"\.get\("}]))


# ---------------------------------------------------------------------
# Anti-Goodhart: max alternation branches
# ---------------------------------------------------------------------

def test_pattern_within_alternation_cap_passes():
    validate.validate_gapfill_dict(_result(patterns=[
        {"name": "gf_clientsecret", "regex": r"\b(client_secret_basic|client_secret_post|private_key_jwt)\b"},
    ]))


def test_pattern_over_alternation_cap_fails():
    # The exact Goodhart shape this cap exists to catch: one broad
    # alternation whose branches are unrelated target facts' own
    # identifiers, satisfying the coverage checker for all of them at
    # once without a real per-symbol pattern for any of them. Written in
    # the grouped `\b(A|B|C|D)\b` form this vocabulary's own existing
    # patterns already use -- the branches are nested inside one group,
    # not top-level alternatives, and the cap must still catch it.
    kitchen_sink = r"\b(ClientSession|RootModel|TypeAliasType|ErrorData)\b"
    with pytest.raises(ValueError, match="alternation branches"):
        validate.validate_gapfill_dict(_result(patterns=[{"name": "gf_misc", "regex": kitchen_sink}]))


def test_alternation_cap_counts_nested_pipes_too():
    # Exactly at the cap (3 branches) inside a nested, non-alternation-
    # named group -- must still pass, since it's genuinely under the cap.
    validate.validate_gapfill_dict(_result(patterns=[
        {"name": "gf_rootmodel", "regex": r"\bRootModel\((?:foo|bar|baz)\)"},
    ]))


def test_alternation_cap_ignores_escaped_literal_pipe():
    # `\|` is a literal pipe character in the matched text, not an
    # alternation operator -- must not inflate the branch count.
    validate.validate_gapfill_dict(_result(patterns=[
        {"name": "gf_rootmodel", "regex": r"\bRootModel\|v2\b"},
    ]))


# ---------------------------------------------------------------------
# Anti-Goodhart: id must reference the symbol it targets
# ---------------------------------------------------------------------

def test_id_referencing_its_symbol_passes():
    validate.validate_gapfill_dict(_result(patterns=[
        {"name": "gf_rootmodel", "regex": r"\bRootModel\b"},
    ]))
    # A truncated id must still pass -- neither direction of plain
    # substring containment holds once the 'gf_' stage prefix sits in
    # front of the truncation, which is exactly why this check uses
    # longest-common-substring instead of `in`.
    validate.validate_gapfill_dict(_result(patterns=[
        {"name": "gf_clientsess", "regex": r"\bClientSession\s*\("},
    ]))


def test_id_not_referencing_its_symbol_fails():
    # The other half of the same Goodhart shape: a vague, category-style
    # id ("gf_misc") that can't be traced back to what the pattern
    # actually matches -- exactly what a pattern optimizing for the
    # checker rather than naming a real symbol would look like.
    with pytest.raises(ValueError, match="id does not reference any recognizable word"):
        validate.validate_gapfill_dict(_result(patterns=[
            {"name": "gf_misc", "regex": r"\bRootModel\b"},
        ]))


def test_id_check_ignores_short_regex_syntax_noise():
    # A pattern's regex source can contain short alnum runs that are pure
    # regex syntax residue (e.g. a repetition count) -- these must not
    # count as "words" the id needs to reference.
    validate.validate_gapfill_dict(_result(patterns=[
        {"name": "gf_rootmodel", "regex": r"\bRootModel[s]{1,2}\b"},
    ]))
