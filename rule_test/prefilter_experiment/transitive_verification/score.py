"""Score the 9 post-transitive-stage-A verification runs (targetB_small x3,
targetB_diluted x3, entangled x3) and check for regressions against the
prior (pre-transitive) known-good results."""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(BASE)), "scale_experiment"))
sys.path.insert(0, os.path.join(os.path.dirname(BASE), "..", "blind_vocab_experiment"))
from validate_run import validate_run_file
from gt import GT_TARGET_B_SMALL, GT_TARGET_B_DILUTED

ENTANGLEMENT_GT = {
    ("src/opsmesh/server/base.py", 16), ("src/opsmesh/server/base.py", 24),
    ("src/opsmesh/server/context.py", 12), ("src/opsmesh/server/context.py", 13),
    ("src/opsmesh/server/context.py", 20),
    ("src/opsmesh/client/session_group.py", 38), ("src/opsmesh/orchestrator/tool_catalog.py", 46),
    ("tests/test_server_base.py", 31), ("tests/test_client_session_group.py", 23),
    ("tests/test_orchestrator_agent.py", 18),
}


def score_run(path, gt):
    data = validate_run_file(path)
    proposed = {(i["file"], i["line"]) for i in data["proposed_sites"]}
    flagged = {(i["file"], i["line"]) for i in data["flag_uncertain"]}
    rejected = {(i["file"], i["line"]) for i in data["considered_and_rejected"]}
    all_verdicted = proposed | flagged | rejected

    tp = gt & proposed
    gt_in_flag = gt & flagged
    gt_missed = gt - proposed - flagged
    fp = proposed - gt

    recall_propose = len(tp) / len(gt)
    recall_surfaced = len((gt & proposed) | (gt & flagged)) / len(gt)
    precision = len(tp) / len(proposed) if proposed else float("nan")

    return {
        "run": data["run"], "repo": data["repo"],
        "n_verdicted": len(all_verdicted),
        "proposed": len(proposed), "flagged": len(flagged), "rejected": len(rejected),
        "true_positives": sorted(tp), "false_positives": sorted(fp),
        "gt_in_flag_uncertain": sorted(gt_in_flag), "gt_missed_entirely": sorted(gt_missed),
        "precision": precision, "recall_propose_only": recall_propose,
        "recall_surfaced": recall_surfaced,
    }


def summarize(label, runs, gt, raw_count, final_count):
    print(f"\n===== {label} (GT={len(gt)}, raw candidates={raw_count}, "
          f"final after transitive prefilter={final_count}, "
          f"reduction={100*(1-final_count/raw_count):.1f}%) =====")
    for r in runs:
        print(f"  run {r['run']}: precision={r['precision']:.1%}  "
              f"recall(propose)={r['recall_propose_only']:.1%}  "
              f"recall(surfaced)={r['recall_surfaced']:.1%}  "
              f"FP={r['false_positives']}  "
              f"GT-in-flag={r['gt_in_flag_uncertain']}  "
              f"GT-missed={r['gt_missed_entirely']}")


def main():
    all_runs = {}

    # targetB_small
    small_runs = [score_run(os.path.join(BASE, "runs", f"targetB_small_run{i}.json"), GT_TARGET_B_SMALL) for i in (1, 2, 3)]
    all_runs["targetB_small"] = small_runs
    small_final = json.load(open(os.path.join(BASE, "candidates_targetB_small.json")))
    summarize("targetB_small", small_runs, GT_TARGET_B_SMALL, 587, len(small_final))

    # targetB_diluted
    diluted_runs = [score_run(os.path.join(BASE, "runs", f"targetB_diluted_run{i}.json"), GT_TARGET_B_DILUTED) for i in (1, 2, 3)]
    all_runs["targetB_diluted"] = diluted_runs
    diluted_final = json.load(open(os.path.join(BASE, "candidates_targetB_diluted.json")))
    summarize("targetB_diluted", diluted_runs, GT_TARGET_B_DILUTED, 1121, len(diluted_final))

    # entangled
    ENT_DIR = os.path.join(os.path.dirname(BASE), "..", "entanglement_experiment")
    ent_runs = [score_run(os.path.join(ENT_DIR, "runs", f"transitive_attempt{i}.json"), ENTANGLEMENT_GT) for i in (1, 2, 3)]
    all_runs["entangled"] = ent_runs
    ent_final = json.load(open(os.path.join(ENT_DIR, "candidates_final_transitive.json")))
    summarize("entangled (transitive stage A)", ent_runs, ENTANGLEMENT_GT, 69, len(ent_final))

    print("\n\n===== Specific confirmation: tool_catalog.py:46 =====")
    target_site = ("src/opsmesh/orchestrator/tool_catalog.py", 46)
    for r in ent_runs:
        recovered = target_site in r["true_positives"]
        hedged = target_site in r["gt_in_flag_uncertain"]
        missed = target_site in r["gt_missed_entirely"]
        print(f"  run {r['run']}: PROPOSE={recovered}  FLAG-UNCERTAIN={hedged}  MISSED={missed}")

    with open(os.path.join(BASE, "scoring_results.json"), "w") as f:
        json.dump(all_runs, f, indent=2, default=str)


if __name__ == "__main__":
    main()
