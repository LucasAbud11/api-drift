"""Offline tests for chunked fact-block derivation (apidrift/stages/
factblock.py): section splitting, oversized-section subdivision, resume
skipping completed chunks, global renumbering, package_name consensus/
conflict, and --dry-run making no API calls. No network, no LLM calls --
a scripted fake client answers whichever chunks actually need deriving.
"""
import json
import os

import pytest

from apidrift import cli, llm
from apidrift.stages import factblock

GUIDE_WITH_SECTIONS = """Preamble note: this guide covers the Foo SDK v1->v2 migration.
It assumes you already have v1 installed.

## Client construction

`foo.Client()` is renamed to `foo.NewClient()`.

## Response shape

`.get()` now returns a `Response` object instead of a plain dict.

## Removed functions

`foo.legacy_call()` is removed entirely with no drop-in replacement.
"""


# ---------------------------------------------------------------------
# Fake client
# ---------------------------------------------------------------------

class ScriptedLLMClient:
    """Keyed by a substring of the chunk's own heading (found in
    user_text) rather than a fixed stage prefix, since each chunk of a
    multi-section guide gets a different heading and needs a different
    scripted answer."""

    def __init__(self, by_heading_substring, default=None):
        self._by_heading_substring = by_heading_substring
        self._default = default
        self.calls = []

    def complete(self, stage, system_text, user_text, schema, cache_system=False,
                 cache_ttl="5m", max_tokens=8000, effort="high"):
        self.calls.append({"stage": stage, "user_text": user_text, "max_tokens": max_tokens,
                            "usage": {"input_tokens": 100, "output_tokens": 50,
                                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}})
        for substring, response in self._by_heading_substring.items():
            if substring in user_text:
                return response() if callable(response) else response
        if self._default is not None:
            return self._default() if callable(self._default) else self._default
        raise AssertionError(f"no scripted response for user_text: {user_text[:200]!r}")


def _fb(package_name, texts):
    return {"package_name": package_name,
            "facts": [{"number": i + 1, "text": t} for i, t in enumerate(texts)]}


# ---------------------------------------------------------------------
# Section splitting
# ---------------------------------------------------------------------

def test_plan_chunks_splits_on_top_level_headings():
    preamble, chunks = factblock.plan_chunks(GUIDE_WITH_SECTIONS, chunk_token_budget=6000)

    assert "Preamble note" in preamble
    assert "## Client construction" not in preamble  # preamble stops before the first heading

    assert [c["heading"] for c in chunks] == [
        "Client construction", "Response shape", "Removed functions",
    ]
    # Each chunk's own text starts at its heading line and carries the
    # section's real content -- nothing split mid-section.
    assert chunks[0]["text"].startswith("## Client construction")
    assert "foo.NewClient()" in chunks[0]["text"]
    assert "Response` object" in chunks[1]["text"]
    assert "legacy_call" in chunks[2]["text"]


def test_plan_chunks_reconstructs_guide_text_exactly():
    """Preamble + every chunk's text, concatenated in order, must equal
    the original guide text -- nothing dropped, nothing duplicated,
    nothing reordered."""
    preamble, chunks = factblock.plan_chunks(GUIDE_WITH_SECTIONS, chunk_token_budget=6000)
    reconstructed = preamble + "".join(c["text"] for c in chunks)
    assert reconstructed == GUIDE_WITH_SECTIONS


def test_plan_chunks_falls_back_to_whole_guide_when_no_h2_headings():
    text = "Just a flat guide with no `##` headings anywhere in it."
    preamble, chunks = factblock.plan_chunks(text, chunk_token_budget=6000)
    assert preamble == ""
    assert len(chunks) == 1
    assert chunks[0]["text"] == text


# ---------------------------------------------------------------------
# Oversized section subdivision
# ---------------------------------------------------------------------

def test_plan_chunks_splits_oversized_section_on_h3_subheadings():
    big_section = (
        "## Everything about responses\n\n"
        "Intro prose for this section, before any subsection.\n\n"
        "### GET responses\n\n" + ("x" * 5000) + "\n\n"
        "### SET responses\n\n" + ("y" * 5000) + "\n\n"
    )
    guide = "Preamble.\n\n" + big_section + "## A small section\n\nsmall.\n"

    preamble, chunks = factblock.plan_chunks(guide, chunk_token_budget=2000)

    headings = [c["heading"] for c in chunks]
    assert "Everything about responses > GET responses" in headings
    assert "Everything about responses > SET responses" in headings
    assert "A small section" in headings  # small section stays one whole chunk

    get_chunk = next(c for c in chunks if c["heading"].endswith("GET responses"))
    # The oversized section's own intro prose (before its first ###)
    # is attached to the FIRST subsection chunk, not dropped.
    assert "Intro prose for this section" in get_chunk["text"]
    assert "x" * 5000 in get_chunk["text"]

    set_chunk = next(c for c in chunks if c["heading"].endswith("SET responses"))
    assert "Intro prose for this section" not in set_chunk["text"]  # only the first subchunk gets it
    assert "y" * 5000 in set_chunk["text"]


