"""Score the 3 entanglement adjudication runs against independently-derived GT.

GT was established by direct reading of the generated host (not by the
detector, not by the host-construction agent) -- see report.md for the
full per-file reasoning. Distinguishes three loss mechanisms instead of
conflating them:
  - grep_missed: never became a candidate at all (vocabulary gap)
  - prefilter_dropped: was a candidate, dropped by the hardened prefilter
  - reachable: survived to the agent; scored normally against its verdict
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(BASE), "scale_experiment"))
from validate_run import validate_run_file

GT = {
    ("src/opsmesh/server/base.py", 16),
    ("src/opsmesh/server/base.py", 24),
    ("src/opsmesh/server/context.py", 12),
    ("src/opsmesh/server/context.py", 13),
    # context.py:20 calls the locally-aliased get_context(); the authoritative
    # spec (adjudication_prompt_reduced_targetB.md fact 3) states
    # mcp.get_context() is REMOVED ENTIRELY in v2, not just relocated -- so
    # this call site's own text must change (inject ctx as a handler param),
    # same shape as the FastMCP rename, not the Context move. Missed in the
    # first manual GT pass (which used the reduced 6-item host-construction
    # guide's stale "get_context() -- unchanged" framing instead of the
    # authoritative 9-fact spec); all 3 agents caught it correctly.
    ("src/opsmesh/server/context.py", 20),
    ("src/opsmesh/client/session_group.py", 38),
    ("src/opsmesh/orchestrator/tool_catalog.py", 46),
    ("tests/test_server_base.py", 31),
    ("tests/test_client_session_group.py", 23),
    ("tests/test_orchestrator_agent.py", 18),
}

GREP_MISSED = {("tests/test_client_session_group.py", 23)}
PREFILTER_DROPPED = {
    ("src/opsmesh/orchestrator/tool_catalog.py", 46),
    ("tests/test_orchestrator_agent.py", 18),
}
REACHABLE_GT = GT - GREP_MISSED - PREFILTER_DROPPED

raw_candidates = json.load(open(os.path.join(BASE, "candidates_raw.json")))
raw_keys = {(c["file"], c["line"]) for c in raw_candidates}
final_candidates = json.load(open(os.path.join(BASE, "candidates_final.json")))
final_keys = set()
for c in final_candidates:
    final_keys.add((c["file"], c["line"]))
    for dl in c.get("duplicate_lines", []):
        final_keys.add((c["file"], dl))


def score_run(path):
    data = validate_run_file(path)
    proposed = {(i["file"], i["line"]) for i in data["proposed_sites"]}
    flagged = {(i["file"], i["line"]) for i in data["flag_uncertain"]}
    rejected = {(i["file"], i["line"]) for i in data["considered_and_rejected"]}

    all_verdicted = proposed | flagged | rejected
    missing_from_output = final_keys - all_verdicted
    extra_in_output = all_verdicted - final_keys

    tp_propose = REACHABLE_GT & proposed
    gt_in_flag = REACHABLE_GT & flagged
    gt_missed_entirely = REACHABLE_GT - proposed - flagged
    fp_propose = proposed - REACHABLE_GT  # false positives: proposed but not GT

    surfaced = REACHABLE_GT & (proposed | flagged)  # "found it, even if hedged"

    precision = len(tp_propose) / len(proposed) if proposed else float("nan")
    recall_strict = len(tp_propose) / len(REACHABLE_GT)
    recall_surfaced = len(surfaced) / len(REACHABLE_GT)

    return {
        "run": data["run"],
        "n_candidates_final": len(final_keys),
        "missing_from_output": sorted(missing_from_output),
        "extra_in_output": sorted(extra_in_output),
        "proposed_count": len(proposed),
        "flag_count": len(flagged),
        "reject_count": len(rejected),
        "true_positives_propose": sorted(tp_propose),
        "gt_in_flag_uncertain": sorted(gt_in_flag),
        "gt_missed_entirely": sorted(gt_missed_entirely),
        "false_positives_propose": sorted(fp_propose),
        "precision_strict_propose_only": precision,
        "recall_strict_propose_only": recall_strict,
        "recall_surfaced_propose_or_flag": recall_surfaced,
    }


def main():
    results = []
    for i in (1, 2, 3):
        path = os.path.join(BASE, "runs", f"attempt{i}.json")
        if not os.path.isfile(path):
            print(f"attempt{i}.json not found yet, skipping")
            continue
        r = score_run(path)
        results.append(r)
        print(f"\n===== run {r['run']} =====")
        for k, v in r.items():
            print(f"  {k}: {v}")

    print("\n\n===== GT accounting =====")
    print(f"Total independently-derived GT: {len(GT)}")
    print(f"Missed by grep (vocabulary gap, never a candidate): {sorted(GREP_MISSED)}")
    print(f"Dropped by hardened prefilter stage A (file-relevance false negative): {sorted(PREFILTER_DROPPED)}")
    print(f"Reachable by agent (the only GT the pipeline had a chance at): {len(REACHABLE_GT)} / {len(GT)}")

    with open(os.path.join(BASE, "scoring_results.json"), "w") as f:
        json.dump(results, f, indent=2, default=str)


if __name__ == "__main__":
    main()
