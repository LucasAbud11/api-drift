import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPOS_DIR = os.path.join(REPO_ROOT, "repos")

TARGET_B_SMALL_REPOS = [
    "danilop_MCP2Lambda",
    "m0xai_trello-mcp-server",
    "QAInsights_jmeter-mcp-server",
    "securityfortech_secops-mcp",
    "tonyzorin_youtrack-mcp",
]

TARGET_B_GUIDE_PATH = os.path.join(REPO_ROOT, "rule_test", "specs", "target_b_mcp_migration_spec.md")

TARGET_A_SMALL_REPOS = [
    "TomaszRewak_MAGI",
    "franalgaba_chatgpt-telegram-bot-serverless",
    "batuhantoker_Flask-OpenAI-Chatbot",
    "g0ldencybersec_sus_params",
]

TARGET_A_GUIDE_PATH = os.path.join(REPO_ROOT, "rule_test", "specs", "target_a_openai_migration_spec.md")


def _make_small_repo(tmp_path, dirname, repo_names):
    """Symlinks the named repos into a fresh temp dir -- reproduces the
    study's exact "_small" host (not the mixed 9-repo tree that repos/
    actually contains)."""
    root = tmp_path / dirname
    root.mkdir()
    for name in repo_names:
        src = os.path.join(REPOS_DIR, name)
        dst = root / name
        os.symlink(src, dst)
    return str(root)


def make_targetb_small_repo(tmp_path):
    return _make_small_repo(tmp_path, "targetb_small", TARGET_B_SMALL_REPOS)


def make_targeta_small_repo(tmp_path):
    return _make_small_repo(tmp_path, "targeta_small", TARGET_A_SMALL_REPOS)


# claude-opus-5 pricing, $/1M tokens (Anthropic API, cached 2026-06-24):
# input $5.00, output $25.00, cache write $6.25 (1.25x input), cache read $0.50 (0.1x input)
_PRICE_PER_MTOK = {
    "input_tokens": 5.00,
    "output_tokens": 25.00,
    "cache_creation_input_tokens": 6.25,
    "cache_read_input_tokens": 0.50,
}


def report_usage(client):
    totals = client.usage_totals
    cost = sum(totals[k] / 1_000_000 * _PRICE_PER_MTOK[k] for k in _PRICE_PER_MTOK)
    print(f"\ntoken usage: input={totals['input_tokens']} output={totals['output_tokens']} "
          f"cache_write={totals['cache_creation_input_tokens']} cache_read={totals['cache_read_input_tokens']}")
    print(f"total tokens: {sum(totals.values())}  estimated cost: ${cost:.4f}  "
          f"({len(client.calls)} API calls)")
    return totals, cost


def score_against(expanded, ground_truth):
    """Metric matching REPORT.md's own definitions: every GT site must
    appear in PROPOSE or FLAG-UNCERTAIN (surfaced recall), and every
    PROPOSE entry must be a real GT site (precision). GT keys are
    "<repo-dir-name>/<relpath>" -- exactly what RepoReader.list_py_files()
    produces when repo_root is a temp dir of symlinks built by
    _make_small_repo(), so no path massaging needed."""
    proposed = {(i["file"], i["line"]) for i in expanded["proposed_sites"]}
    flagged = {(i["file"], i["line"]) for i in expanded["flag_uncertain"]}
    surfaced = proposed | flagged

    missed = ground_truth - surfaced
    false_positives = proposed - ground_truth

    surfaced_recall = 1.0 - len(missed) / len(ground_truth)
    precision = 1.0 if not proposed else len(proposed - false_positives) / len(proposed)
    return surfaced_recall, precision, missed, false_positives