def test_plan_chunks_never_splits_mid_section_no_h3_to_split_on():
    """A `##` section too big for the budget, with no `###` subheadings
    at all, is kept whole rather than cut at an arbitrary offset."""
    text = "## One giant section\n\n" + ("z" * 50000) + "\n"
    preamble, chunks = factblock.plan_chunks(text, chunk_token_budget=100)
    assert len(chunks) == 1
    assert chunks[0]["text"] == text  # whole section, not truncated/split


# ---------------------------------------------------------------------
# Resume skipping completed chunks
# ---------------------------------------------------------------------

def test_resume_never_rederives_a_completed_chunk(tmp_path):
    guide = GUIDE_WITH_SECTIONS
    workdir = str(tmp_path / "workdir")
    fb_dir = os.path.join(workdir, "factblock")
    os.makedirs(fb_dir, exist_ok=True)

    # Pre-write chunk_000 (Client construction) as already done.
    with open(os.path.join(fb_dir, "chunk_000.json"), "w") as f:
        json.dump(_fb("foo", ["`foo.Client()` is renamed to `foo.NewClient()`."]), f)

    def _boom():
        raise AssertionError("chunk 0 should never be re-derived on resume")

    client = ScriptedLLMClient({
        "Client construction": _boom,
        "Response shape": _fb("foo", ["`.get()` now returns a `Response` object."]),
        "Removed functions": _fb("foo", ["`foo.legacy_call()` is removed entirely."]),
    })

    merged = factblock.run(client, guide, workdir, chunk_token_budget=6000)

    # Only the two NOT pre-written chunks triggered a real call.
    assert len(client.calls) == 2
    assert all("Client construction" not in c["user_text"] for c in client.calls)
    # But the pre-written chunk's fact still made it into the merge.
    assert any("NewClient" in f["text"] for f in merged["facts"])


def test_resumed_run_is_idempotent_on_a_second_call(tmp_path):
    """Running factblock.run() twice against the same workdir with a
    client that fails on any second call for the same chunk proves
    nothing gets re-derived the second time either."""
    guide = "## Only section\n\n`foo.old()` becomes `foo.new()`.\n"
    workdir = str(tmp_path / "workdir")

    call_count = {"n": 0}

    def _once():
        call_count["n"] += 1
        if call_count["n"] > 1:
            raise AssertionError("chunk was derived more than once")
        return _fb("foo", ["`foo.old()` becomes `foo.new()`."])

    client = ScriptedLLMClient({"Only section": _once})

    factblock.run(client, guide, workdir, chunk_token_budget=6000)
    merged_again = factblock.run(client, guide, workdir, chunk_token_budget=6000)

    assert call_count["n"] == 1
    assert len(merged_again["facts"]) == 1


# ---------------------------------------------------------------------
# Global renumbering
# ---------------------------------------------------------------------

def test_merge_renumbers_facts_globally_in_guide_order(tmp_path):
    guide = GUIDE_WITH_SECTIONS
    workdir = str(tmp_path / "workdir")

    client = ScriptedLLMClient({
        "Client construction": _fb("foo", ["fact A1", "fact A2"]),
        "Response shape": _fb("foo", ["fact B1"]),
        "Removed functions": _fb("foo", ["fact C1", "fact C2", "fact C3"]),
    })

    merged = factblock.run(client, guide, workdir, chunk_token_budget=6000)

    numbers = [f["number"] for f in merged["facts"]]
    assert numbers == [1, 2, 3, 4, 5, 6]
    texts_in_order = [f["text"] for f in merged["facts"]]
    assert texts_in_order == ["fact A1", "fact A2", "fact B1", "fact C1", "fact C2", "fact C3"]


def test_merge_carries_fact_text_through_verbatim(tmp_path):
    guide = "## Section\n\nbody\n"
    workdir = str(tmp_path / "workdir")
    verbatim_text = "`foo.bar()` changes from returning `int` to returning `str`, verbatim."
    client = ScriptedLLMClient({"Section": _fb("foo", [verbatim_text])})

    merged = factblock.run(client, guide, workdir, chunk_token_budget=6000)

    assert merged["facts"][0]["text"] == verbatim_text  # not paraphrased/rewritten


def test_merge_flags_exact_duplicate_facts_without_dropping_either(tmp_path):
    guide = ("## Section one\n\nbody one\n\n"
              "## Section two\n\nbody two\n")
    workdir = str(tmp_path / "workdir")
    dup_text = "`foo.shared()` is renamed to `foo.shared_v2()`."
    client = ScriptedLLMClient({
        "Section one": _fb("foo", [dup_text]),
        "Section two": _fb("foo", [dup_text, "a different fact"]),
    })

    merged = factblock.run(client, guide, workdir, chunk_token_budget=6000)

    assert len(merged["facts"]) == 3  # both copies kept, not deduplicated
    assert merged["duplicate_facts"] == [[1, 2]]  # global numbers of the two identical facts


