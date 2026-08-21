"""Second acceptance case: does the packaged CLI reproduce the study's
known result on targetA_small (OpenAI v0->v1), a migration the tool's
prompts/schemas were never shaped around? Real API calls, real cost, real
minutes -- run explicitly:

    pytest tests/test_acceptance_targeta.py -m acceptance -s

To also record a cassette for the offline replay tier:

    APIDRIFT_RECORD_CASSETTE=tests/cassettes/targeta_small/cassette.json \\
        pytest tests/test_acceptance_targeta.py -m acceptance -s

Ground truth: GT_TARGET_A_SMALL, the study's own independently-verified
13-site answer key (rule_test/blind_vocab_experiment/gt.py) -- not
something built for this test. Same metric as the Target B case: every GT
site must appear in PROPOSE or FLAG-UNCERTAIN (surfaced recall), and every
PROPOSE entry must be a real GT site (precision).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "rule_test", "blind_vocab_experiment"))
from gt import GT_TARGET_A_SMALL  # noqa: E402

from apidrift import pipeline
from apidrift.llm import AnthropicLLMClient, RecordingLLMClient
from conftest import TARGET_A_GUIDE_PATH, make_targeta_small_repo, report_usage, score_against


@pytest.mark.acceptance
def test_targeta_small_reproduces_study_numbers(tmp_path):
    repo_root = make_targeta_small_repo(tmp_path)
    workdir = str(tmp_path / "workdir")

    real_client = AnthropicLLMClient(model="claude-opus-5")
    cassette_target = os.environ.get("APIDRIFT_RECORD_CASSETTE")
    client = RecordingLLMClient(real_client, cassette_target) if cassette_target else real_client

    result = pipeline.run(
        repo_root=repo_root,
        guide_path=TARGET_A_GUIDE_PATH,
        workdir=workdir,
        client=client,
        chunk_size=40,
    )

    surfaced_recall, precision, missed, false_positives = score_against(result["expanded"], GT_TARGET_A_SMALL)
    report_usage(real_client)

    print(f"\nsurfaced recall: {surfaced_recall:.1%}  precision: {precision:.1%}")
    if missed:
        print(f"MISSED (not in PROPOSE or FLAG-UNCERTAIN): {sorted(missed)}")
    if false_positives:
        print(f"FALSE POSITIVES (in PROPOSE, not GT): {sorted(false_positives)}")

    assert surfaced_recall == 1.0, f"surfaced recall {surfaced_recall:.1%}, missed: {sorted(missed)}"
    assert precision == 1.0, f"precision {precision:.1%}, false positives: {sorted(false_positives)}"
