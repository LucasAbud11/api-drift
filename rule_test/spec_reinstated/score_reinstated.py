import json, os
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(BASE, "runs")

# Ground truth, transcribed from ground_truth/ground_truth.md (site id -> class)
GT = {
    ("A", "TomaszRewak_MAGI", "ai.py", 6): "helper-wrapped",
    ("A", "TomaszRewak_MAGI", "ai.py", 7): "helper-wrapped",
    ("A", "TomaszRewak_MAGI", "ai.py", 51): "helper-wrapped",
    ("A", "TomaszRewak_MAGI", "ai.py", 52): "helper-wrapped",
    ("A", "TomaszRewak_MAGI", "ai.py", 64): "helper-wrapped",
    ("A", "TomaszRewak_MAGI", "ai.py", 65): "helper-wrapped",
    ("A", "franalgaba_chatgpt-telegram-bot-serverless", "app.py", 41): "helper-wrapped",
    ("A", "batuhantoker_Flask-OpenAI-Chatbot", "app.py", 8): "literal",
    ("A", "batuhantoker_Flask-OpenAI-Chatbot", "app.py", 48): "helper-wrapped",
    ("A", "g0ldencybersec_sus_params", "PoC.py", 7): "literal",
    ("A", "g0ldencybersec_sus_params", "PoC.py", 11): "helper-wrapped",
    ("A", "g0ldencybersec_sus_params", "PoC.py", 192): "literal",
    ("A", "g0ldencybersec_sus_params", "PoC.py", 201): "literal",

    ("B", "tonyzorin_youtrack-mcp", "main.py", 10): "literal",
    ("B", "tonyzorin_youtrack-mcp", "main.py", 25): "literal",
    ("B", "tonyzorin_youtrack-mcp", "main.py", 27): "literal",

    ("B", "QAInsights_jmeter-mcp-server", "main.py", 2): "literal",
    ("B", "QAInsights_jmeter-mcp-server", "main.py", 9): "literal",
    ("B", "QAInsights_jmeter-mcp-server", "jmeter_server.py", 4): "literal",
    ("B", "QAInsights_jmeter-mcp-server", "jmeter_server.py", 23): "literal",
    ("B", "QAInsights_jmeter-mcp-server", "tests/test_jmeter_server.py", 11): "test/mock",
    ("B", "QAInsights_jmeter-mcp-server", "tests/test_jmeter_server.py", 12): "test/mock",
    ("B", "QAInsights_jmeter-mcp-server", "tests/test_jmeter_server.py", 21): "test/mock",
    ("B", "QAInsights_jmeter-mcp-server", "tests/test_jmeter_server.py", 22): "test/mock",

    ("B", "securityfortech_secops-mcp", "main.py", 7): "literal",
    ("B", "securityfortech_secops-mcp", "main.py", 26): "literal",

    ("B", "m0xai_trello-mcp-server", "main.py", 6): "literal",
    ("B", "m0xai_trello-mcp-server", "main.py", 23): "literal",
    ("B", "m0xai_trello-mcp-server", "server/tools/board.py", 8): "literal",
    ("B", "m0xai_trello-mcp-server", "server/tools/card.py", 8): "literal",
    ("B", "m0xai_trello-mcp-server", "server/tools/list.py", 8): "literal",

    ("B", "danilop_MCP2Lambda", "main.py", 6): "literal",
    ("B", "danilop_MCP2Lambda", "main.py", 30): "literal",
    ("B", "danilop_MCP2Lambda", "mcp_client_bedrock/main.py", 44): "client-side",
}

REPO_TARGET = {
    "TomaszRewak_MAGI": "A", "franalgaba_chatgpt-telegram-bot-serverless": "A",
    "batuhantoker_Flask-OpenAI-Chatbot": "A", "g0ldencybersec_sus_params": "A",
    "tonyzorin_youtrack-mcp": "B", "QAInsights_jmeter-mcp-server": "B",
    "securityfortech_secops-mcp": "B", "m0xai_trello-mcp-server": "B",
    "danilop_MCP2Lambda": "B",
}

def load_run(repo, run):
    path = os.path.join(RUNS, repo, f"run{run}.json")
    with open(path) as f:
        data = json.load(f)
    target = REPO_TARGET[repo]
    proposed = {(target, repo, s["file"], s["line"]) for s in data["proposed_sites"]}
    return proposed

def score(repo, run):
    target = REPO_TARGET[repo]
    gt = {k for k in GT if k[0] == target and k[1] == repo}
    proposed = load_run(repo, run)
    tp = proposed & gt
    fp = proposed - gt
    fn = gt - proposed
    return tp, fp, fn, gt, proposed

def main():
    all_repos = list(REPO_TARGET.keys())
    per_run_totals = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "gt": 0, "proposed": 0})
    print(f"{'repo':45s} {'run':4s} {'TP':3s} {'FP':3s} {'FN':3s} {'GT':3s} {'recall':8s} {'precision':10s}")
    for repo in all_repos:
        for run in (1, 2, 3):
            tp, fp, fn, gt, proposed = score(repo, run)
            recall = len(tp) / len(gt) * 100 if gt else float('nan')
            precision = len(tp) / len(proposed) * 100 if proposed else float('nan')
            print(f"{repo:45s} {run:<4d} {len(tp):<3d} {len(fp):<3d} {len(fn):<3d} {len(gt):<3d} {recall:6.1f}%  {precision:6.1f}%")
            d = per_run_totals[run]
            d["tp"] += len(tp); d["fp"] += len(fp); d["fn"] += len(fn)
            d["gt"] += len(gt); d["proposed"] += len(proposed)
            if fn:
                print(f"    MISSED: {sorted(fn)}")
            if fp:
                print(f"    FP: {sorted(fp)}")
    print()
    print("=== per-run totals across all 9 repos ===")
    for run in (1, 2, 3):
        d = per_run_totals[run]
        recall = d["tp"] / d["gt"] * 100 if d["gt"] else float('nan')
        precision = d["tp"] / d["proposed"] * 100 if d["proposed"] else float('nan')
        print(f"run{run}: TP={d['tp']} FP={d['fp']} FN={d['fn']} GT={d['gt']} proposed={d['proposed']}  recall={recall:.1f}%  precision={precision:.1f}%")

    print()
    print("=== per-target breakdown (averaged is not meaningful; showing union across 3 runs per repo for stability check) ===")
    for target in ("A", "B"):
        repos = [r for r, t in REPO_TARGET.items() if t == target]
        gt_total = sum(1 for k in GT if k[0] == target)
        print(f"Target {target}: {gt_total} GT sites across {len(repos)} repos")

if __name__ == "__main__":
    main()
