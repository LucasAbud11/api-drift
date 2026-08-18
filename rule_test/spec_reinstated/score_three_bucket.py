import json, os, re
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(BASE, "runs")

# Ground truth, corrected 2026-08-18 (B8b removed -- see b8b_verification.md)
GT = {
    ("A", "TomaszRewak_MAGI", "ai.py", 6), ("A", "TomaszRewak_MAGI", "ai.py", 7),
    ("A", "TomaszRewak_MAGI", "ai.py", 51), ("A", "TomaszRewak_MAGI", "ai.py", 52),
    ("A", "TomaszRewak_MAGI", "ai.py", 64), ("A", "TomaszRewak_MAGI", "ai.py", 65),
    ("A", "franalgaba_chatgpt-telegram-bot-serverless", "app.py", 41),
    ("A", "batuhantoker_Flask-OpenAI-Chatbot", "app.py", 8),
    ("A", "batuhantoker_Flask-OpenAI-Chatbot", "app.py", 48),
    ("A", "g0ldencybersec_sus_params", "PoC.py", 7),
    ("A", "g0ldencybersec_sus_params", "PoC.py", 11),
    ("A", "g0ldencybersec_sus_params", "PoC.py", 192),
    ("A", "g0ldencybersec_sus_params", "PoC.py", 201),

    ("B", "tonyzorin_youtrack-mcp", "main.py", 10),
    ("B", "tonyzorin_youtrack-mcp", "main.py", 25),
    ("B", "tonyzorin_youtrack-mcp", "main.py", 27),

    ("B", "QAInsights_jmeter-mcp-server", "main.py", 2),
    ("B", "QAInsights_jmeter-mcp-server", "main.py", 9),
    ("B", "QAInsights_jmeter-mcp-server", "jmeter_server.py", 4),
    ("B", "QAInsights_jmeter-mcp-server", "jmeter_server.py", 23),
    ("B", "QAInsights_jmeter-mcp-server", "tests/test_jmeter_server.py", 11),
    # B8b (tests/test_jmeter_server.py:12, `class FastMCP:`) REMOVED 2026-08-18:
    # empirically verified not to be a required edit -- see b8b_verification.md.
    ("B", "QAInsights_jmeter-mcp-server", "tests/test_jmeter_server.py", 21),
    ("B", "QAInsights_jmeter-mcp-server", "tests/test_jmeter_server.py", 22),

    ("B", "securityfortech_secops-mcp", "main.py", 7),
    ("B", "securityfortech_secops-mcp", "main.py", 26),

    ("B", "m0xai_trello-mcp-server", "main.py", 6),
    ("B", "m0xai_trello-mcp-server", "main.py", 23),
    ("B", "m0xai_trello-mcp-server", "server/tools/board.py", 8),
    ("B", "m0xai_trello-mcp-server", "server/tools/card.py", 8),
    ("B", "m0xai_trello-mcp-server", "server/tools/list.py", 8),

    ("B", "danilop_MCP2Lambda", "main.py", 6),
    ("B", "danilop_MCP2Lambda", "main.py", 30),
    ("B", "danilop_MCP2Lambda", "mcp_client_bedrock/main.py", 44),
}

REPO_TARGET = {
    "TomaszRewak_MAGI": "A", "franalgaba_chatgpt-telegram-bot-serverless": "A",
    "batuhantoker_Flask-OpenAI-Chatbot": "A", "g0ldencybersec_sus_params": "A",
    "tonyzorin_youtrack-mcp": "B", "QAInsights_jmeter-mcp-server": "B",
    "securityfortech_secops-mcp": "B", "m0xai_trello-mcp-server": "B",
    "danilop_MCP2Lambda": "B",
}

HEDGE_PATTERNS = [
    r'low confidence', r'flagged here', r'not (?:entirely |fully |100% )?(?:certain|sure)',
    r'\buncertain\b', r'\bmight\b', r'\bmay not\b', r'\bpossibly\b', r'\barguably\b',
    r'\bborderline\b', r'\bambiguous\b', r'judgment call', r'rather than silently',
    r'not strictly (?:necessary|required)', r'debatable', r'could go either way',
]
HEDGE_RE = re.compile('|'.join(HEDGE_PATTERNS), re.IGNORECASE)


def load_run(repo, run):
    path = os.path.join(RUNS, repo, f"run{run}.json")
    with open(path) as f:
        return json.load(f)


