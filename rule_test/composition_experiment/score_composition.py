"""
Scorer for the grep-candidates + agent-adjudication composition experiment.

Every run file is loaded exclusively through validate_run_file() (imported
from the scale_experiment's hardened validator -- same contract, same
hard-fail-on-missing-field behavior, not reimplemented separately).

Unlike the earlier experiments, this one also checks CLOSED-WORLD
COMPLIANCE: since the agent was handed a fixed, finite candidate list and
explicitly told not to search for more, every item in its three buckets
must correspond to one of the candidates it was given, and every
candidate it was given must appear in exactly one bucket. Both directions
are checked and reported, not assumed.
"""
import json
import os
import sys
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(BASE), "scale_experiment"))
from validate_run import validate_run_file

RUNS = os.path.join(BASE, "runs")

GT_SMALL = {
    ("tonyzorin_youtrack-mcp/main.py", 10), ("tonyzorin_youtrack-mcp/main.py", 25), ("tonyzorin_youtrack-mcp/main.py", 27),
    ("QAInsights_jmeter-mcp-server/main.py", 2), ("QAInsights_jmeter-mcp-server/main.py", 9),
    ("QAInsights_jmeter-mcp-server/jmeter_server.py", 4), ("QAInsights_jmeter-mcp-server/jmeter_server.py", 23),
    ("QAInsights_jmeter-mcp-server/tests/test_jmeter_server.py", 11),
    ("QAInsights_jmeter-mcp-server/tests/test_jmeter_server.py", 21),
    ("QAInsights_jmeter-mcp-server/tests/test_jmeter_server.py", 22),
    ("securityfortech_secops-mcp/main.py", 7), ("securityfortech_secops-mcp/main.py", 26),
    ("m0xai_trello-mcp-server/main.py", 6), ("m0xai_trello-mcp-server/main.py", 23),
    ("m0xai_trello-mcp-server/server/tools/board.py", 8),
    ("m0xai_trello-mcp-server/server/tools/card.py", 8),
    ("m0xai_trello-mcp-server/server/tools/list.py", 8),
    ("danilop_MCP2Lambda/main.py", 6), ("danilop_MCP2Lambda/main.py", 30),
    ("danilop_MCP2Lambda/mcp_client_bedrock/main.py", 44),
}

GT_DILUTED = {(f"integrations/{f}", l) for f, l in GT_SMALL}

assert len(GT_SMALL) == 20 and len(GT_DILUTED) == 20


def normalize_path(p):
    p = p.strip()
    if p.startswith("./"):
        p = p[2:]
    if p.startswith("host/"):
        p = p[len("host/"):]
    return p


def load_candidates(scale):
    with open(os.path.join(BASE, f"candidates_{scale}.json")) as f:
        cands = json.load(f)
    return {(c["file"], c["line"]) for c in cands}


