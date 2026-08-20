"""
PROPOSAL, NOT SHIPPED: measures what a transitive-import-graph version of
prefilter.py's stage A would cost in reduction power, on both the diluted
host (where stage A is the dominant reduction lever) and the entangled host
(where the current file-local stage A silently drops real GT).

Current stage A (prefilter.py): keep a file's candidates iff a broadened
relevance PATTERN matches somewhere in that file's own text. This is
structurally wrong for entanglement: a file can use the SDK entirely
through a host-internal wrapper (e.g. `from opsmesh.client import
FleetClient`) and never itself contain the string "mcp" anywhere -- see
tool_catalog.py and test_orchestrator_agent.py in the entanglement host.

Proposed replacement: a file is relevant if it directly matches the
pattern, OR it imports (transitively, through the repo's own intra-repo
import graph) some file that does. This script builds that import graph
with Python's own `ast` module (no heuristics on import syntax) and
resolves module dotted-names to files using the standard "walk up while
__init__.py exists" rule to find each file's true sys.path root -- so it
naturally stays scoped within one repo without hand-coded per-repo roots.

This file does NOT modify prefilter.py. It is a standalone measurement.
"""
import ast
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(BASE), "prefilter_experiment"))
sys.path.insert(0, os.path.join(os.path.dirname(BASE), "blind_vocab_experiment"))
from prefilter import stage_b_comment_and_docstring, stage_c_collapse_duplicates, build_relevance_pattern
import importlib.util
import re


