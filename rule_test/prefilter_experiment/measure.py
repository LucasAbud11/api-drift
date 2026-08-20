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
from prefilter import run_pipeline, build_relevance_pattern


def load_vocab_regex(vocab_path):
    spec = importlib.util.spec_from_file_location("vocab_module", vocab_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return re.compile("|".join(f"(?:{p})" for p in mod.PATTERNS.values()))


VOCAB_A = load_vocab_regex(os.path.join(BLIND, "vocab_targetA_blind.py"))
VOCAB_B = load_vocab_regex(os.path.join(BLIND, "vocab_targetB_blind.py"))

# Broadened, fail-safe-by-construction relevance patterns (see prefilter.py's
# module docstring / AUDIT NOTE) -- covers aliased imports, importlib,
# __import__, and any string literal containing the package's dotted-path
# prefix, not just the narrow "import X / from X" forms the first version
# checked for.
RELEVANCE_A = build_relevance_pattern("openai")
RELEVANCE_B = build_relevance_pattern("mcp")

PROJECT_ROOT = os.path.dirname(os.path.dirname(BASE))
REPOS_DIR = os.path.join(PROJECT_ROOT, "repos")
SCALE_HOST_DIR = os.path.join(BASE, "..", "scale_experiment", "host")

SCALES = [
    ("targetA_small", GT_TARGET_A_SMALL, "candidates_targetA_small_blind.json",
     REPOS_DIR, RELEVANCE_A, VOCAB_A),
    ("targetA_diluted", GT_TARGET_A_DILUTED, "candidates_targetA_diluted_blind.json",
     SCALE_HOST_DIR, RELEVANCE_A, VOCAB_A),
    ("targetB_small", GT_TARGET_B_SMALL, "candidates_targetB_small_blind.json",
     REPOS_DIR, RELEVANCE_B, VOCAB_B),
    ("targetB_diluted", GT_TARGET_B_DILUTED, "candidates_targetB_diluted_blind.json",
     SCALE_HOST_DIR, RELEVANCE_B, VOCAB_B),
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
        final_log = []
        for stage_set, label in [
            (("A",), "A only"),
            (("A", "B"), "A+B"),
            (("A", "B", "C"), "A+B+C"),
        ]:
            final, expansion_map, stats, log = run_pipeline(
                candidates, repo_root, relevance_pattern, vocab_regex=vocab_regex, stages=stage_set)
            found, missing = gt_covered(final, expansion_map, gt)
            reduction = (1 - stats["final"] / stats["start"]) * 100
            print(f"  [{label:8s}] {stats} -> {stats['final']} final items, "
                  f"reduction={reduction:.1f}%, GT covered={len(found)}/{len(gt)}"
                  + (f"  !!MISSING: {sorted(missing)}" if missing else ""))
            if stage_set == ("A", "B", "C"):
                final_log = log
        print()
        overall[scale] = stats

        log_path = os.path.join(BASE, f"droplog_{scale}.json")
        with open(log_path, "w") as f:
            json.dump(final_log, f, indent=2)
        print(f"  audit log ({len(final_log)} entries) written to {log_path}\n")
    return overall


if __name__ == "__main__":
    main()
