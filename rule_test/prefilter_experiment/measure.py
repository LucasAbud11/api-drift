import importlib.util
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
BLIND = os.path.join(os.path.dirname(BASE), "blind_vocab_experiment")
sys.path.insert(0, BLIND)
sys.path.insert(0, BASE)
from gt import GT_TARGET_A_SMALL, GT_TARGET_A_DILUTED, GT_TARGET_B_SMALL, GT_TARGET_B_DILUTED
from prefilter import run_pipeline


def load_vocab_regex(vocab_path):
    spec = importlib.util.spec_from_file_location("vocab_module", vocab_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return re.compile("|".join(f"(?:{p})" for p in mod.PATTERNS.values()))


VOCAB_A = load_vocab_regex(os.path.join(BLIND, "vocab_targetA_blind.py"))
VOCAB_B = load_vocab_regex(os.path.join(BLIND, "vocab_targetB_blind.py"))

# Module-qualified relevance patterns, not bare tokens: a file whose only
# connection to "mcp" is that it lives in a repo/package named
# "youtrack_mcp" or "trello-mcp-server" must NOT pass this filter merely
# on that naming coincidence -- it has to actually import the package, or
# (for the one legitimate exception in this study) reference the
# module-path string the way the QAInsights test stub does.
RELEVANCE_A = re.compile(r'\bimport\s+openai\b|\bfrom\s+openai[.\s]|\bopenai\.')
RELEVANCE_B = re.compile(r'\bimport\s+mcp\b|\bfrom\s+mcp[.\s]|mcp\.server\.|mcp\.client\.|\bmcp\.types\b|sys\.modules\[.mcp')

SCALES = [
    ("targetA_small", GT_TARGET_A_SMALL, "candidates_targetA_small_blind.json",
     "/Users/lucasabud/Projects/api-drift/repos", RELEVANCE_A, VOCAB_A),
    ("targetA_diluted", GT_TARGET_A_DILUTED, "candidates_targetA_diluted_blind.json",
     "/Users/lucasabud/Projects/api-drift/rule_test/scale_experiment/host", RELEVANCE_A, VOCAB_A),
    ("targetB_small", GT_TARGET_B_SMALL, "candidates_targetB_small_blind.json",
     "/Users/lucasabud/Projects/api-drift/repos", RELEVANCE_B, VOCAB_B),
    ("targetB_diluted", GT_TARGET_B_DILUTED, "candidates_targetB_diluted_blind.json",
     "/Users/lucasabud/Projects/api-drift/rule_test/scale_experiment/host", RELEVANCE_B, VOCAB_B),
]


def gt_covered(candidates_or_reps, expansion_map, gt):
    """A GT site is covered if it appears as a plain candidate OR inside some
    representative's duplicate_lines (post stage C)."""
    covered = set()
    for c in candidates_or_reps:
        covered.add((c["file"], c["line"]))
        for dl in c.get("duplicate_lines", []):
            covered.add((c["file"], dl))
    return gt & covered, gt - covered


def main():
    overall = {}
    for scale, gt, cand_file, repo_root, relevance_pattern, vocab_regex in SCALES:
        candidates = json.load(open(os.path.join(BLIND, cand_file)))
        print(f"##### {scale} #####")
        print(f"  raw candidates: {len(candidates)}  |  GT: {len(gt)}")

        # run each stage cumulatively, checking GT loss after each
        for stage_set, label in [
            (("A",), "A only"),
            (("A", "B"), "A+B"),
            (("A", "B", "C"), "A+B+C"),
        ]:
            final, expansion_map, stats = run_pipeline(candidates, repo_root, relevance_pattern, vocab_regex=vocab_regex, stages=stage_set)
            found, missing = gt_covered(final, expansion_map, gt)
            reduction = (1 - stats["final"] / stats["start"]) * 100
            print(f"  [{label:8s}] {stats} -> {stats['final']} final items, "
                  f"reduction={reduction:.1f}%, GT covered={len(found)}/{len(gt)}"
                  + (f"  !!MISSING: {sorted(missing)}" if missing else ""))
        print()
        overall[scale] = stats
    return overall


if __name__ == "__main__":
    main()
