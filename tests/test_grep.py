"""find_candidates' provenance contract: `_pattern` is a single
representative match (first, by iteration order); `_patterns` is the
full set. No API calls -- pure regex/filesystem, same as prefilter's
tests."""
from apidrift.reposafe import RepoReader
from apidrift.stages import grep


def _make_repo(tmp_path, files):
    for rel, content in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return RepoReader(str(tmp_path))


def test_single_pattern_match_records_both_fields_identically(tmp_path):
    reader = _make_repo(tmp_path, {"a.py": "from mcp.server.fastmcp import FastMCP\n"})
    patterns = {"p1_fastmcp": r"FastMCP"}
    candidates = grep.find_candidates(reader, patterns)
    assert len(candidates) == 1
    c = candidates[0]
    assert c["_pattern"] == "p1_fastmcp"
    assert c["_patterns"] == ["p1_fastmcp"]


def test_line_matching_two_patterns_records_the_full_set(tmp_path):
    # Line matches BOTH a bare-word pattern and a call-shape pattern --
    # the exact shape of the bug: pre-fix, only the first-iterated name
    # survived in the candidate; the second was silently discarded.
    reader = _make_repo(tmp_path, {"a.py": "x = widget.Foo.qux(timeout=5)\n"})
    patterns = {
        "p_foo": r"widget\.Foo\b",
        "p_qux_timeout": r"\.qux\s*\([^)]*timeout",
    }
    candidates = grep.find_candidates(reader, patterns)
    assert len(candidates) == 1
    c = candidates[0]
    assert set(c["_patterns"]) == {"p_foo", "p_qux_timeout"}
    # _pattern is one representative match, and must be a member of the
    # full set -- never a name that isn't actually one of the matches.
    assert c["_pattern"] in c["_patterns"]


def test_pattern_iteration_order_determines_the_representative_pattern(tmp_path):
    # dict insertion order controls which name `_pattern` picks -- pinned
    # explicitly so a future change to the selection rule is a visible,
    # intentional diff here, not a silent behavior change.
    reader = _make_repo(tmp_path, {"a.py": "x = widget.Foo.qux(timeout=5)\n"})
    patterns = {
        "p_qux_timeout": r"\.qux\s*\([^)]*timeout",
        "p_foo": r"widget\.Foo\b",
    }
    candidates = grep.find_candidates(reader, patterns)
    assert candidates[0]["_pattern"] == "p_qux_timeout"
    assert candidates[0]["_patterns"] == ["p_qux_timeout", "p_foo"]


def test_no_match_yields_no_candidate(tmp_path):
    reader = _make_repo(tmp_path, {"a.py": "x = 1  # unrelated\n"})
    candidates = grep.find_candidates(reader, {"p1": r"FastMCP"})
    assert candidates == []


def test_multiple_files_and_lines_each_get_their_own_full_set(tmp_path):
    reader = _make_repo(tmp_path, {
        "a.py": "import widget\nx = widget.Foo()\n",
        "b/b.py": "y = widget.Foo().qux(timeout=1)\n",
    })
    patterns = {"p_import": r"import widget", "p_foo": r"widget\.Foo\b", "p_qux": r"\.qux\("}
    candidates = grep.find_candidates(reader, patterns)
    by_line = {(c["file"], c["line"]): c for c in candidates}
    assert by_line[("a.py", 1)]["_patterns"] == ["p_import"]
    assert by_line[("a.py", 2)]["_patterns"] == ["p_foo"]
    assert set(by_line[("b/b.py", 1)]["_patterns"]) == {"p_foo", "p_qux"}