def score_scale(scale, gt):
    candidate_set = load_candidates(scale)
    run_dir = os.path.join(RUNS, scale)
    run_files = sorted(
        os.path.join(run_dir, f) for f in os.listdir(run_dir) if f.startswith("run") and f.endswith(".json")
    )
    if not run_files:
        raise RuntimeError(f"no run files found in {run_dir}")

    print(f"##### SCALE: {scale} #####")
    print(f"Candidate set size (grep, coverage-tuned): {len(candidate_set)}")
    print(f"Ground truth sites in this scale: {len(gt)}")
    missing_from_candidates = gt - candidate_set
    if missing_from_candidates:
        print(f"!! WARNING: {len(missing_from_candidates)} GT sites are NOT in the candidate set at all "
              f"(grep itself missed them, independent of the agent): {sorted(missing_from_candidates)}")
    else:
        print("Confirmed: grep candidate set has 100% recall on GT before any adjudication.")
    print()

    print(f"Validating {len(run_files)} run file(s)...")
    for rp in run_files:
        validate_run_file(rp)
        print(f"  OK  {os.path.basename(rp)}")
    print()

    grand = {"tp": 0, "fp": 0, "gt": 0, "proposed": 0, "flag_true": 0, "reject_true": 0, "invisible_true": 0,
             "out_of_contract": 0, "unadjudicated": 0}

    for rp in run_files:
        data = validate_run_file(rp)
        run_label = f"run{data['run']}"

        proposed = {(normalize_path(s["file"]), s["line"]) for s in data["proposed_sites"]}
        flag = {(normalize_path(s["file"]), s["line"]) for s in data["flag_uncertain"]}
        reject = {(normalize_path(s["file"]), s["line"]) for s in data["considered_and_rejected"]}

        # closed-world compliance
        all_adjudicated = proposed | flag | reject
        out_of_contract = all_adjudicated - candidate_set
        unadjudicated = candidate_set - all_adjudicated
        dupes = len(data["proposed_sites"]) + len(data["flag_uncertain"]) + len(data["considered_and_rejected"]) - len(all_adjudicated)

        tp = proposed & gt
        fp = proposed - gt
        fn = gt - proposed
        fn_in_flag = fn & flag
        fn_in_reject = fn & reject
        fn_invisible = fn - flag - reject  # should be 0 if closed-world held and gt subset of candidates

        recall = len(tp) / len(gt) * 100
        precision = len(tp) / len(proposed) * 100 if proposed else float('nan')
        surfaced = (tp | fn_in_flag)  # GT sites either proposed correctly or flagged uncertain -- "not silently lost"
        surfaced_rate = len(surfaced) / len(gt) * 100

        print(f"=== {scale}/{run_label} ===")
        print(f"  adjudicated: {len(all_adjudicated)} / {len(candidate_set)} candidates "
              f"(proposed={len(proposed)} flag={len(flag)} reject={len(reject)}, dupes={dupes})")
        if out_of_contract:
            print(f"  !! OUT-OF-CONTRACT items (not in the given candidate list): {sorted(out_of_contract)}")
        if unadjudicated:
            print(f"  !! UNADJUDICATED candidates (given but never given a verdict): {sorted(unadjudicated)}")
        print(f"  TP={len(tp)} FP={len(fp)} GT={len(gt)}  recall(proposed-only)={recall:.1f}%  precision={precision:.1f}%")
        print(f"  GT sites surfaced (proposed OR flagged, i.e. NOT silently lost): {len(surfaced)}/{len(gt)} = {surfaced_rate:.1f}%")
        if fp:
            print(f"  FALSE POSITIVES: {sorted(fp)}")
        if fn_in_flag:
            print(f"  GT sites correctly routed to FLAG-UNCERTAIN: {sorted(fn_in_flag)}")
        if fn_in_reject:
            print(f"  GT sites silently missed via confident REJECT (mandatory-rule violation if in test path): {sorted(fn_in_reject)}")
        if fn_invisible:
            print(f"  GT sites missed, never adjudicated at all (should be empty under closed-world): {sorted(fn_invisible)}")
        print()

        grand["tp"] += len(tp); grand["fp"] += len(fp); grand["gt"] += len(gt); grand["proposed"] += len(proposed)
        grand["flag_true"] += len(fn_in_flag); grand["reject_true"] += len(fn_in_reject)
        grand["invisible_true"] += len(fn_invisible)
        grand["out_of_contract"] += len(out_of_contract)
        grand["unadjudicated"] += len(unadjudicated)

    print(f"=== {scale} AGGREGATE ({len(run_files)} runs) ===")
    overall_precision = grand["tp"] / grand["proposed"] * 100 if grand["proposed"] else float('nan')
    overall_recall = grand["tp"] / grand["gt"] * 100
    overall_surfaced = (grand["tp"] + grand["flag_true"]) / grand["gt"] * 100
    print(f"Precision on proposed-only: {grand['tp']}/{grand['proposed']} = {overall_precision:.1f}%")
    print(f"Recall on proposed-only:    {grand['tp']}/{grand['gt']} = {overall_recall:.1f}%")
    print(f"Surfaced rate (proposed OR flag_uncertain, i.e. not silently lost): {overall_surfaced:.1f}%")
    print(f"Total closed-world violations: out_of_contract={grand['out_of_contract']}  unadjudicated={grand['unadjudicated']}")
    print(f"Total GT misses landing in confident REJECT: {grand['reject_true']}")
    print(f"Total GT misses never adjudicated (true mechanism-B recurrence): {grand['invisible_true']}")
    print()
    return grand


def main():
    by_top = defaultdict(int)
    for c, _ in GT_SMALL:
        pass
    for scale, gt, out_top in [("small", GT_SMALL, None), ("diluted", GT_DILUTED, None)]:
        cands = load_candidates(scale)
        top_counts = defaultdict(int)
        for f, l in cands:
            top_counts[f.split("/")[0] if scale == "small" else (f.split("/")[1] if f.startswith("integrations/") else "django")] += 1
        print(f"--- adjudication cost, {scale} scale ---")
        for top, n in sorted(top_counts.items()):
            print(f"  {top}: {n} candidates")
        print(f"  TOTAL: {len(cands)} candidates handed to the agent\n")

    score_scale("small", GT_SMALL)
    score_scale("diluted", GT_DILUTED)


if __name__ == "__main__":
    main()
