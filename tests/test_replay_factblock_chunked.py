"""Offline replay tier for the cassette test_acceptance_factblock_chunked.py
records: two derivations of the same guide content (rule_test/
factblock_experiment/guide_redis_unified_responses.md), one genuinely
chunked (6 real `##` sections) and one collapsed to a single whole-guide
chunk (same facts, headings stripped -- see conftest.strip_markdown_headings).
No network, no LLM calls, no cost.

Structural checks only (chunk counts, validation, non-empty results).
Content equivalence between the two derivations -- whether any fact
present in one is genuinely absent from the other, as opposed to just
differently worded or numbered -- isn't something an exact-match assertion
can judge reliably (the two are separate LLM calls), so that comparison
is done by hand against both outputs and rule_test/factblock_experiment/
ground_truth_factblock.md as the tiebreaker, and reported separately
rather than asserted here.
"""
import os

import pytest

from apidrift.llm import ReplayLLMClient
from apidrift.stages import factblock
from conftest import FACTBLOCK_REDIS_CASSETTE_PATH, FACTBLOCK_REDIS_GUIDE_PATH, strip_markdown_headings


@pytest.mark.skipif(not os.path.isfile(FACTBLOCK_REDIS_CASSETTE_PATH),
                     reason="no recorded cassette yet -- run test_acceptance_factblock_chunked.py "
                            "with APIDRIFT_RECORD_CASSETTE set to produce one")
def test_multi_chunk_replay_produces_six_chunks_and_merges(tmp_path):
    with open(FACTBLOCK_REDIS_GUIDE_PATH, encoding="utf-8") as f:
        guide_text = f.read()
    client = ReplayLLMClient(FACTBLOCK_REDIS_CASSETTE_PATH)
    workdir = str(tmp_path / "wd")

    result = factblock.run(client, guide_text, workdir, chunk_token_budget=6000)

    chunk_files = sorted(n for n in os.listdir(os.path.join(workdir, "factblock")) if n.startswith("chunk_"))
    assert len(chunk_files) == 6
    assert result["package_name"] == "redis"
    assert len(result["facts"]) > 0
    assert os.path.isfile(os.path.join(workdir, "factblock", "merged.json"))


@pytest.mark.skipif(not os.path.isfile(FACTBLOCK_REDIS_CASSETTE_PATH),
                     reason="no recorded cassette yet -- run test_acceptance_factblock_chunked.py "
                            "with APIDRIFT_RECORD_CASSETTE set to produce one")
def test_single_chunk_replay_produces_one_chunk_and_merges(tmp_path):
    with open(FACTBLOCK_REDIS_GUIDE_PATH, encoding="utf-8") as f:
        guide_text = f.read()
    stripped_text = strip_markdown_headings(guide_text)
    client = ReplayLLMClient(FACTBLOCK_REDIS_CASSETTE_PATH)
    workdir = str(tmp_path / "wd")

    result = factblock.run(client, stripped_text, workdir, chunk_token_budget=6000)

    chunk_files = sorted(n for n in os.listdir(os.path.join(workdir, "factblock")) if n.startswith("chunk_"))
    assert len(chunk_files) == 1
    assert result["package_name"] == "redis"
    assert len(result["facts"]) > 0
