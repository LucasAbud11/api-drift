"""Offline tests for the gap-fill two-bucket contract (validate.py):
shape checks shared with validate_vocabulary via _validate_pattern_regex,
and the two checks specific to gap-fill's narrower, more exploitable
prompt -- max distinct symbols per pattern (hard-fail) and id-reads-as-
an-abbreviation (warning only, collected via the `warnings` list param,
not raised -- see validate_gapfill_dict's docstring). No network, no LLM
calls.
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
# Anti-Goodhart: BOTH checks are warnings now, neither hard-fails.
#
# The symbol cap started by counting every `|` in the regex, which
# conflated match CONTEXT with target SYMBOL and rejected a pattern
# legitimately anchoring certifi/truststore to both an import statement
# and a quoted string (5 `|`, 2 real symbols) as "5 branches." Counting
# distinct symbols instead fixed that case -- but a FOURTH real firing
# showed the same conflation one level down: a dotted/qualified path
# written with a spelling variant (`mcp.types.jsonrpc` vs
# `mcp_types.jsonrpc`) gets split into path components and each one
# counted as an independent symbol. Four real firings, four false
# positives, zero real Goodhart catches -- both checks are now
# non-blocking; see the block comment above GAPFILL_MAX_SYMBOLS in
# validate.py for the full account.
# ---------------------------------------------------------------------

def _checks(warnings):
    return {w["check"] for w in warnings}


def test_pattern_within_symbol_cap_has_no_symbol_cap_warning():
    warnings = []
    validate.validate_gapfill_dict(
        _result(patterns=[
            {"name": "gf_clientsecret", "regex": r"\b(client_secret_basic|client_secret_post|private_key_jwt)\b"},
        ]),
        warnings=warnings,
    )
    assert "symbol_cap" not in _checks(warnings)


def test_pattern_over_symbol_cap_warns_but_does_not_raise():
    # The exact Goodhart shape this cap exists to catch: one broad
    # alternation whose branches are unrelated target facts' own
    # identifiers, satisfying the coverage checker for all of them at
    # once without a real per-symbol pattern for any of them. Still just
    # a warning -- must not raise.
    kitchen_sink = r"\b(ClientSession|RootModel|TypeAliasType|ErrorData)\b"
    warnings = []
    result = validate.validate_gapfill_dict(
        _result(patterns=[{"name": "gf_misc", "regex": kitchen_sink}]),
        warnings=warnings,
    )
    assert result["patterns"][0]["name"] == "gf_misc"
    assert "symbol_cap" in _checks(warnings)
    cap_warning = next(w for w in warnings if w["check"] == "symbol_cap")
    assert "4 distinct symbols" in cap_warning["reason"]


def test_two_symbols_in_two_syntactic_contexts_each_has_no_symbol_cap_warning():
    # The second real false-positive, the exact rejected regex: covers
    # exactly two symbols (certifi, truststore), each named twice for
    # two match contexts (an import line, a quoted string) -- 5 `|` in
    # the regex, 2 distinct symbols, well under the cap of 3. (The id
    # check may separately flag this id -- a 2-symbol id is its own
    # known limitation, see the id-check section below -- this test is
    # scoped to the symbol cap specifically.)
    regex = r"""(?:import|from)\s+(?:certifi|truststore)\b|["'](?:certifi|truststore)["']"""
    warnings = []
    validate.validate_gapfill_dict(
        _result(patterns=[{"name": "gf_certtruststore", "regex": regex}]),
        warnings=warnings,
    )
    assert "symbol_cap" not in _checks(warnings)


def test_one_symbol_in_four_syntactic_contexts_has_no_warnings_at_all():
    # One real target symbol, matched via an attribute access, a call,
    # an import, and a quoted string -- 4 distinct syntactic shapes, 1
    # distinct symbol, and an id that names it outright. Must not warn
    # on either check regardless of how many `|` or contexts that takes.
    warnings = []
    validate.validate_gapfill_dict(
        _result(patterns=[{
            "name": "gf_rootmodel",
            "regex": r"\.RootModel\b|\bRootModel\(|from\s+\S+\s+import\s+RootModel|[\"']RootModel[\"']",
        }]),
        warnings=warnings,
    )
    assert warnings == []


def test_symbol_cap_ignores_import_from_keywords():
    # `import`/`from` are match-shape vocabulary, not target symbols --
    # a pattern anchoring 3 real symbols to an import statement must not
    # be penalized, on the symbol cap specifically, for also containing
    # those two keywords.
    warnings = []
    validate.validate_gapfill_dict(
        _result(patterns=[{
            "name": "gf_threeimports",
            "regex": r"(?:import|from)\s+(?:widgetone|widgettwo|widgetthree)\b",
        }]),
        warnings=warnings,
    )
    assert "symbol_cap" not in _checks(warnings)


def test_dotted_path_with_spelling_variant_warns_but_does_not_raise():
    # The fourth real false-positive, the exact rejected regex: covers
    # two targets (`mcp.types.jsonrpc`, `mcp.types.methods`) written as
    # a dotted path with a spelling variant (`.types`/`_types`) -- the
    # extractor splits the path into components (mcp, types, _types,
    # jsonrpc, methods) and counts each as a symbol. Still just a
    # warning -- must not raise.
    regex = r"\bmcp(?:\.types|_types)\.(?:jsonrpc|methods)\b|from\s+mcp[\w.]*\s+import[^\n]*\b(?:jsonrpc|methods)\b"
    warnings = []
    result = validate.validate_gapfill_dict(
        _result(patterns=[{"name": "gf_mcptypes", "regex": regex}]),
        warnings=warnings,
    )
    assert result["patterns"][0]["name"] == "gf_mcptypes"
    assert "symbol_cap" in _checks(warnings)


# ---------------------------------------------------------------------
# Anti-Goodhart: id-reads-as-an-abbreviation -- a WARNING, not a
# hard-fail. Real gap-fill output broke the check's premise (an id
# abbreviates ONE symbol) twice at real cost: a correct id for an
# alternation of related symbols often names the shared concept instead
# of any one member (e.g. 'gf_sslcertenv' for
# `SSL_CERT_FILE`/`SSL_CERT_DIR` -- neither contains "env").
# ---------------------------------------------------------------------

def test_id_not_reading_as_an_abbreviation_warns_but_does_not_raise():
    # An id naming a symbol that's simply absent from its own regex --
    # not an abbreviation of anything the pattern actually matches.
    # Must not raise: this is exactly the shape the check flags, not
    # blocks.
    result = validate.validate_gapfill_dict(_result(patterns=[
        {"name": "gf_requestid", "regex": r"\bClientSession\s*\("},
    ]))
    assert result["patterns"][0]["name"] == "gf_requestid"


def test_id_not_reading_as_an_abbreviation_is_recorded_in_warnings():
    warnings = []
    validate.validate_gapfill_dict(
        _result(patterns=[{"name": "gf_requestid", "regex": r"\bClientSession\s*\("}]),
        warnings=warnings,
    )
    assert len(warnings) == 1
    assert warnings[0]["pattern"] == "gf_requestid"
    assert warnings[0]["regex"] == r"\bClientSession\s*\("
    assert warnings[0]["check"] == "id_check"
    assert "abbreviation" in warnings[0]["reason"]


def test_group_naming_id_over_related_alternation_warns_but_does_not_raise():
    # The real false positive that motivated downgrading this check: a
    # correct id naming the shared concept across an alternation of
    # related symbols, where the concept word appears in NEITHER member
    # ('env' is in neither `SSL_CERT_FILE` nor `SSL_CERT_DIR`). The
    # matcher still can't tell this apart from a genuinely vague id --
    # that's the whole reason this is a warning and not a hard-fail:
    # must be recorded for a human to see, must NOT stop the run.
    warnings = []
    result = validate.validate_gapfill_dict(
        _result(patterns=[{"name": "gf_sslcertenv", "regex": r"\b(SSL_CERT_FILE|SSL_CERT_DIR)\b"}]),
        warnings=warnings,
    )
    assert result["patterns"][0]["name"] == "gf_sslcertenv"
    assert len(warnings) == 1
    assert warnings[0]["pattern"] == "gf_sslcertenv"


def test_generic_id_over_multi_symbol_alternation_warns_for_every_pattern():
    # A vague, category-style id that can't be traced back to what the
    # pattern actually matches, tried against EVERY branch of a
    # multi-symbol alternation -- still just a warning now, recorded for
    # each pattern that trips it.
    kitchen_sink = r"\b(ClientSession|RootModel|title)\b"
    warnings = []
    validate.validate_gapfill_dict(
        _result(patterns=[
            {"name": "gf_misc", "regex": kitchen_sink},
        ]),
        warnings=warnings,
    )
    assert len(warnings) == 1
    warnings2 = []
    validate.validate_gapfill_dict(
        _result(patterns=[{"name": "gf_pattern1", "regex": kitchen_sink}]),
        warnings=warnings2,
    )
    assert len(warnings2) == 1


def test_id_check_warnings_defaults_to_discarded():
    # No `warnings` list given -- must not raise AttributeError or
    # anything else; the flag is just dropped.
    validate.validate_gapfill_dict(_result(patterns=[
        {"name": "gf_misc", "regex": r"\bRootModel\b"},
    ]))


def test_id_check_rejects_a_remainder_too_short_to_mean_anything():
    # A one-character abbreviation is "in order somewhere" in nearly any
    # word -- too short to plausibly be naming a specific symbol. Still
    # just a warning.
    warnings = []
    validate.validate_gapfill_dict(
        _result(patterns=[{"name": "gf_r", "regex": r"\bRootModel\b"}]),
        warnings=warnings,
    )
    assert len(warnings) == 1


def test_id_referencing_its_symbol_passes():
    # A single-word symbol, id equals it whole.
    validate.validate_gapfill_dict(_result(patterns=[
        {"name": "gf_rootmodel", "regex": r"\bRootModel\b"},
    ]))
    # A two-word CamelCase symbol, id truncates each word.
    validate.validate_gapfill_dict(_result(patterns=[
        {"name": "gf_clientsess", "regex": r"\bClientSession\s*\("},
    ]))
    # A three-word CamelCase symbol abbreviated to its word-initial
    # letters -- the real false positive this check was rewritten for:
    # no long contiguous run of 'ResourceTemplateReference' contains
    # 'restmplref', but it plainly abbreviates
    # Resource+Template+Reference in order.
    validate.validate_gapfill_dict(_result(patterns=[
        {"name": "gf_restmplref", "regex": r"\bResourceTemplateReference\b"},
    ]))
    # A four-word CamelCase symbol with an acronym-shaped first word.
    validate.validate_gapfill_dict(_result(patterns=[
        {"name": "gf_oauthclientinfo", "regex": r"\bOAuthClientInformationFull\b"},
    ]))
    # A snake_case symbol.
    validate.validate_gapfill_dict(_result(patterns=[
        {"name": "gf_clientsecretbasic", "regex": r"\bclient_secret_basic\b"},
    ]))
    validate.validate_gapfill_dict(_result(patterns=[
        {"name": "gf_secbasic", "regex": r"\bclient_secret_basic\b"},
    ]))


def test_id_check_ignores_short_regex_syntax_noise():
    # A pattern's regex source can contain short alnum runs that are pure
    # regex syntax residue (e.g. a repetition count) -- these must not
    # count as tokens the id needs to reference (and must not warn).
    warnings = []
    validate.validate_gapfill_dict(
        _result(patterns=[{"name": "gf_rootmodel", "regex": r"\bRootModel[s]{1,2}\b"}]),
        warnings=warnings,
    )
    assert warnings == []
