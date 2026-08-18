"""
Scorer for the blind-vocabulary experiment. Every run file is loaded
through the same hardened validate_run_file() used throughout this
study (scale_experiment/validate_run.py) -- hard-fails on any missing
bucket key or blank required field.

Reports, per scale/target combo and in aggregate:
  - candidate-set recall (grep alone, before any adjudication) -- the
    "structurally invisible" ceiling: GT sites the vocabulary itself
    never surfaces as a candidate, which no amount of agent judgment
    can recover.
  - end-to-end recall (proposed-only) and surfaced rate (proposed OR
    flag_uncertain) after adjudication.
  - closed-world compliance (out-of-contract / unadjudicated counts).
  - adjudication cost (candidate list size) per scale.
"""
import json
import os
import sys
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(BASE), "scale_experiment"))
from validate_run import validate_run_file

from gt import GT_TARGET_A_SMALL, GT_TARGET_A_DILUTED, GT_TARGET_B_SMALL, GT_TARGET_B_DILUTED

RUNS = os.path.join(BASE, "runs")

SCALES = [
    ("targetA_small", GT_TARGET_A_SMALL, "candidates_targetA_small_blind.json"),
    ("targetA_diluted", GT_TARGET_A_DILUTED, "candidates_targetA_diluted_blind.json"),
    ("targetB_small", GT_TARGET_B_SMALL, "candidates_targetB_small_blind.json"),
    ("targetB_diluted", GT_TARGET_B_DILUTED, "candidates_targetB_diluted_blind.json"),
]


def normalize_path(p):
    p = p.strip()
    if p.startswith("./"):
        p = p[2:]
    return p


def score_scale(scale, gt, cand_file):
    candidate_set = {(c["file"], c["line"]) for c in json.load(open(os.path.join(BASE, cand_file)))}
    cand_recall = len(gt & candidate_set) / len(gt) * 100
    cand_missing = gt - candidate_set

    run_dir = os.path.join(RUNS, scale)
    run_files = sorted(os.path.join(run_dir, f) for f in os.listdir(run_dir) if f.startswith("run") and f.endswith(".json"))

    print(f"##### {scale} #####")
    print(f"Candidate set size: {len(candidate_set)}  |  GT: {len(gt)}  |  candidate-set recall: {cand_recall:.1f}%")
    if cand_missing:
        print(f"  STRUCTURALLY INVISIBLE (never a candidate, no adjudication can recover): {sorted(cand_missing)}")
    print()

    grand = {"tp": 0, "proposed": 0, "gt": 0, "flag_true": 0, "reject_true": 0, "invisible_true": 0,
             "out_of_contract": 0, "unadjudicated": 0}

    for rp in run_files:
        data = validate_run_file(rp)
        run_label = f"run{data['run']}"
        proposed = {(normalize_path(s["file"]), s["line"]) for s in data["proposed_sites"]}
        flag = {(normalize_path(s["file"]), s["line"]) for s in data["flag_uncertain"]}
        reject = {(normalize_path(s["file"]), s["line"]) for s in data["considered_and_rejected"]}

        all_adj = proposed | flag | reject
        out_of_contract = all_adj - candidate_set
        unadjudicated = candidate_set - all_adj

        tp = proposed & gt
        fn = gt - proposed
        fn_flag = fn & flag
        fn_reject = fn & reject
        fn_invisible = fn - flag - reject

        recall = len(tp) / len(gt) * 100
        surfaced = len(tp | fn_flag) / len(gt) * 100

        print(f"  {run_label}: proposed={len(proposed)} flag={len(flag)} reject={len(reject)} total_adj={len(all_adj)}")
        print(f"    recall(proposed-only)={recall:.1f}%  surfaced(propose+flag)={surfaced:.1f}%  "
              f"out_of_contract={len(out_of_contract)}  unadjudicated={len(unadjudicated)}")
        if fn_reject:
            print(f"    silently missed via confident REJECT: {sorted(fn_reject)}")
        if fn_invisible:
            print(f"    missed, never adjudicated: {sorted(fn_invisible)}")

        grand["tp"] += len(tp); grand["proposed"] += len(proposed); grand["gt"] += len(gt)
        grand["flag_true"] += len(fn_flag); grand["reject_true"] += len(fn_reject)
        grand["invisible_true"] += len(fn_invisible)
        grand["out_of_contract"] += len(out_of_contract); grand["unadjudicated"] += len(unadjudicated)

    print()
    print(f"  === {scale} aggregate ({len(run_files)} runs) ===")
    precision = grand["tp"] / grand["proposed"] * 100 if grand["proposed"] else float("nan")
    recall = grand["tp"] / grand["gt"] * 100
    surfaced = (grand["tp"] + grand["flag_true"]) / grand["gt"] * 100
    print(f"  Precision on proposed-only: {grand['tp']}/{grand['proposed']} = {precision:.1f}%")
    print(f"  Recall on proposed-only:    {grand['tp']}/{grand['gt']} = {recall:.1f}%")
    print(f"  Surfaced rate:              {surfaced:.1f}%")
    print(f"  Closed-world violations: out_of_contract={grand['out_of_contract']} unadjudicated={grand['unadjudicated']}")
    print()
    return {"cand_recall": cand_recall, "cand_missing": cand_missing, **grand}


def main():
    results = {}
    for scale, gt, cand_file in SCALES:
        results[scale] = score_scale(scale, gt, cand_file)

    print("=" * 70)
    print("OVERALL SUMMARY")
    print("=" * 70)
    for scale, r in results.items():
        precision = r["tp"] / r["proposed"] * 100 if r["proposed"] else float("nan")
        recall = r["tp"] / r["gt"] * 100
        print(f"{scale:20s} candidate-recall={r['cand_recall']:6.1f}%  "
              f"end-to-end recall={recall:6.1f}%  precision={precision:6.1f}%  "
              f"structurally-invisible-GT-sites={len(r['cand_missing'])}")


if __name__ == "__main__":
    main()
