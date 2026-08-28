from apidrift import guards


def test_thin_factblock_is_flagged():
    guide = "The `Foo` class moves to `Bar`. `baz()` is removed. `qux` gains a `timeout` kwarg."
    factblock = {"package_name": "x", "facts": [{"number": 1, "text": "Something changed."}]}
    result = guards.check_factblock_coverage(guide, factblock)
    assert not result.ok
    assert "coverage ratio" in result.reason
    assert "Foo" in result.report


def test_empty_factblock_is_flagged():
    guide = "The `Foo` class moves to `Bar`."
    factblock = {"package_name": "x", "facts": []}
    result = guards.check_factblock_coverage(guide, factblock)
    assert not result.ok
    assert "zero facts" in result.reason


def test_thorough_factblock_passes():
    guide = "The `Foo` class moves to `Bar`. `baz()` is removed."
    factblock = {
        "package_name": "x",
        "facts": [
            {"number": 1, "text": "`Foo` renamed to `Bar`."},
            {"number": 2, "text": "`baz()` removed entirely."},
        ],
    }
    result = guards.check_factblock_coverage(guide, factblock)
    assert result.ok


def test_candidate_count_ceiling():
    patterns = {"p1": r"foo"}
    candidates = [{"file": f"f{i}.py", "line": 1, "_pattern": "p1"} for i in range(3000)]
    result = guards.check_vocabulary_yield(patterns, candidates, max_total=2000)
    assert not result.ok
    assert "3000" in result.reason


def test_single_pattern_dominance():
    patterns = {"generic": r"\.error\(", "specific": r"FooBar\("}
    candidates = [{"file": f"f{i}.py", "line": 1, "_pattern": "generic"} for i in range(500)]
    candidates += [{"file": "g.py", "line": 1, "_pattern": "specific"} for _ in range(3)]
    result = guards.check_vocabulary_yield(patterns, candidates, max_total=10000)
    assert not result.ok
    assert "generic" in result.reason


def test_balanced_vocabulary_passes():
    patterns = {"p1": r"foo", "p2": r"bar", "p3": r"baz"}
    candidates = (
        [{"file": f"f{i}.py", "line": 1, "_pattern": "p1"} for i in range(20)]
        + [{"file": f"f{i}.py", "line": 1, "_pattern": "p2"} for i in range(20)]
        + [{"file": f"f{i}.py", "line": 1, "_pattern": "p3"} for i in range(20)]
    )
    result = guards.check_vocabulary_yield(patterns, candidates)
    assert result.ok


def test_vocabulary_coverage_catches_a_dropped_fact():
    factblock = {
        "package_name": "widget",
        "facts": [
            {"number": 1, "text": "`widget.Foo` is renamed to `widget.Bar`."},
            {"number": 2, "text": "`widget.Baz.qux()` gains a required `timeout=` kwarg."},
        ],
    }
    vocabulary = {"patterns": {"p1": r"\bwidget\.Foo\b"}}
    result = guards.check_vocabulary_coverage(factblock, vocabulary)
    assert not result.ok
    assert "2" in result.reason
    assert "qux" in result.report


def test_vocabulary_coverage_escape_anchored_pattern_registers_as_covering():
    # Regression for the escape-fusion bug: a pattern whose only
    # alternatives are \b-anchored must still register as covering the
    # identifier it names. Pre-fix, `_pattern_tokens(r"\bMcpError\b|\bMCPError\b")`
    # produced only {"bmcperror"} -- the leading \b's own "b" fused onto
    # the identifier -- so this pattern could never cover any fact
    # regardless of vocabulary quality.
    factblock = {
        "package_name": "mcp",
        "facts": [{"number": 1, "text": "`McpError` was renamed to `MCPError`."}],
    }
    vocabulary = {"patterns": {"p8_mcperror": r"\bMcpError\b|\bMCPError\b"}}
    result = guards.check_vocabulary_coverage(factblock, vocabulary)
    assert result.ok
    rows = guards.compute_fact_pattern_coverage(factblock, vocabulary)
    assert rows[0]["status"] == "covered"


def test_vocabulary_coverage_underscore_insensitive_match():
    # The guide names a wire-style command with no separator; the actual
    # Python method inserts an underscore in a different place. A plain
    # \b-bounded match would miss this -- the fix must not regress it.
    factblock = {
        "package_name": "widget",
        "facts": [{"number": 1, "text": "`CLIENT TRACKINGINFO` changes shape."}],
    }
    vocabulary = {"patterns": {"p1": r"\.client_tracking_info\s*\("}}
    result = guards.check_vocabulary_coverage(factblock, vocabulary)
    assert result.ok


