"""
Scorer for the scale (search-space dilution) experiment.

Every run file is loaded EXCLUSIVELY through validate_run_file() --
see validate_run.py for what that enforces and why. This script does
not read raw JSON itself and does not fill in any default for a
missing/malformed field; a broken run file aborts the whole scoring
run with a clear error rather than silently scoring against a partial
reconstruction.
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validate_run import validate_run_file

BASE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(BASE, "runs")

# 20 corrected Target B ground-truth sites (see ground_truth/ground_truth.md,
# B8b removed 2026-08-18), paths rewritten relative to the scale host root
# (host/integrations/<repo>/...) since that's where these files now live.
GT = {
    ("integrations/tonyzorin_youtrack-mcp/main.py", 10),
    ("integrations/tonyzorin_youtrack-mcp/main.py", 25),
    ("integrations/tonyzorin_youtrack-mcp/main.py", 27),

    ("integrations/QAInsights_jmeter-mcp-server/main.py", 2),
    ("integrations/QAInsights_jmeter-mcp-server/main.py", 9),
    ("integrations/QAInsights_jmeter-mcp-server/jmeter_server.py", 4),
    ("integrations/QAInsights_jmeter-mcp-server/jmeter_server.py", 23),
    ("integrations/QAInsights_jmeter-mcp-server/tests/test_jmeter_server.py", 11),
    ("integrations/QAInsights_jmeter-mcp-server/tests/test_jmeter_server.py", 21),
    ("integrations/QAInsights_jmeter-mcp-server/tests/test_jmeter_server.py", 22),

    ("integrations/securityfortech_secops-mcp/main.py", 7),
    ("integrations/securityfortech_secops-mcp/main.py", 26),

    ("integrations/m0xai_trello-mcp-server/main.py", 6),
    ("integrations/m0xai_trello-mcp-server/main.py", 23),
    ("integrations/m0xai_trello-mcp-server/server/tools/board.py", 8),
    ("integrations/m0xai_trello-mcp-server/server/tools/card.py", 8),
    ("integrations/m0xai_trello-mcp-server/server/tools/list.py", 8),

    ("integrations/danilop_MCP2Lambda/main.py", 6),
    ("integrations/danilop_MCP2Lambda/main.py", 30),
    ("integrations/danilop_MCP2Lambda/mcp_client_bedrock/main.py", 44),
}

assert len(GT) == 20, f"expected 20 GT sites, got {len(GT)}"


def normalize_path(p):
    """Accept paths the agent may report either as 'integrations/<repo>/...'
    (matching {REPO_PATH} being the host root) or, if it echoed a path
    already rooted differently, strip a leading './'/'host/' prefix.
    No other normalization -- do not silently match on basename alone,
    that would hide real path-confusion errors instead of scoring them."""
    p = p.strip()
    if p.startswith("./"):
        p = p[2:]
    if p.startswith("host/"):
        p = p[len("host/"):]
    return p


def load_and_bucket(run_path):
    data = validate_run_file(run_path)
    proposed = {(normalize_path(s["file"]), s["line"]) for s in data["proposed_sites"]}
    flag = {(normalize_path(s["file"]), s["line"]) for s in data["flag_uncertain"]}
    reject = {(normalize_path(s["file"]), s["line"]) for s in data["considered_and_rejected"]}
    return data, proposed, flag, reject


def main():
    run_files = sorted(
        os.path.join(RUNS, f) for f in os.listdir(RUNS) if f.startswith("run") and f.endswith(".json")
    )
    if not run_files:
        raise RuntimeError(f"no run*.json files found in {RUNS} -- nothing to score")

    print(f"Validating {len(run_files)} run file(s) before scoring...")
    for rp in run_files:
        validate_run_file(rp)  # raises on any defect; no partial scoring
        print(f"  OK  {os.path.basename(rp)}")
    print()

    grand = {"tp": 0, "fp": 0, "gt": 0, "proposed": 0, "flag_true": 0, "reject_true": 0, "invisible_true": 0}

    for rp in run_files:
        data, proposed, flag, reject = load_and_bucket(rp)
        run_label = f"run{data['run']}"

        tp = proposed & GT
        fp = proposed - GT
        fn = GT - proposed

        fn_in_flag = fn & flag
        fn_in_reject = fn & reject
        fn_invisible = fn - flag - reject

        recall = len(tp) / len(GT) * 100
        precision = len(tp) / len(proposed) * 100 if proposed else float('nan')

        print(f"=== {run_label} ({os.path.basename(rp)}) ===")
        print(f"  proposed={len(proposed)} TP={len(tp)} FP={len(fp)} GT={len(GT)}  recall={recall:.1f}%  precision={precision:.1f}%")
        print(f"  flag_uncertain bucket size: {len(flag)}")
        if fp:
            print(f"  FALSE POSITIVES: {sorted(fp)}")
        if fn_in_flag:
            print(f"  GT sites correctly landed in FLAG-UNCERTAIN: {sorted(fn_in_flag)}")
        if fn_in_reject:
            print(f"  GT sites silently missed via confident REJECT: {sorted(fn_in_reject)}")
        if fn_invisible:
            print(f"  GT sites missed, never mentioned in any bucket: {sorted(fn_invisible)}")
        print()

        grand["tp"] += len(tp)
        grand["fp"] += len(fp)
        grand["gt"] += len(GT)
        grand["proposed"] += len(proposed)
        grand["flag_true"] += len(fn_in_flag)
        grand["reject_true"] += len(fn_in_reject)
        grand["invisible_true"] += len(fn_invisible)

    print("=== AGGREGATE ===")
    overall_precision = grand["tp"] / grand["proposed"] * 100 if grand["proposed"] else float('nan')
    overall_recall = grand["tp"] / grand["gt"] * 100
    print(f"Precision on proposed-only: {grand['tp']}/{grand['proposed']} = {overall_precision:.1f}%")
    print(f"Recall on proposed-only:    {grand['tp']}/{grand['gt']} = {overall_recall:.1f}%")
    total_fn = grand["flag_true"] + grand["reject_true"] + grand["invisible_true"]
    print(f"\nTotal recall misses across {len(run_files)} run(s): {total_fn}")
    print(f"  -> landed in FLAG-UNCERTAIN: {grand['flag_true']}")
    print(f"  -> silently missed via confident REJECT: {grand['reject_true']}")
    print(f"  -> silently missed, invisible (no mention at all): {grand['invisible_true']}")


if __name__ == "__main__":
    main()
