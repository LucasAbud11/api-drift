"""Score the 6 Target A verification runs (targetA_small x3, targetA_diluted
x3) against the current three-stage pipeline's exact 9-candidate list per
host. Expands stage-C duplicate-collapsed representatives back to every
original line before scoring, per this study's established convention
(prefilter_experiment/report.md) -- a verdict on one representative line
covers every line it was collapsed from."""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(BASE)), "scale_experiment"))
sys.path.insert(0, os.path.join(os.path.dirname(BASE), "..", "blind_vocab_experiment"))
from validate_run import validate_run_file
from gt import GT_TARGET_A_SMALL, GT_TARGET_A_DILUTED


def load_expansion(cand_file):
    cands = json.load(open(cand_file))
    exp = {}
    for c in cands:
        key = (c["file"], c["line"])
        exp[key] = [(c["file"], dl) for dl in c.get("duplicate_lines", [c["line"]])]
    return exp


def score_run(path, gt, expansion):
    data = validate_run_file(path)

    def expand(items):
        out = set()
        for i in items:
            key = (i["file"], i["line"])
            for e in expansion.get(key, [key]):
                out.add(e)
        return out

    proposed = expand(data["proposed_sites"])
    flagged = expand(data["flag_uncertain"])
    tp = gt & proposed
    fp = {(i["file"], i["line"]) for i in data["proposed_sites"]} - gt
    missed = gt - proposed - flagged
    precision = len(tp) / len(proposed) if proposed else float("nan")
    recall_propose = len(tp) / len(gt)
    recall_surfaced = len((gt & proposed) | (gt & flagged)) / len(gt)
    return {
        "run": data["run"], "precision": precision,
        "recall_propose_only": recall_propose, "recall_surfaced": recall_surfaced,
        "false_positives": sorted(fp), "gt_missed_entirely": sorted(missed),
    }


def main():
    results = {}
    for scale, gt, cfile in [
        ("targetA_small", GT_TARGET_A_SMALL, "candidates_targetA_small.json"),
        ("targetA_diluted", GT_TARGET_A_DILUTED, "candidates_targetA_diluted.json"),
    ]:
        expansion = load_expansion(os.path.join(BASE, cfile))
        runs = [score_run(os.path.join(BASE, "runs", f"{scale}_run{i}.json"), gt, expansion) for i in (1, 2, 3)]
        results[scale] = runs
        print(f"\n===== {scale} (GT={len(gt)}) =====")
        for r in runs:
            print(f"  run {r['run']}: precision={r['precision']:.0%} "
                  f"recall_propose={r['recall_propose_only']:.0%} "
                  f"recall_surfaced={r['recall_surfaced']:.0%} "
                  f"FP={r['false_positives']} missed={r['gt_missed_entirely']}")
    with open(os.path.join(BASE, "scoring_results_targetA.json"), "w") as f:
        json.dump(results, f, indent=2, default=str)


if __name__ == "__main__":
    main()