def test_vocabulary_coverage_does_not_falsely_cover_via_package_name_substring():
    # Real bug: `Mcp-Param-*` tokenizes to ["mcp", "param"], and under
    # substring matching "mcp" is contained in "fastmcp", "mcpserver",
    # "mcperror", etc, so almost every MCP-family pattern falsely
    # registered as covering almost every fact. `fastmcp` has nothing to
    # do with parameter headers -- it must not count as coverage.
    factblock = {
        "package_name": "mcp",
        "facts": [{"number": 1, "text": "`Mcp-Param-*` headers change shape."}],
    }
    vocabulary = {"patterns": {
        "p1_fastmcp": r"\bFastMCP\b",
        "p24_pydsett": r"mcpserver\.settings",
        "p78_websocket": r"mcperror\.WebSocket",
    }}
    result = guards.check_vocabulary_coverage(factblock, vocabulary)
    assert not result.ok
    assert "1" in result.reason


def test_vocabulary_coverage_still_covers_via_a_real_non_package_token():
    # Same fact as above, but a pattern that actually references the
    # non-package-name token (`param`) must still register as covering
    # it -- the fix must not become so strict it can never match.
    factblock = {
        "package_name": "mcp",
        "facts": [{"number": 1, "text": "`Mcp-Param-*` headers change shape."}],
    }
    vocabulary = {"patterns": {
        "p1_fastmcp": r"\bFastMCP\b",
        "p_param_header": r"Mcp-Param-",
    }}
    result = guards.check_vocabulary_coverage(factblock, vocabulary)
    assert result.ok


def test_vocabulary_coverage_package_name_alone_is_not_coverage():
    # A fact whose only identifier IS the bare package name has no real
    # signal to search for -- a pattern that merely imports/references
    # the package must not count as covering it. Before
    # classify_span_searchability's package_self_reference category, this
    # landed in "uncovered" (a real gap the guard would flag, requiring
    # --force). That was itself the wrong verdict for a different reason
    # -- the token is excluded as a matchable candidate on both sides
    # (see _pattern_tokens' `exclude`), so the fact could never reach
    # "covered" no matter what patterns existed. It's "unsearchable" now:
    # not falsely covered, but also not a real gap the guard should
    # block a run over.
    factblock = {
        "package_name": "mcp",
        "facts": [{"number": 1, "text": "`mcp` behavior changes in an unspecified way."}],
    }
    vocabulary = {"patterns": {"p1": r"import mcp"}}
    rows = guards.compute_fact_pattern_coverage(factblock, vocabulary)
    assert rows[0]["status"] == "unsearchable"
    assert rows[0]["spans"][0]["category"] == "package_self_reference"

    result = guards.check_vocabulary_coverage(factblock, vocabulary)
    assert result.ok


def test_compute_fact_pattern_coverage_row_shape_is_uniform():
    # Every row carries the same keys regardless of status -- "spans" is
    # always a list (empty where there's nothing to match), never absent,
    # so a persistence caller can treat every row identically.
    factblock = {
        "package_name": "widget",
        "facts": [
            {"number": 1, "text": "CONFIRMED UNCHANGED: `widget.Foo` is not affected."},
            {"number": 2, "text": "No concrete symbol named here, just process notes."},
            {"number": 3, "text": "`widget.Bar` is renamed to `widget.Baz`."},
        ],
    }
    vocabulary = {"patterns": {"p1": r"\bwidget\.Bar\b"}}
    rows = guards.compute_fact_pattern_coverage(factblock, vocabulary)
    assert [r["number"] for r in rows] == [1, 2, 3]
    for row in rows:
        assert set(row.keys()) == {"number", "text", "status", "spans"}
        assert isinstance(row["spans"], list)
    assert rows[0]["status"] == "non_breaking"
    assert rows[0]["spans"] == []
    assert rows[1]["status"] == "no_identifier"
    assert rows[1]["spans"] == []
    assert rows[2]["status"] == "partial"  # `widget.Bar` covered, `widget.Baz` is not
    covering_by_span = {s["span"]: s["covering"] for s in rows[2]["spans"]}
    assert covering_by_span["widget.Bar"] == ["p1"]
    assert covering_by_span["widget.Baz"] == []


