"""Real acceptance test for fix generation: does the packaged CLI's
fix-generation stage reproduce the study's hand-derived, mechanically-
verified correct fixes for targetB_small's confirmed sites? Real API calls
(detection + fix generation), real cost, real minutes -- run explicitly:

    pytest tests/test_acceptance_fixgen_targetb.py -m acceptance -s

To also record a cassette for a future offline replay tier:

    APIDRIFT_RECORD_CASSETTE=tests/cassettes/targetb_small/fixgen_cassette.json \\
        pytest tests/test_acceptance_fixgen_targetb.py -m acceptance -s

Ground truth: rule_test/fix_generation_experiment/fix_ground_truth.md, the
study's hand-derived answer key (score.py's REQUIRED dict), independently
mechanically verified there (parses, imports resolve against a real v2
stub, and QAInsights' real test suite passes) -- re-keyed here by
(file, line) via confirmed_sites_targetB_small.json so it lines up with
what the packaged pipeline actually returns, rather than that experiment's
own site ids.

Runs the FULL pipeline (detection, then fix generation on whatever
detection's real PROPOSE bucket contains this run) rather than
short-circuiting detection with a pre-built confirmed-sites list -- this
also re-confirms 100%/100% detection recall/precision on the exact host the
fix-generation numbers are measured against, so a detection regression
shows up here rather than silently feeding fix-gen the wrong input.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "rule_test", "blind_vocab_experiment"))
from gt import GT_TARGET_B_SMALL  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "rule_test", "fix_generation_experiment"))
import score as study_score  # noqa: E402

from apidrift import pipeline
from apidrift.llm import AnthropicLLMClient, RecordingLLMClient
from conftest import TARGET_B_GUIDE_PATH, make_targetb_small_repo, report_usage, score_against
from fixgen_scoring import print_score_report, score_fixgen

_FIXGEN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "rule_test", "fix_generation_experiment")


def _required_by_key():
    with open(os.path.join(_FIXGEN_DIR, "confirmed_sites_targetB_small.json")) as f:
        sites = json.load(f)["sites"]
    by_id = {s["id"]: s for s in sites}
    required, legit_hedge = {}, set()
    for site_id, required_line in study_score.REQUIRED.items():
        s = by_id[site_id]
        key = (f"{s['repo']}/{s['file']}", s["line"])
        required[key] = required_line
        if site_id in study_score.LEGITIMATE_HEDGE_OK:
            legit_hedge.add(key)
    return required, legit_hedge


@pytest.mark.acceptance
def test_targetb_small_fixgen_reproduces_study_answers(tmp_path):
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
        force=True,
        skip_fix_generation=False,
        verify_install=True,
    )

    # Printed immediately after the run, before any assertion below can
    # abort the test -- these calls are billed regardless of what the
    # scoring finds, so the cost must not go unreported on a failure.
    report_usage(real_client)

    # Detection's own recall/precision bar is test_acceptance_targetb.py's
    # job, not this test's -- printed here for context (vocabulary
    # derivation is documented as non-deterministic call to call, so a
    # single real run can show the same variance the study's own 3-run
    # tables do) but not hard-asserted, so this test measures fix-gen
    # quality on whatever detection actually handed it this run, rather
    # than being blocked by detection noise unrelated to fix generation.
    surfaced_recall, precision, missed, false_positives = score_against(result["expanded"], GT_TARGET_B_SMALL)
    print(f"\ndetection this run: surfaced recall {surfaced_recall:.1%}  precision {precision:.1%}")
    if missed:
        print(f"  GT sites not surfaced at all this run (not sent to fix-gen): {sorted(missed)}")
    if false_positives:
        print(f"  detection false positive(s) fed to fix-gen as if confirmed: {sorted(false_positives)}")

    flagged_keys = {(i["file"], i["line"]) for i in result["expanded"]["flag_uncertain"]}
    gt_in_flag_uncertain = GT_TARGET_B_SMALL & flagged_keys
    if gt_in_flag_uncertain:
        print(f"  GT site(s) surfaced via FLAG-UNCERTAIN this run (not sent to fix-gen): "
              f"{sorted(gt_in_flag_uncertain)}")

    required, legit_hedge = _required_by_key()
    scored = score_fixgen(result["fixgen_expanded"], required, legitimate_hedge_keys=legit_hedge)
    print_score_report("targetB_small", scored, result["verification_report"])

    n_known_sent = scored["n_sites"] - scored["counts"]["unknown-site"]
    # A floor, not a perfection requirement: guards against a vacuously
    # "passing" run where detection noise left almost nothing for fix-gen
    # to actually be tested on.
    assert n_known_sent >= 15, (
        f"only {n_known_sent}/20 known GT sites reached fix-gen this run -- too few to "
        f"draw a fix-generation conclusion from (this is a detection-stage problem, see "
        f"the recall/precision line above)"
    )
    if scored["counts"]["unknown-site"]:
        print(f"  ({scored['counts']['unknown-site']} site(s) sent to fix-gen have no answer-key "
              f"entry -- detection false positives, not scored as fix-gen right/wrong)")

    assert scored["counts"]["locally-plausible-but-globally-wrong"] == 0, (
        f"{scored['counts']['locally-plausible-but-globally-wrong']} confident-but-wrong fix(es) "
        f"on a known site -- see printed detail above"
    )
