"""Real acceptance test for fix generation on Target A (OpenAI v0.x ->
v1.x), mirroring test_acceptance_fixgen_targetb.py. Real API calls
(detection + fix generation), real cost, real minutes -- run explicitly:

    pytest tests/test_acceptance_fixgen_targeta.py -m acceptance -s

To also record a cassette:

    APIDRIFT_RECORD_CASSETTE=tests/cassettes/targeta_small/fixgen_cassette.json \\
        pytest tests/test_acceptance_fixgen_targeta.py -m acceptance -s

Ground truth: rule_test/fix_generation_experiment/fix_ground_truth_targetA.md
-- unlike Target B's answer key (built by the study's own author),
this one did not exist before this test suite; it was derived by a fresh,
walled-off agent given only the migration spec and read access to the 4
repos, with no access to apidrift/ or this pipeline's own fixgen prompt --
per the same isolated-construction discipline the rest of this project
uses for anything that grades a detector/generator against itself.

Two of the 13 sites (A9, A11) are a real, non-mechanical stress case the
answer key's own notes flag explicitly: their correct required text is
contingent on the client variable name introduced ~40 lines away at a
separate confirmed site (A8, A10) -- well outside fixgen.py's own
DEFAULT_CONTEXT_RADIUS (8 lines) for either site individually. Whether the
model still lands on the same name (all 13 sites share one fix-gen call
here, since 13 < fixgen's default chunk size of 15, so it has cross-site
visibility within that one call even without wide per-site context) is a
real, unadjusted test of the current implementation, not a known-good case
-- the context radius was fixed before this answer key existed and is not
being tuned to make this pass.
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
from fixgen_scoring import print_score_report, score_fixgen

_FIXGEN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "rule_test", "fix_generation_experiment")

# Fixed id -> (file, line) order, exactly as dictated to the blind
# ground-truth agent (see the prompt this test's own commit message
# references) -- GT_TARGET_A_SMALL is a set, so its iteration order can't
# be relied on to reconstruct this mapping; it's pinned here explicitly and
# cross-checked against the set below at collection time.
_ID_ORDER = [
    ("A1",  ("TomaszRewak_MAGI/ai.py", 6)),
    ("A2",  ("TomaszRewak_MAGI/ai.py", 7)),
    ("A3",  ("TomaszRewak_MAGI/ai.py", 51)),
    ("A4",  ("TomaszRewak_MAGI/ai.py", 52)),
    ("A5",  ("TomaszRewak_MAGI/ai.py", 64)),
    ("A6",  ("TomaszRewak_MAGI/ai.py", 65)),
    ("A7",  ("franalgaba_chatgpt-telegram-bot-serverless/app.py", 41)),
    ("A8",  ("batuhantoker_Flask-OpenAI-Chatbot/app.py", 8)),
    ("A9",  ("batuhantoker_Flask-OpenAI-Chatbot/app.py", 48)),
    ("A10", ("g0ldencybersec_sus_params/PoC.py", 7)),
    ("A11", ("g0ldencybersec_sus_params/PoC.py", 11)),
    ("A12", ("g0ldencybersec_sus_params/PoC.py", 192)),
    ("A13", ("g0ldencybersec_sus_params/PoC.py", 201)),
]

assert {key for _, key in _ID_ORDER} == GT_TARGET_A_SMALL, (
    "_ID_ORDER in this test drifted from gt.py's GT_TARGET_A_SMALL -- fix the mapping above"
)


def _required_by_key():
    import json
    with open(os.path.join(_FIXGEN_DIR, "fix_ground_truth_targetA_required.json")) as f:
        required_by_id = json.load(f)
    return {key: required_by_id[site_id] for site_id, key in _ID_ORDER}


@pytest.mark.acceptance
def test_targeta_small_fixgen_reproduces_answer_key(tmp_path):
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
        force=True,
        skip_fix_generation=False,
        verify_install=True,
    )

    # Printed immediately after the run, before any assertion below can
    # abort the test -- these calls are billed regardless of what the
    # scoring finds, so the cost must not go unreported on a failure.
    report_usage(real_client)

    # Detection's own recall/precision bar is test_acceptance_targeta.py's
    # job, not this test's -- printed for context, not hard-asserted, so
    # this test measures fix-gen quality on whatever detection actually
    # handed it this run rather than being blocked by unrelated noise.
    surfaced_recall, precision, missed, false_positives = score_against(result["expanded"], GT_TARGET_A_SMALL)
    print(f"\ndetection this run: surfaced recall {surfaced_recall:.1%}  precision {precision:.1%}")
    if missed:
        print(f"  GT sites not surfaced at all this run (not sent to fix-gen): {sorted(missed)}")
    if false_positives:
        print(f"  detection false positive(s) fed to fix-gen as if confirmed: {sorted(false_positives)}")

    flagged_keys = {(i["file"], i["line"]) for i in result["expanded"]["flag_uncertain"]}
    gt_in_flag_uncertain = GT_TARGET_A_SMALL & flagged_keys
    if gt_in_flag_uncertain:
        print(f"  GT site(s) surfaced via FLAG-UNCERTAIN this run (not sent to fix-gen): "
              f"{sorted(gt_in_flag_uncertain)}")

    required = _required_by_key()
    scored = score_fixgen(result["fixgen_expanded"], required)
    print_score_report("targetA_small", scored, result["verification_report"])

    n_known_sent = scored["n_sites"] - scored["counts"]["unknown-site"]
    assert n_known_sent >= 10, (
        f"only {n_known_sent}/13 known GT sites reached fix-gen this run -- too few to "
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
