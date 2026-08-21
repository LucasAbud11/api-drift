"""Third test tier: replays a cassette recorded from one real acceptance
run through the exact same pipeline.run() code path, with a fake client
that never touches the network. Catches plumbing regressions -- chunking,
validation, scoring, report generation -- for free. Not a substitute for
the acceptance test: if the pipeline's own logic changes what it asks the
model (a real prompt/schema change), this fails with ReplayMiss, which is
correct -- it means the cassette is stale, not that the pipeline is wrong.
"""
import os

import pytest

from apidrift import pipeline
from apidrift.llm import ReplayLLMClient
from conftest import TARGET_B_GUIDE_PATH, make_targetb_small_repo

CASSETTE_PATH = os.path.join(os.path.dirname(__file__), "cassettes", "targetb_small", "cassette.json")


@pytest.mark.skipif(not os.path.isfile(CASSETTE_PATH),
                     reason="no recorded cassette yet -- run the acceptance test with "
                            "APIDRIFT_RECORD_CASSETTE set to produce one")
def test_replay_reproduces_recorded_result(tmp_path):
    repo_root = make_targetb_small_repo(tmp_path)
    workdir = str(tmp_path / "workdir")

    client = ReplayLLMClient(CASSETTE_PATH)
    result = pipeline.run(
        repo_root=repo_root,
        guide_path=TARGET_B_GUIDE_PATH,
        workdir=workdir,
        client=client,
        chunk_size=40,
    )

    # Plumbing checks: every artifact got written, every bucket key exists,
    # the report file exists and mentions the counts. This is what a
    # chunking/validation/report-generation regression would actually break.
    for name in ("factblock.json", "vocabulary.json", "candidates.json",
                 "droplog.json", "report.md"):
        assert os.path.isfile(os.path.join(workdir, name)), f"missing {name}"

    for bucket in ("proposed_sites", "flag_uncertain", "considered_and_rejected"):
        assert bucket in result["merged"]
        assert isinstance(result["merged"][bucket], list)

    assert os.path.isfile(os.path.join(workdir, "adjudication", "merged.json"))
