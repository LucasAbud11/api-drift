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
