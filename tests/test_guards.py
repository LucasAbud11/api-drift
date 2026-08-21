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
