import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(BASE), "scale_experiment"))
sys.path.insert(0, os.path.join(os.path.dirname(BASE), "blind_vocab_experiment"))
from validate_run import validate_run_file
from gt import GT_TARGET_B_DILUTED

REDUCED_CANDS = json.load(open(os.path.join(BASE, "reduced_targetB_diluted.json")))
# map representative (file, line) -> full set of lines it stands for
EXPANSION = {}
for c in REDUCED_CANDS:
    key = (c["file"], c["line"])
    EXPANSION[key] = set(c.get("duplicate_lines", [c["line"]]))
    EXPANSION[key] = {(c["file"], ln) for ln in EXPANSION[key]}

ALL_CANDIDATE_KEYS = set(EXPANSION.keys())


def expand(items):
    out = set()
    for it in items:
        key = (it["file"], it["line"])
        out |= EXPANSION.get(key, {key})
    return out


def main():
    run_dir = os.path.join(BASE, "reliability_runs")
    run_files = sorted(f for f in os.listdir(run_dir) if f.endswith(".json"))
    print(f"Reduced candidate set: {len(REDUCED_CANDS)} representatives, "
          f"{sum(len(v) for v in EXPANSION.values())} total lines covered\n")

    all_clean = 0
    for fname in run_files:
        path = os.path.join(run_dir, fname)
        data = validate_run_file(path)  # hard-fails on malformed run

        proposed_reps = {(s["file"], s["line"]) for s in data["proposed_sites"]}
        flag_reps = {(s["file"], s["line"]) for s in data["flag_uncertain"]}
        reject_reps = {(s["file"], s["line"]) for s in data["considered_and_rejected"]}

        all_reps = proposed_reps | flag_reps | reject_reps
        out_of_contract = all_reps - ALL_CANDIDATE_KEYS
        unadjudicated = ALL_CANDIDATE_KEYS - all_reps

        proposed_expanded = expand(data["proposed_sites"])
        flag_expanded = expand(data["flag_uncertain"])

        tp = proposed_expanded & GT_TARGET_B_DILUTED
        fn = GT_TARGET_B_DILUTED - proposed_expanded
        fn_flag = fn & flag_expanded
        fn_lost = fn - flag_expanded

        recall = len(tp) / len(GT_TARGET_B_DILUTED) * 100
        surfaced = len(tp | fn_flag) / len(GT_TARGET_B_DILUTED) * 100
        precision = len(tp) / len(proposed_expanded) * 100 if proposed_expanded else float("nan")

        clean = (len(out_of_contract) == 0 and len(unadjudicated) == 0)
        all_clean += 1 if clean else 0

        print(f"{fname}: reps_adjudicated={len(all_reps)}/{len(ALL_CANDIDATE_KEYS)} "
              f"out_of_contract={len(out_of_contract)} unadjudicated={len(unadjudicated)} "
              f"{'CLEAN' if clean else 'INCOMPLETE'}")
        print(f"  recall={recall:.1f}% precision={precision:.1f}% surfaced={surfaced:.1f}%"
              + (f"  LOST GT SITES: {sorted(fn_lost)}" if fn_lost else ""))

    print(f"\n{all_clean}/{len(run_files)} runs completed cleanly (schema-valid, full closed-world coverage) on first attempt.")


if __name__ == "__main__":
    main()
