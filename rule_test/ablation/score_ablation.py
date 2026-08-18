import json, os
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(BASE, "runs")

# Ground truth for the two repos that can actually show the effect
# (tonyzorin, QAInsights, securityfortech have zero ctx:Context sites -- excluded, see rule_test.md)
GT = {
    "m0xai_trello-mcp-server": {
        ("main.py", 6), ("main.py", 23),
        ("server/tools/board.py", 8), ("server/tools/card.py", 8), ("server/tools/list.py", 8),
    },
    "danilop_MCP2Lambda": {
        ("main.py", 6), ("main.py", 30),
        ("mcp_client_bedrock/main.py", 44),
    },
}

def score_run(path, gt):
    with open(path) as f:
        data = json.load(f)
    proposed = {(s["file"], s["line"]) for s in data["proposed_sites"]}
    tp = proposed & gt
    fp = proposed - gt
    fn = gt - proposed
    return len(tp), len(fp), len(fn), len(proposed)

for condition in ["condition_A", "condition_B"]:
    print(f"=== {condition} ===")
    for repo, gt in GT.items():
        results = []
        for run in range(1, 6):
            path = os.path.join(RUNS, condition, repo, f"run{run}.json")
            tp, fp, fn, proposed = score_run(path, gt)
            recall = tp / len(gt) * 100
            precision = tp / proposed * 100 if proposed else float('nan')
            results.append((run, tp, fp, fn, proposed, recall, precision))
        print(f"  {repo} (GT={len(gt)}, of which ctx:Context-style ambiguous sites={len(gt)-2}):")
        for run, tp, fp, fn, proposed, recall, precision in results:
            print(f"    run{run}: TP={tp} FP={fp} FN={fn} proposed={proposed}  recall={recall:.0f}%  precision={precision:.0f}%")
        recalls = [r[5] for r in results]
        precisions = [r[6] for r in results]
        fps = [r[2] for r in results]
        print(f"    -> recall range: {min(recalls):.0f}-{max(recalls):.0f}%  precision range: {min(precisions):.0f}-{max(precisions):.0f}%  FP range: {min(fps)}-{max(fps)}")
    print()
