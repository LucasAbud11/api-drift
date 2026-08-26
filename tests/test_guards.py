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
    # the package must not count as covering it.
    factblock = {
        "package_name": "mcp",
        "facts": [{"number": 1, "text": "`mcp` behavior changes in an unspecified way."}],
    }
    vocabulary = {"patterns": {"p1": r"import mcp"}}
    result = guards.check_vocabulary_coverage(factblock, vocabulary)
    assert not result.ok


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