def test_compute_fact_pattern_coverage_uncovered_vs_covered():
    factblock = {
        "package_name": "widget",
        "facts": [
            {"number": 1, "text": "`widget.Foo` is renamed to `widget.Bar`."},
            {"number": 2, "text": "`widget.Baz.qux()` gains a required `timeout=` kwarg."},
        ],
    }
    vocabulary = {"patterns": {"p1": r"\bwidget\.Foo\b", "p2": r"\bwidget\.Bar\b"}}
    rows = guards.compute_fact_pattern_coverage(factblock, vocabulary)
    by_number = {r["number"]: r for r in rows}
    assert by_number[1]["status"] == "covered"
    assert by_number[2]["status"] == "uncovered"


def test_check_vocabulary_coverage_delegates_to_compute_and_render():
    # check_vocabulary_coverage's report/verdict must be exactly what
    # compute_fact_pattern_coverage + render_fact_pattern_coverage_report
    # produce independently -- it's a thin wrapper now, not a second copy
    # of the matching logic.
    factblock = {
        "package_name": "widget",
        "facts": [
            {"number": 1, "text": "`widget.Foo` is renamed to `widget.Bar`."},
            {"number": 2, "text": "`widget.Baz.qux()` gains a required `timeout=` kwarg."},
        ],
    }
    vocabulary = {"patterns": {"p1": r"\bwidget\.Foo\b"}}
    rows = guards.compute_fact_pattern_coverage(factblock, vocabulary)
    expected_report = guards.render_fact_pattern_coverage_report(rows)

    result = guards.check_vocabulary_coverage(factblock, vocabulary)
    assert result.report == expected_report
    assert not result.ok
    assert "2" in result.reason


def test_vocabulary_coverage_skips_non_breaking_and_shape_facts():
    factblock = {
        "package_name": "widget",
        "facts": [
            {"number": 1, "text": "CONFIRMED UNCHANGED: `widget.Foo` is not affected."},
            {"number": 2, "text": "Shape changes from `(a, b)` to `[a, b]`."},
            {"number": 3, "text": "No concrete symbol named here, just process notes."},
        ],
    }
    result = guards.check_vocabulary_coverage(factblock, {"patterns": {"p1": r"\bwidget\b"}})
    assert result.ok


# --- searchability pre-filter (classify_span_searchability) ---
#
# Roughly a third of the spans check_vocabulary_coverage used to flag as
# "no covering pattern" were never Python source tokens to begin with --
# guide prose ABOUT Python source (a version constraint, a JSON-RPC error
# number, a bare builtin type name, an HTTP header spelled with hyphens, a
# `tools/list` wire path, a full quoted runtime-symptom sentence). No
# pattern could meaningfully cover these, so counting their absence as a
# gap measured an unreachable target. These tests pin each category this
# classifier recognizes, and -- just as important -- pin the shapes that
# must NOT be caught by it: a real, bespoke identifier, however plain,
# stays "searchable" even if no sane vocabulary would ever write a
# pattern for it (e.g. `ClientSession`), because that restraint is a
# vocabulary judgment (vocabulary_system.md's anti-genericity rule), not
# a searchability property this filter is allowed to launder away.
#
# A bare Python BUILTIN name (`TypeError`, `isinstance`, ...) is the one
# deliberate exception to "no name-based special case," added for
# gap-fill: it's not that no pattern COULD match `TypeError` -- it's that
# doing so would match every line in the host codebase already using the
# language's own exception type, so sending it to gap-fill as if it were
# a real vocabulary gap would burn a call chasing something no vocabulary
# should ever cover. Still structural, not identity-based: the test is
# membership in `dir(builtins)`, a mechanical, enumerable fact about the
# span's exact text, not a hand-picked list of "words we don't like."

def test_classify_version_specifiers_as_unsearchable():
    for span in ["<3", ">=2.11,<3", ">=0.27.1,<1.0.0", '"mcp>=2,<3"', '"mcp==1.28.1"', ">=310"]:
        assert guards.classify_span_searchability(span) == "version_specifier", span


def test_classify_numeric_error_codes_as_unsearchable():
    for span in ["-32021", "-32600", "0", "32600", "408"]:
        assert guards.classify_span_searchability(span) == "numeric_code", span


def test_classify_bare_builtin_types_as_unsearchable():
    for span in ["str", "float", "float | None", "str | None", "bool"]:
        assert guards.classify_span_searchability(span) == "builtin_type", span