# ---------------------------------------------------------------------
# package_name consensus and conflict hard-fail
# ---------------------------------------------------------------------

def test_package_name_consensus_from_mostly_blank_chunks(tmp_path):
    guide = GUIDE_WITH_SECTIONS
    workdir = str(tmp_path / "workdir")
    client = ScriptedLLMClient({
        "Client construction": _fb("foo", ["fact A"]),
        "Response shape": {"package_name": "", "facts": [{"number": 1, "text": "fact B"}]},
        "Removed functions": {"package_name": "", "facts": [{"number": 1, "text": "fact C"}]},
    })

    merged = factblock.run(client, guide, workdir, chunk_token_budget=6000)

    assert merged["package_name"] == "foo"


def test_package_name_conflict_hard_fails_naming_both(tmp_path):
    guide = ("## Section one\n\nbody one\n\n"
              "## Section two\n\nbody two\n")
    workdir = str(tmp_path / "workdir")
    client = ScriptedLLMClient({
        "Section one": _fb("foo", ["fact A"]),
        "Section two": _fb("bar", ["fact B"]),
    })

    with pytest.raises(ValueError, match="disagree on package_name") as exc_info:
        factblock.run(client, guide, workdir, chunk_token_budget=6000)

    assert "'bar'" in str(exc_info.value)
    assert "'foo'" in str(exc_info.value)


def test_chunk_with_no_facts_is_legal_and_contributes_nothing(tmp_path):
    """A section that's pure prose/overview must not hard-fail just for
    having zero facts -- only the MERGED block is required to be
    non-empty overall."""
    guide = ("## Overview\n\nJust background, no breaking changes here.\n\n"
              "## Real change\n\n`foo.old()` becomes `foo.new()`.\n")
    workdir = str(tmp_path / "workdir")
    client = ScriptedLLMClient({
        "Overview": {"package_name": "", "facts": []},
        "Real change": _fb("foo", ["`foo.old()` becomes `foo.new()`."]),
    })

    merged = factblock.run(client, guide, workdir, chunk_token_budget=6000)

    assert merged["package_name"] == "foo"
    assert len(merged["facts"]) == 1


# ---------------------------------------------------------------------
# --dry-run: no API calls
# ---------------------------------------------------------------------

def test_format_dry_run_report_is_pure_and_lists_every_chunk():
    lines = factblock.format_dry_run_report(GUIDE_WITH_SECTIONS, chunk_token_budget=6000,
                                             model="claude-opus-5")
    text = "\n".join(lines)
    assert "Client construction" in text
    assert "Response shape" in text
    assert "Removed functions" in text
    assert "Estimated total input tokens" in text
    assert "Estimated input-token cost" in text


def test_format_dry_run_report_without_model_skips_cost():
    lines = factblock.format_dry_run_report(GUIDE_WITH_SECTIONS, chunk_token_budget=6000, model=None)
    text = "\n".join(lines)
    assert "Estimated total input tokens" in text
    assert "cost" not in text.lower()


def test_cli_dry_run_makes_no_api_call_and_never_constructs_a_client(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

    def _boom(*a, **k):
        raise AssertionError("AnthropicLLMClient must never be constructed on --dry-run")
    monkeypatch.setattr(llm, "AnthropicLLMClient", _boom)
    monkeypatch.setattr(cli, "AnthropicLLMClient", _boom)

    guide_path = tmp_path / "guide.md"
    guide_path.write_text(GUIDE_WITH_SECTIONS)
    repo = tmp_path / "repo"
    repo.mkdir()

    # No ANTHROPIC_API_KEY set, and no client constructor reachable --
    # if the dry-run path touched either, this would raise/exit(1)
    # instead of printing the plan and returning cleanly.
    cli.main(["run", "--repo", str(repo), "--guide", str(guide_path), "--dry-run"])

    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "Client construction" in out
    assert "no API calls made" in out


def test_cli_dry_run_with_missing_guide_is_a_clean_stopped_line(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(SystemExit):
        cli.main(["run", "--repo", str(repo), "--guide", str(tmp_path / "nope.md"), "--dry-run"])

    assert "STOPPED" in capsys.readouterr().err


def test_cli_dry_run_with_factblock_flag_does_nothing_and_makes_no_claim(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    guide_path = tmp_path / "guide.md"
    guide_path.write_text(GUIDE_WITH_SECTIONS)
    factblock_path = tmp_path / "factblock.json"
    factblock_path.write_text(json.dumps(_fb("foo", ["a fact"])))

    cli.main(["run", "--repo", str(repo), "--guide", str(guide_path),
              "--factblock", str(factblock_path), "--dry-run"])

    out = capsys.readouterr().out
    assert "loaded from disk" in out
    assert "DRY RUN" not in out
