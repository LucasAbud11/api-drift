import re

from apidrift.reposafe import RepoReader
from apidrift.stages import prefilter


def _make_repo(tmp_path, files):
    root = tmp_path / "repo"
    root.mkdir()
    for relpath, content in files.items():
        p = root / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return str(root)


def test_stage_a_keeps_relevant_drops_irrelevant(tmp_path):
    repo = _make_repo(tmp_path, {
        "used.py": "import mcp\nfrom mcp.server.fastmcp import FastMCP\nx = FastMCP()\n",
        "unrelated.py": "x = FastMCP()\n",  # never imports mcp -- structurally irrelevant
    })
    reader = RepoReader(repo)
    candidates = [
        {"file": "used.py", "line": 3, "snippet": "x = FastMCP()"},
        {"file": "unrelated.py", "line": 1, "snippet": "x = FastMCP()"},
    ]
    pattern = prefilter.build_relevance_pattern("mcp")
    kept, dropped, log = prefilter.stage_a_file_relevance(candidates, reader, pattern)
    assert [c["file"] for c in kept] == ["used.py"]
    assert [c["file"] for c in dropped] == ["unrelated.py"]
    assert log[0]["stage"] == "A"


def test_stage_a_keeps_transitively_relevant_file(tmp_path):
    repo = _make_repo(tmp_path, {
        "wrapper.py": "import mcp\nclass Wrapper:\n    pass\n",
        "user.py": "from wrapper import Wrapper\nw = Wrapper()\n",
    })
    reader = RepoReader(repo)
    candidates = [{"file": "user.py", "line": 2, "snippet": "w = Wrapper()"}]
    pattern = prefilter.build_relevance_pattern("mcp")
    kept, dropped, _ = prefilter.stage_a_file_relevance(candidates, reader, pattern)
    assert [c["file"] for c in kept] == ["user.py"]
    assert dropped == []


def test_stage_b_drops_comment_only_match(tmp_path):
    repo = _make_repo(tmp_path, {
        "f.py": "x = 1  # FastMCP is mentioned only here\n",
    })
    reader = RepoReader(repo)
    candidates = [{"file": "f.py", "line": 1, "snippet": "x = 1  # FastMCP is mentioned only here"}]
    vocab_regex = re.compile(r"FastMCP")
    kept, dropped, log = prefilter.stage_b_comment_and_docstring(candidates, reader, vocab_regex)
    assert kept == []
    assert len(dropped) == 1
    assert log[0]["rule"] == "comment"


def test_stage_b_drops_docstring_match(tmp_path):
    repo = _make_repo(tmp_path, {
        "f.py": '"""Uses FastMCP under the hood."""\nx = 1\n',
    })
    reader = RepoReader(repo)
    candidates = [{"file": "f.py", "line": 1, "snippet": '"""Uses FastMCP under the hood."""'}]
    vocab_regex = re.compile(r"FastMCP")
    kept, dropped, log = prefilter.stage_b_comment_and_docstring(candidates, reader, vocab_regex)
    assert kept == []
    assert log[0]["rule"] == "docstring"


def test_stage_b_keeps_real_code_match(tmp_path):
    repo = _make_repo(tmp_path, {
        "f.py": "x = FastMCP()\n",
    })
    reader = RepoReader(repo)
    candidates = [{"file": "f.py", "line": 1, "snippet": "x = FastMCP()"}]
    vocab_regex = re.compile(r"FastMCP")
    kept, dropped, _ = prefilter.stage_b_comment_and_docstring(candidates, reader, vocab_regex)
    assert len(kept) == 1
    assert dropped == []


def test_stage_c_collapses_byte_identical_duplicates():
    candidates = [
        {"file": "f.py", "line": 5, "snippet": "await ctx.error(msg)"},
        {"file": "f.py", "line": 19, "snippet": "await ctx.error(msg)"},
        {"file": "f.py", "line": 33, "snippet": "await ctx.error(msg)"},
        {"file": "f.py", "line": 5, "snippet": "different line"},
    ]
    # second file/line-5 entry is a distinct snippet -- won't collapse with the trio
    candidates[3]["file"] = "g.py"
    reps, expansion_map, log = prefilter.stage_c_collapse_duplicates(candidates)
    assert len(reps) == 2
    trio_rep = next(r for r in reps if r["file"] == "f.py")
    assert trio_rep["duplicate_count"] == 3
    assert trio_rep["duplicate_lines"] == [5, 19, 33]
    assert expansion_map[("f.py", 5)][-1]["line"] == 33


def test_full_pipeline_never_drops_on_ambiguity(tmp_path):
    """A generic string-literal match (not a comment, not a docstring) must
    survive stage B -- absence from any whitelist is not proof of
    irrelevance."""
    repo = _make_repo(tmp_path, {
        "f.py": 'import mcp\nlog.info("touching FastMCP indirectly")\n',
    })
    reader = RepoReader(repo)
    candidates = [{"file": "f.py", "line": 2,
                   "snippet": 'log.info("touching FastMCP indirectly")'}]
    pattern = prefilter.build_relevance_pattern("mcp")
    vocab_regex = re.compile(r"FastMCP")
    kept, _, _, _ = prefilter.run_pipeline(candidates, reader, pattern, vocab_regex=vocab_regex)
    assert len(kept) == 1
