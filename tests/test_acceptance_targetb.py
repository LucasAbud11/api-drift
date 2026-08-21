"""THE required acceptance test: does the packaged CLI reproduce the
study's known result on targetB_small? Real API calls, real cost, real
minutes -- run explicitly:

    pytest tests/test_acceptance_targetb.py -m acceptance -s

To also record a cassette for the offline replay tier (test_replay_targetb.py):

    APIDRIFT_RECORD_CASSETTE=tests/cassettes/targetb_small/cassette.json \\
        pytest tests/test_acceptance_targetb.py -m acceptance -s

Ground truth: GT_TARGET_B_SMALL, the study's own independently-verified
20-site answer key (rule_test/blind_vocab_experiment/gt.py) -- not
something built for this test. Metric, matching REPORT.md's own
definitions for the Target B / 5-repo row (Precision 100%, surfaced Recall
100%): every GT site must appear in PROPOSE or FLAG-UNCERTAIN (surfaced
recall), and every PROPOSE entry must be a real GT site (precision).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "rule_test", "blind_vocab_experiment"))
from gt import GT_TARGET_B_SMALL  # noqa: E402

from apidrift import pipeline
from apidrift.llm import AnthropicLLMClient, RecordingLLMClient
from conftest import TARGET_B_GUIDE_PATH, make_targetb_small_repo


# claude-opus-5 pricing, $/1M tokens (Anthropic API, cached 2026-06-24):
# input $5.00, output $25.00, cache write $6.25 (1.25x input), cache read $0.50 (0.1x input)
_PRICE_PER_MTOK = {
    "input_tokens": 5.00,
    "output_tokens": 25.00,
    "cache_creation_input_tokens": 6.25,
    "cache_read_input_tokens": 0.50,
}


def _report_usage(client):
    totals = client.usage_totals
    cost = sum(totals[k] / 1_000_000 * _PRICE_PER_MTOK[k] for k in _PRICE_PER_MTOK)
    print(f"\ntoken usage: input={totals['input_tokens']} output={totals['output_tokens']} "
          f"cache_write={totals['cache_creation_input_tokens']} cache_read={totals['cache_read_input_tokens']}")
    print(f"total tokens: {sum(totals.values())}  estimated cost: ${cost:.4f}  "
          f"({len(client.calls)} API calls)")
    return totals, cost


def _score(expanded):
    # GT_TARGET_B_SMALL keys are "<repo-dir-name>/<relpath>" -- exactly what
    # RepoReader.list_py_files() produces when repo_root is the temp dir of
    # symlinks built by make_targetb_small_repo(), so no path massaging needed.
    proposed = {(i["file"], i["line"]) for i in expanded["proposed_sites"]}
    flagged = {(i["file"], i["line"]) for i in expanded["flag_uncertain"]}
    surfaced = proposed | flagged

    missed = GT_TARGET_B_SMALL - surfaced
    false_positives = proposed - GT_TARGET_B_SMALL

    surfaced_recall = 1.0 - len(missed) / len(GT_TARGET_B_SMALL)
    precision = 1.0 if not proposed else len(proposed - false_positives) / len(proposed)
    return surfaced_recall, precision, missed, false_positives


@pytest.mark.acceptance
def test_targetb_small_reproduces_study_numbers(tmp_path):
    repo_root = make_targetb_small_repo(tmp_path)
    workdir = str(tmp_path / "workdir")

    real_client = AnthropicLLMClient(model="claude-opus-5")
    cassette_target = os.environ.get("APIDRIFT_RECORD_CASSETTE")
    client = RecordingLLMClient(real_client, cassette_target) if cassette_target else real_client

    result = pipeline.run(
        repo_root=repo_root,
        guide_path=TARGET_B_GUIDE_PATH,
        workdir=workdir,
        client=client,
        chunk_size=40,
    )

    surfaced_recall, precision, missed, false_positives = _score(result["expanded"])
    _report_usage(real_client)

    print(f"\nsurfaced recall: {surfaced_recall:.1%}  precision: {precision:.1%}")
    if missed:
        print(f"MISSED (not in PROPOSE or FLAG-UNCERTAIN): {sorted(missed)}")
    if false_positives:
        print(f"FALSE POSITIVES (in PROPOSE, not GT): {sorted(false_positives)}")

    assert surfaced_recall == 1.0, f"surfaced recall {surfaced_recall:.1%}, missed: {sorted(missed)}"
    assert precision == 1.0, f"precision {precision:.1%}, false positives: {sorted(false_positives)}"
