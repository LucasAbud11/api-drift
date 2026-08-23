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
from conftest import TARGET_B_GUIDE_PATH, make_targetb_small_repo, report_usage, score_against


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
        # This test's real bar is the GT-based recall/precision assertion
        # below, which is a stronger, empirical coverage signal than the
        # static vocabulary-coverage guard has access to -- force past a
        # guard stop so a real but non-fatal gap doesn't fail a test whose
        # actual pass criterion already accounts for it.
        force=True,
        # This test's bar is detection recall/precision only -- fix
        # generation is a separate, unmeasured stage here (own tests live in
        # test_fixgen.py) and would add real API cost with nothing this
        # test's assertions check.
        skip_fix_generation=True,
    )

    surfaced_recall, precision, missed, false_positives = score_against(result["expanded"], GT_TARGET_B_SMALL)
    report_usage(real_client)

    print(f"\nsurfaced recall: {surfaced_recall:.1%}  precision: {precision:.1%}")
    if missed:
        print(f"MISSED (not in PROPOSE or FLAG-UNCERTAIN): {sorted(missed)}")
    if false_positives:
        print(f"FALSE POSITIVES (in PROPOSE, not GT): {sorted(false_positives)}")

    assert surfaced_recall == 1.0, f"surfaced recall {surfaced_recall:.1%}, missed: {sorted(missed)}"
    assert precision == 1.0, f"precision {precision:.1%}, false positives: {sorted(false_positives)}"
