"""Startup checks that run before any network call or repo/guide access.
Fail fast with one clear line -- never a raw SDK/filesystem traceback
surfacing from deep inside a stage.

check_inputs() covers --repo/--guide/--workdir and runs inside
pipeline.run() itself, so every caller (CLI, acceptance tests, replay
tests) gets it for free. check_api_key() is separate and CLI-only: it's
the one check tied to a specific client implementation
(AnthropicLLMClient), so pipeline.run() -- which only ever sees the
LLMClient interface -- has no business making it.
"""
import os

from .reposafe import assert_no_overlap


class PreflightError(Exception):
    """str(e) is the single line to show the user."""


def _nearest_existing_dir(path):
    path = os.path.abspath(path)
    while not os.path.isdir(path):
        parent = os.path.dirname(path)
        if parent == path:
            return path
        path = parent
    return path


def check_inputs(repo_root, guide_path, workdir):
    if not os.path.isdir(repo_root):
        raise PreflightError(f"--repo does not exist or is not a directory: {repo_root}")
    if not os.path.isfile(guide_path):
        raise PreflightError(f"--guide does not exist or is not a file: {guide_path}")
    if not os.access(guide_path, os.R_OK):
        raise PreflightError(f"--guide is not readable: {guide_path}")
    if os.path.getsize(guide_path) == 0:
        raise PreflightError(f"--guide is empty: {guide_path}")
    try:
        assert_no_overlap(repo_root, workdir)
    except ValueError as e:
        raise PreflightError(str(e)) from e
    nearest = _nearest_existing_dir(workdir)
    if not os.access(nearest, os.W_OK):
        raise PreflightError(
            f"--workdir is not writable (nearest existing directory {nearest} "
            f"is not writable): {workdir}"
        )


def check_api_key():
    """Doesn't replicate the SDK's full credential-resolution chain (an
    `ant auth login` OAuth profile also works and this won't detect
    that) -- it only catches the common case of a plain missing key
    before any work starts. A credential that's present but invalid
    still surfaces as a clear LLMCallError from the first real call
    (see llm.py), not a preflight failure."""
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise PreflightError(
            "ANTHROPIC_API_KEY is not set (ANTHROPIC_AUTH_TOKEN isn't either) -- "
            "export ANTHROPIC_API_KEY, or authenticate with `ant auth login`, "
            "before running api-drift."
        )