def bucket_run(repo, run):
    target = REPO_TARGET[repo]
    data = load_run(repo, run)

    proposed = {(target, repo, s["file"], s["line"]) for s in data.get("proposed_sites", [])}

    flag_uncertain = set()
    reject = set()
    for item in data.get("considered_and_rejected", []):
        key = (target, repo, item["file"], item["line"])
        if HEDGE_RE.search(item.get("reason", "")):
            flag_uncertain.add(key)
        else:
            reject.add(key)

    return proposed, flag_uncertain, reject


def main():
    repos = list(REPO_TARGET.keys())

    grand = {
        "propose_tp": 0, "propose_fp": 0, "propose_gt": 0,
        "flag_true": 0, "flag_false": 0,
        "reject_true": 0, "reject_false": 0,
        "invisible_true": 0,  # GT sites not mentioned in either bucket at all
    }

    per_run_rows = []

    for repo in repos:
        target = REPO_TARGET[repo]
        gt = {k for k in GT if k[0] == target and k[1] == repo}
        for run in (1, 2, 3):
            proposed, flag_unc, reject = bucket_run(repo, run)

            tp = proposed & gt
            fp = proposed - gt
            fn = gt - proposed  # not proposed -- either flagged, rejected, or invisible

            fn_in_flag = fn & flag_unc
            fn_in_reject = fn & reject
            fn_invisible = fn - flag_unc - reject

            recall = len(tp) / len(gt) * 100 if gt else float('nan')
            precision = len(tp) / len(proposed) * 100 if proposed else float('nan')

            per_run_rows.append({
                "repo": repo, "run": run, "target": target,
                "gt": len(gt), "tp": len(tp), "fp": len(fp),
                "recall": recall, "precision": precision,
                "fn_in_flag": sorted(fn_in_flag),
                "fn_in_reject": sorted(fn_in_reject),
                "fn_invisible": sorted(fn_invisible),
            })

            grand["propose_tp"] += len(tp)
            grand["propose_fp"] += len(fp)
            grand["propose_gt"] += len(gt)
            grand["flag_true"] += len(fn_in_flag)
            grand["reject_true"] += len(fn_in_reject)
            grand["invisible_true"] += len(fn_invisible)

    print(f"{'repo':45s} {'run':4s} {'GT':3s} {'TP':3s} {'FP':3s} {'recall':8s} {'precision':10s} {'FN->flag':9s} {'FN->reject':11s} {'FN->invis':10s}")
    for r in per_run_rows:
        print(f"{r['repo']:45s} {r['run']:<4d} {r['gt']:<3d} {r['tp']:<3d} {r['fp']:<3d} "
              f"{r['recall']:6.1f}%  {r['precision']:6.1f}%    "
              f"{len(r['fn_in_flag']):<9d} {len(r['fn_in_reject']):<11d} {len(r['fn_invisible']):<10d}")
        if r['fn_in_flag']:
            print(f"    correctly flagged uncertain (true site): {r['fn_in_flag']}")
        if r['fn_in_reject']:
            print(f"    silently missed via confident REJECT: {r['fn_in_reject']}")
        if r['fn_invisible']:
            print(f"    silently missed, never mentioned at all: {r['fn_invisible']}")

    print()
    print("=== AGGREGATE ACROSS ALL 27 RUNS ===")
    overall_recall = grand["propose_tp"] / grand["propose_gt"] * 100
    overall_precision = grand["propose_tp"] / (grand["propose_tp"] + grand["propose_fp"]) * 100
    print(f"Precision on proposed-only: {grand['propose_tp']}/{grand['propose_tp']+grand['propose_fp']} = {overall_precision:.1f}%")
    print(f"Recall on proposed-only:    {grand['propose_tp']}/{grand['propose_gt']} = {overall_recall:.1f}%")
    total_fn = grand["flag_true"] + grand["reject_true"] + grand["invisible_true"]
    print(f"\nTotal recall misses (FN) across 27 runs: {total_fn}")
    print(f"  -> correctly landed in FLAG-UNCERTAIN (agent flagged its own doubt): {grand['flag_true']}")
    print(f"  -> silently missed via a confident REJECT reason:                   {grand['reject_true']}")
    print(f"  -> silently missed, not mentioned in proposed OR rejected at all:   {grand['invisible_true']}")


if __name__ == "__main__":
    main()