def load_vocab_regex(vocab_path):
    spec = importlib.util.spec_from_file_location("vocab_module", vocab_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return re.compile("|".join(f"(?:{p})" for p in mod.PATTERNS.values()))


def find_py_files(root):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(".py"):
                out.append(os.path.relpath(os.path.join(dirpath, fn), root))
    return out


def module_root_and_dotted_name(rel_path, root):
    """Walk up from rel_path while ancestor dirs have __init__.py; the first
    ancestor WITHOUT __init__.py is this file's resolution root. Returns
    (root_rel_dir, dotted_name)."""
    parts = rel_path.split(os.sep)
    if parts[-1] == "__init__.py":
        pkg_parts = parts[:-1]
    else:
        pkg_parts = parts[:-1] + [parts[-1][:-3]]  # strip .py

    # walk up from the immediate containing directory
    dir_parts = parts[:-1]
    depth = len(dir_parts)
    while depth > 0:
        candidate_dir = os.path.join(root, *dir_parts[:depth])
        if not os.path.isfile(os.path.join(candidate_dir, "__init__.py")):
            break
        depth -= 1
    root_rel_dir = os.sep.join(dir_parts[:depth]) if depth else ""
    dotted = ".".join(pkg_parts[depth:])
    return root_rel_dir, dotted


def build_module_index(root, py_files):
    """dotted_name -> rel_path, scoped per discovered root (last-wins on
    collision across genuinely different repos, which should not occur in
    practice since unrelated repos use distinct top-level package names)."""
    index = {}
    for rel_path in py_files:
        _, dotted = module_root_and_dotted_name(rel_path, root)
        index[dotted] = rel_path
        # also index the package form (dir without __init__) so "import pkg"
        # resolves to pkg/__init__.py
    return index


def extract_imports(root, rel_path):
    """Returns a list of dotted module names this file imports (absolute
    form only; relative imports are resolved using this file's own package)."""
    full = os.path.join(root, rel_path)
    try:
        with open(full, encoding="utf-8", errors="replace") as f:
            src = f.read()
        tree = ast.parse(src)
    except (OSError, SyntaxError):
        return []

    _, self_dotted = module_root_and_dotted_name(rel_path, root)
    self_pkg_parts = self_dotted.split(".")
    if not rel_path.endswith("__init__.py"):
        self_pkg_parts = self_pkg_parts[:-1]  # containing package, not the module itself

    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                # relative import: resolve against this file's package
                base = self_pkg_parts[: len(self_pkg_parts) - (node.level - 1)] if node.level > 1 else self_pkg_parts
                base_dotted = ".".join(base)
                mod = f"{base_dotted}.{node.module}" if node.module else base_dotted
                imports.append(mod)
                for alias in node.names:
                    imports.append(f"{mod}.{alias.name}")
            elif node.module:
                imports.append(node.module)
                for alias in node.names:
                    imports.append(f"{node.module}.{alias.name}")
    return imports


def build_import_graph(root, py_files):
    index = build_module_index(root, py_files)
    graph = {f: set() for f in py_files}
    for rel_path in py_files:
        for dotted in extract_imports(root, rel_path):
            if dotted in index and index[dotted] != rel_path:
                graph[rel_path].add(index[dotted])
    return graph, index


def transitive_relevant_files(root, py_files, relevance_pattern):
    direct = set()
    for rel_path in py_files:
        full = os.path.join(root, rel_path)
        try:
            with open(full, encoding="utf-8", errors="replace") as f:
                if relevance_pattern.search(f.read()):
                    direct.add(rel_path)
        except OSError:
            direct.add(rel_path)  # fail-safe: unreadable -> keep

    graph, _ = build_import_graph(root, py_files)
    relevant = set(direct)
    changed = True
    while changed:
        changed = False
        for f, imported in graph.items():
            if f not in relevant and (imported & relevant):
                relevant.add(f)
                changed = True
    return direct, relevant


def measure(label, root, candidates, package_name, vocab_path):
    py_files = find_py_files(root)
    pattern = build_relevance_pattern(package_name)
    direct, transitive = transitive_relevant_files(root, py_files, pattern)

    vocab_regex = load_vocab_regex(vocab_path)

    def run_stageA_variant(relevant_files):
        kept = [c for c in candidates if c["file"] in relevant_files]
        after_b, _, _ = stage_b_comment_and_docstring(kept, root, vocab_regex)
        after_c, _, _ = stage_c_collapse_duplicates(after_b)
        return len(kept), len(after_b), len(after_c)

    a_direct, b_direct, c_direct = run_stageA_variant(direct)
    a_trans, b_trans, c_trans = run_stageA_variant(transitive)

    print(f"\n===== {label} =====")
    print(f"  total .py files: {len(py_files)}")
    print(f"  files directly relevant (current stage A): {len(direct)}")
    print(f"  files transitively relevant (proposed stage A): {len(transitive)}  "
          f"(+{len(transitive) - len(direct)} recovered via import graph)")
    print(f"  raw candidates: {len(candidates)}")
    print(f"  CURRENT  (direct-only):    after A={a_direct:4d}  after A+B={b_direct:4d}  after A+B+C={c_direct:4d}"
          f"  reduction={100*(1-c_direct/len(candidates)):.1f}%")
    print(f"  PROPOSED (transitive):     after A={a_trans:4d}  after A+B={b_trans:4d}  after A+B+C={c_trans:4d}"
          f"  reduction={100*(1-c_trans/len(candidates)):.1f}%")
    return {
        "label": label, "total_files": len(py_files),
        "direct_relevant_files": len(direct), "transitive_relevant_files": len(transitive),
        "raw_candidates": len(candidates),
        "current_final": c_direct, "current_reduction_pct": 100 * (1 - c_direct / len(candidates)),
        "proposed_final": c_trans, "proposed_reduction_pct": 100 * (1 - c_trans / len(candidates)),
    }


def main():
    results = []

    # Entangled host
    ent_candidates = json.load(open(os.path.join(BASE, "candidates_raw.json")))
    results.append(measure(
        "entangled host (OpsMesh)",
        os.path.join(BASE, "host"),
        ent_candidates, "mcp",
        os.path.join(os.path.dirname(BASE), "blind_vocab_experiment", "vocab_targetB_blind.py"),
    ))

    # Diluted Target B host (the same one measure.py scores as targetB_diluted)
    BLIND = os.path.join(os.path.dirname(BASE), "blind_vocab_experiment")
    diluted_candidates = json.load(open(os.path.join(BLIND, "candidates_targetB_diluted_blind.json")))
    results.append(measure(
        "diluted host (Django + 5 MCP repos + 4 OpenAI repos)",
        os.path.join(os.path.dirname(BASE), "scale_experiment", "host"),
        diluted_candidates, "mcp",
        os.path.join(BLIND, "vocab_targetB_blind.py"),
    ))

    with open(os.path.join(BASE, "transitive_relevance_results.json"), "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
