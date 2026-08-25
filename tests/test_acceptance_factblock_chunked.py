"""Stage-1-only acceptance test: exercises factblock.run()'s multi-chunk
merge / global renumbering / duplicate-fact-flagging / package_name-
consensus path against a real guide with genuine `##` structure --
rule_test/factblock_experiment/guide_redis_unified_responses.md, 6
sections. Target A and Target B (the guides the rest of this suite uses)
both have zero `##`/`###` headings, so factblock.plan_chunks() always
returns them as a single whole-guide chunk regardless of
--factblock-chunk-size (see REPORT.md) -- neither exercises this path,
and this test doesn't touch either of them or their cassettes.

Real API calls, real cost, run explicitly:

    pytest tests/test_acceptance_factblock_chunked.py -m acceptance -s

To also record a cassette for the offline replay tier
(test_replay_factblock_chunked.py):

    APIDRIFT_RECORD_CASSETTE=tests/cassettes/factblock_redis_chunked/cassette.json \\
        pytest tests/test_acceptance_factblock_chunked.py -m acceptance -s

Derives the guide TWICE in one recording, into the one cassette above:
once as-is (6 real `##` sections -> 6 chunks) and once with the
`##`/`###` markers stripped out of the identical guide text (same facts,
same wording -- see conftest.strip_markdown_headings -- just no longer
parsed as section structure, so plan_chunks falls back to "whole guide,
one chunk"). Recording both into a single run/cassette is what lets the
offline replay tier compare a chunked and a single-chunk derivation of
the same underlying content for chunk-boundary fact loss.
"""
import os

import pytest

from apidrift.llm import AnthropicLLMClient, RecordingLLMClient
from apidrift.stages import factblock
from conftest import FACTBLOCK_REDIS_GUIDE_PATH, report_usage, strip_markdown_headings


@pytest.mark.acceptance
def test_chunked_and_single_chunk_derivations_recorded(tmp_path):
    with open(FACTBLOCK_REDIS_GUIDE_PATH, encoding="utf-8") as f:
        guide_text = f.read()
    stripped_text = strip_markdown_headings(guide_text)
    assert stripped_text != guide_text  # sanity: the guide really has headings to strip

    real_client = AnthropicLLMClient(model="claude-opus-5")
    cassette_target = os.environ.get("APIDRIFT_RECORD_CASSETTE")
    client = RecordingLLMClient(real_client, cassette_target) if cassette_target else real_client

    multi = factblock.run(client, guide_text, str(tmp_path / "multi"),
                           chunk_token_budget=6000, print_fn=print)
    single = factblock.run(client, stripped_text, str(tmp_path / "single"),
                            chunk_token_budget=6000, print_fn=print)

    report_usage(real_client)

    n_multi_chunks = len(os.listdir(os.path.join(tmp_path, "multi", "factblock"))) - 1  # minus merged.json
    n_single_chunks = len(os.listdir(os.path.join(tmp_path, "single", "factblock"))) - 1

    print(f"\nmulti-chunk:  {n_multi_chunks} chunk(s), {len(multi['facts'])} facts, "
          f"package={multi['package_name']!r}")
    print(f"single-chunk: {n_single_chunks} chunk(s), {len(single['facts'])} facts, "
          f"package={single['package_name']!r}")

    assert n_multi_chunks == 6, "the redis guide's ## structure changed -- update this test's expectations"
    assert n_single_chunks == 1, "stripping headings should always collapse to one whole-guide chunk"
    assert multi["package_name"] == "redis"
    assert single["package_name"] == "redis"
