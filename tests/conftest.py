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


def make_targetb_small_repo(tmp_path):
    """Symlinks the 5 known Target B repos into a fresh temp dir --
    reproduces the study's exact targetB_small host (not the mixed
    9-repo tree that repos/ actually contains)."""
    root = tmp_path / "targetb_small"
    root.mkdir()
    for name in TARGET_B_SMALL_REPOS:
        src = os.path.join(REPOS_DIR, name)
        dst = root / name
        os.symlink(src, dst)
    return str(root)
