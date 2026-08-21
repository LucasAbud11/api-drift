"""Structural proof, not a convention: the pipeline's repo-touching stages
run against a chmod-555 (read-only) repo copy. If any code path attempted
a write, this would raise PermissionError and fail the test -- success
here means no write attempt happened, and that the OS would have refused
one even if the code tried.
"""
import os
import re
import stat

from apidrift.reposafe import RepoReader, assert_no_overlap
from apidrift.stages import grep, prefilter


def _chmod_tree_readonly(root):
    for dirpath, dirnames, filenames in os.walk(root):
        for fn in filenames:
            os.chmod(os.path.join(dirpath, fn), stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        os.chmod(dirpath, stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP)


def test_pipeline_stages_never_write_to_a_readonly_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("import mcp\nfrom mcp.server.fastmcp import FastMCP\nx = FastMCP()\n")
    (repo / "b.py").write_text("x = 1  # unrelated\n")
    _chmod_tree_readonly(str(repo))

    try:
        reader = RepoReader(str(repo))
        patterns = {"fastmcp": r"FastMCP"}
        candidates = grep.find_candidates(reader, patterns)
        assert len(candidates) >= 1

        pattern = prefilter.build_relevance_pattern("mcp")
        vocab_regex = re.compile("|".join(patterns.values()))
        kept, expansion_map, stats, droplog = prefilter.run_pipeline(
            candidates, reader, pattern, vocab_regex=vocab_regex,
        )
        assert stats["start"] >= 1
    finally:
        # restore write perms so pytest / tmp_path cleanup can remove the tree
        for dirpath, dirnames, filenames in os.walk(str(repo)):
            os.chmod(dirpath, stat.S_IRWXU)
            for fn in filenames:
                os.chmod(os.path.join(dirpath, fn), stat.S_IRUSR | stat.S_IWUSR)


def test_reposafe_has_no_write_capability():
    """Type-level check: RepoReader exposes no attribute whose name looks
    like a write/delete/rename operation. Cheap and direct -- if someone
    adds a write_file() method later, this fails immediately."""
    forbidden_substrings = ("write", "delete", "remove", "rename", "unlink", "rmdir", "move")
    members = [m for m in dir(RepoReader) if not m.startswith("_")]
    for m in members:
        lower = m.lower()
        assert not any(f in lower for f in forbidden_substrings), (
            f"RepoReader.{m} looks like a write-capable method -- "
            f"the read-only guarantee depends on this class never having one"
        )


def test_repo_and_workdir_overlap_is_rejected(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    nested_workdir = repo / ".api-drift-run"
    try:
        assert_no_overlap(str(repo), str(nested_workdir))
        assert False, "expected ValueError for nested workdir"
    except ValueError:
        pass

    try:
        assert_no_overlap(str(repo), str(repo))
        assert False, "expected ValueError for identical paths"
    except ValueError:
        pass

    sibling_workdir = tmp_path / "workdir"
    assert_no_overlap(str(repo), str(sibling_workdir))  # should not raise
