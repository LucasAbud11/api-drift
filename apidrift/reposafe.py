"""The only module allowed to touch a `--repo` path.

Structural guarantee, not a convention: this class exposes no write, no
delete, no rename -- there is no method on it that could mutate the target
repository, so no caller of it can either, by construction. Every stage
that needs repo content (grep, prefilter) takes a RepoReader, never a raw
path, and never calls `open()` on a repo path itself.

The workdir (run artifacts: factblock.json, candidates.json, droplog.json,
adjudication/*.json, report.md) is written by a completely separate path
(plain `open(..., "w")` calls in the stage modules, always joined against
`workdir`, never against anything that came from a RepoReader) -- so repo
paths and workdir paths never share a code path that could write.
"""
import os


class RepoReader:
    """Read-only view of a repository. No write/delete/rename method
    exists on this class -- that is the enforcement mechanism, not a
    docstring promise."""

    def __init__(self, repo_root):
        self.repo_root = os.path.abspath(repo_root)
        if not os.path.isdir(self.repo_root):
            raise ValueError(f"--repo path does not exist or is not a directory: {repo_root}")

    def list_py_files(self):
        """Relative paths (repo-root-relative, POSIX-style) of every .py
        file, skipping dotdirs (.git, .venv, etc)."""
        out = []
        for dirpath, dirnames, filenames in os.walk(self.repo_root, followlinks=True):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fn in filenames:
                if fn.endswith(".py"):
                    rel = os.path.relpath(os.path.join(dirpath, fn), self.repo_root)
                    out.append(rel.replace(os.sep, "/"))
        return sorted(out)

    def read_text(self, relpath):
        """Raises OSError if unreadable -- callers decide fail-open vs
        fail-closed per their own fail-safe rules; this method never
        swallows the error itself."""
        full = os.path.join(self.repo_root, relpath)
        with open(full, encoding="utf-8", errors="replace") as f:
            return f.read()

    def abspath(self, relpath):
        return os.path.join(self.repo_root, relpath)


def assert_no_overlap(repo_root, workdir_root):
    """Hard-fail if --repo and --workdir are the same directory or one
    contains the other. Without this check, a user pointing --workdir
    inside their repo would make "write only to workdir" accidentally mean
    "write into the repo" -- this closes that specific hole structurally,
    at startup, before any stage runs."""
    r = os.path.abspath(repo_root)
    w = os.path.abspath(workdir_root)
    if r == w or w.startswith(r + os.sep) or r.startswith(w + os.sep):
        raise ValueError(
            f"--repo ({r}) and --workdir ({w}) must not be the same directory "
            f"or nested inside each other -- the tool writes only to --workdir "
            f"and refuses to run if that guarantee could be violated by overlap."
        )
