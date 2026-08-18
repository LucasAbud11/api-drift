"""Generic coverage-tuned candidate generator, parameterized by an
arbitrary PATTERNS dict (imported from a vocab_*.py module). Same
mechanics as scale_experiment/grep_candidates.py, generalized to take
the vocabulary as an argument instead of hardcoding it, so the blind
vocabulary and the hand-tuned vocabulary can be run through identical
code and compared fairly.
"""
import importlib.util
import json
import os
import re
import sys


def load_vocab(vocab_path):
    spec = importlib.util.spec_from_file_location("vocab_module", vocab_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.PATTERNS


def find_candidates(root_dir, patterns, restrict_to_relpaths=None):
    combined = re.compile("|".join(f"(?:{p})" for p in patterns.values()))
    results = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, root_dir)
            if restrict_to_relpaths is not None:
                if not any(rel == r or rel.startswith(r + os.sep) for r in restrict_to_relpaths):
                    continue
            try:
                with open(full, encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
            except OSError:
                continue
            for i, line in enumerate(lines, start=1):
                if combined.search(line):
                    results.append({"file": rel, "line": i, "snippet": line.rstrip("\n")})
    return results


def main():
    if len(sys.argv) < 4:
        print("usage: python build_candidates.py <vocab_module.py> <root_dir> <output.json> [restrict_prefix ...]")
        sys.exit(1)
    vocab_path, root_dir, out_path = sys.argv[1:4]
    restrict = set(sys.argv[4:]) if len(sys.argv) > 4 else None

    patterns = load_vocab(vocab_path)
    candidates = find_candidates(root_dir, patterns, restrict)
    with open(out_path, "w") as f:
        json.dump(candidates, f, indent=2)

    by_top = {}
    for c in candidates:
        top = c["file"].split(os.sep)[0]
        by_top[top] = by_top.get(top, 0) + 1
    print(f"Vocabulary: {vocab_path}")
    print(f"Total candidates: {len(candidates)}")
    for top, n in sorted(by_top.items()):
        print(f"  {top}: {n}")
    print(f"Written to {out_path}")


if __name__ == "__main__":
    main()