def test_classify_wire_header_tokens_as_unsearchable():
    for span in ["Mcp-Name", "MCP-Protocol-Version", "Last-Event-ID", "Mcp-Method"]:
        assert guards.classify_span_searchability(span) == "wire_header_token", span


def test_classify_method_paths_as_unsearchable():
    for span in ["tools/list", "/authorize", "/etc/passwd", "notifications/tools/list_changed"]:
        assert guards.classify_span_searchability(span) == "method_path", span


def test_classify_date_literals_as_unsearchable():
    for span in ["2026-07-28", "2025-11-25"]:
        assert guards.classify_span_searchability(span) == "date_literal", span


def test_classify_quoted_runtime_symptoms_as_unsearchable_prose():
    # The dangerous category: `TypeError` itself must stay searchable (see
    # the negative test below) but a full symptom sentence quoting it is
    # prose, not a grep target -- classified by SHAPE (multiple words,
    # at least one lowercase), never by checking for "TypeError" by name.
    for span in [
        '"Method not found"',
        '"Invalid request parameters"',
        'TypeError: Invalid "auth" argument',
        "AttributeError: 'Server' object has no attribute 'list_tools'",
    ]:
        assert guards.classify_span_searchability(span) == "multiword_prose", span


def test_classify_does_not_flag_dotted_paths():
    assert guards.classify_span_searchability("mcp.server.mcpserver") is None
    assert guards.classify_span_searchability("redis.Redis") is None


def test_classify_does_not_flag_dunder_names():
    assert guards.classify_span_searchability("__init__") is None
    assert guards.classify_span_searchability("__all__") is None


def test_classify_does_not_flag_names_with_digits():
    assert guards.classify_span_searchability("sha256") is None
    assert guards.classify_span_searchability("utf8") is None
    assert guards.classify_span_searchability("mcp2") is None


def test_classify_does_not_flag_single_letter_identifiers():
    assert guards.classify_span_searchability("T") is None
    assert guards.classify_span_searchability("_") is None
    assert guards.classify_span_searchability("x") is None


def test_classify_does_not_flag_a_bare_identifier_by_name():
    # A real, bespoke identifier stays searchable no matter how plain --
    # `ClientSession` remains a real (if deliberately unaddressed)
    # candidate in the covered/partial/uncovered accounting, exactly the
    # same as any other bare word a vocabulary chose not to write a
    # pattern for. This is NOT the same claim as "no name is ever
    # special-cased" -- see test_classify_bare_python_builtins_as_unsearchable
    # directly below for the one deliberate exception.
    assert guards.classify_span_searchability("ClientSession") is None
    assert guards.classify_span_searchability("RootModel") is None


def test_classify_bare_python_builtins_as_unsearchable():
    for span in ["TypeError", "ValueError", "RuntimeError", "isinstance", "AttributeError"]:
        assert guards.classify_span_searchability(span) == "python_builtin", span


def test_classify_does_not_flag_dunder_names_as_python_builtin():
    # dir(builtins) includes module dunders (__name__, __loader__, ...) --
    # excluded deliberately, since a dunder is a structurally different
    # kind of identifier a guide might legitimately want a pattern for.
    assert guards.classify_span_searchability("__init__") is None
    assert guards.classify_span_searchability("__loader__") is None


def test_classify_package_self_reference_as_unsearchable():
    assert guards.classify_span_searchability("mcp", package_name="mcp") == "package_self_reference"
    assert guards.classify_span_searchability("MCP", package_name="mcp") == "package_self_reference"
    # Underscore-insensitive, same normalization compute_fact_pattern_coverage
    # already applies to both a fact's tokens and a pattern's own tokens.
    assert guards.classify_span_searchability("my_pkg", package_name="my_pkg") == "package_self_reference"
    assert guards.classify_span_searchability("mypkg", package_name="my_pkg") == "package_self_reference"
    # A different word, or no package_name given at all, must not match.
    assert guards.classify_span_searchability("mcpserver", package_name="mcp") is None
    assert guards.classify_span_searchability("mcp") is None


def test_classify_does_not_flag_real_code_constructs():
    assert guards.classify_span_searchability("@mcp.tool()") is None
    assert guards.classify_span_searchability("initialize()") is None
    assert guards.classify_span_searchability("encoding=None") is None
    assert guards.classify_span_searchability('redis.Redis(host="localhost", port=6379)') is None


def test_classify_does_not_flag_type_expressions_with_brackets():
    # A real type expression must never be misread as prose just because
    # it contains bracket-adjacent words, and a union of real (non-
    # builtin) class names is a legitimate, if currently ungrepped,
    # symbol reference -- not builtin-type noise.
    assert guards.classify_span_searchability("Callable[..., Any]") is None
    assert guards.classify_span_searchability("Callable[[], str | None]") is None
    assert guards.classify_span_searchability(
        "AcceptedElicitation[T] | DeclinedElicitation | CancelledElicitation"
    ) is None


def test_compute_fact_pattern_coverage_unsearchable_status_and_exclusion():
    # A fact whose only identifier span is structurally unsearchable gets
    # its own status -- it must never count as "uncovered"/"partial", and
    # must never trip check_vocabulary_coverage's guard, since there is no
    # pattern a vocabulary could plausibly write for it.
    factblock = {
        "package_name": "widget",
        "facts": [
            {"number": 1, "text": "`pydantic` floor raised to `>=2.12` in v2."},
        ],
    }
    vocabulary = {"patterns": {"p1": r"\bpydantic\b"}}
    rows = guards.compute_fact_pattern_coverage(factblock, vocabulary)
    by_span = {s["span"]: s for s in rows[0]["spans"]}
    assert by_span[">=2.12"]["searchable"] is False
    assert by_span[">=2.12"]["category"] == "version_specifier"
    assert by_span[">=2.12"]["covering"] == []
    # `pydantic` is covered, and the only other span is unsearchable, so
    # the fact is "covered" overall -- not "partial".
    assert rows[0]["status"] == "covered"

    result = guards.check_vocabulary_coverage(factblock, vocabulary)
    assert result.ok


def test_compute_fact_pattern_coverage_all_spans_unsearchable():
    factblock = {
        "package_name": "widget",
        "facts": [
            {"number": 1, "text": "The error code is `-32021`."},
        ],
    }
    rows = guards.compute_fact_pattern_coverage(factblock, {"patterns": {}})
    assert rows[0]["status"] == "unsearchable"
    assert rows[0]["spans"][0]["searchable"] is False

    # A fact with no searchable spans left is not a coverage gap -- the
    # guard must not fire on it.
    result = guards.check_vocabulary_coverage(factblock, {"patterns": {}})
    assert result.ok


def test_compute_fact_pattern_coverage_mixed_unsearchable_and_uncovered():
    # One unsearchable span and one real, genuinely-uncovered span: status
    # must be driven by the real span alone ("uncovered"), not "partial" --
    # the unsearchable span contributes nothing either way.
    factblock = {
        "package_name": "widget",
        "facts": [
            {"number": 1, "text": "`widget.Baz` now requires `>=2.12`."},
        ],
    }
    rows = guards.compute_fact_pattern_coverage(factblock, {"patterns": {}})
    assert rows[0]["status"] == "uncovered"


def test_compute_fact_pattern_coverage_python_builtin_only_is_unsearchable():
    # A fact whose only identifier span is a bare Python builtin must land
    # in "unsearchable", not "uncovered" -- gap-fill's whole reason for
    # existing is a per-fact target list, and a fact like this one is not
    # a real target: no vocabulary should ever write a standalone
    # `TypeError` pattern.
    factblock = {
        "package_name": "widget",
        "facts": [
            {"number": 1, "text": "Calling the loader with a bad path now raises "
                                   "`TypeError` instead of returning nothing."},
        ],
    }
    rows = guards.compute_fact_pattern_coverage(factblock, {"patterns": {}})
    assert rows[0]["status"] == "unsearchable"
    by_span = {s["span"]: s for s in rows[0]["spans"]}
    assert by_span["TypeError"]["category"] == "python_builtin"


def test_compute_fact_pattern_coverage_package_self_reference_only_is_unsearchable():
    # A fact whose only identifier span is the bare package name itself
    # can never reach "covered" (the token is excluded as a matchable
    # candidate on both sides -- see _pattern_tokens' `exclude`), so it
    # must not be counted as an "uncovered" gap either.
    factblock = {
        "package_name": "widget",
        "facts": [
            {"number": 1, "text": "`widget` now requires Python 3.10 or newer."},
        ],
    }
    rows = guards.compute_fact_pattern_coverage(factblock, {"patterns": {"p1": r"\bwidget\b"}})
    assert rows[0]["status"] == "unsearchable"
    assert rows[0]["spans"][0]["category"] == "package_self_reference"
