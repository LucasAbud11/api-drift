"""
Deterministic, mechanical pre-filter between grep and agent adjudication.
No LLM involved anywhere in this file.

FAIL-SAFE PRINCIPLE (binding on every stage below): a candidate is only
ever dropped when the reason for dropping it is provably, syntactically
certain -- not merely "no evidence of relevance was found." Absence of a
positive match is not the same thing as proof of irrelevance, and this
file must not conflate the two. Where a stage cannot establish certainty,
the candidate is kept. Every actual drop is logged with the stage, the
specific rule that fired, the file/line, and the matched span/text, so
any exclusion is auditable after the fact without re-running anything.

  A. file_relevance -- drop a file's candidates only if the broadened
     module-qualified reference pattern finds nothing DIRECTLY in the
     file AND the file does not TRANSITIVELY import (through the repo's
     own intra-repo import graph, resolved via `ast`, not string
     heuristics) any other file that does. This closes the entanglement
     gap the file-local-only version had: a file can use the target
     package's data/behavior entirely through the host's own wrapper
     layer and never itself contain any reference to the package -- see
     `rule_test/entanglement_experiment/report.md` for the concrete
     production-code site (`tool_catalog.py:46`) this exact gap silently
     dropped before this change. This is still the one stage that cannot
     reach true certainty: a file could receive SDK-shaped data through
     a channel the import graph doesn't model at all (a value passed
     into a plain function parameter with no import edge, pure runtime
     duck-typing, a plugin/callback registry) -- transitive-via-imports
     is a real, measured improvement over file-local-only, not a claim
     of completeness. That residual risk is reduced further and made
     fully auditable via the drop log, so a missed file is discoverable,
     not silently gone. See AUDIT NOTE below.

  B. comment_and_docstring -- drop a match ONLY if it is entirely inside
     a `#` comment (never executable, always certain) or entirely inside
     a real docstring (first statement of a module/class/function body,
     identified structurally via AST -- also certain, since docstrings
     are never evaluated as code by the interpreter). Earlier versions
     of this stage also dropped matches inside ordinary string literals
     (dict values, log-message arguments, etc.) whenever they weren't on
     a two-item hand-built whitelist. That was the same certainty
     violation as stage A, scoped to strings: absence from a short,
     study-specific whitelist is not proof a string is safe to drop.
     Generic string-literal matches are now KEPT unconditionally -- the
     agent adjudicates them like any other candidate.

  C. collapse_duplicates -- not a drop at all. Groups candidates within
     one file whose (stripped) snippet text is byte-identical and routes
     them to the agent as ONE representative item; the single verdict is
     expanded back to every original line before scoring. Provably
     lossless as long as expansion is correct (verified separately), so
     this is not subject to the same certainty concern -- it changes how
     many times a line is judged, never how many lines end up judged.
     Every collapse is still logged for auditability.

AUDIT NOTE (from the 2026-08-18 review): stage A cannot be made fully
certain by construction -- "this file was not found to reference the
package, directly or transitively" is structurally an absence-based
claim no matter how the pattern is written or how far the import graph
is walked, because Python allows references neither the pattern nor the
import graph enumerate (dynamic module-name construction, runtime
duck-typing across a channel with no import edge at all). It remains in
the pipeline because, broadened, made transitive, and logged, its
false-negative rate is low enough to be worth the reduction it buys, and
because every drop it makes is recorded with the exact reason -- but it
is the one stage where "kept because uncertain" does not fully apply,
and that should not be papered over.

AUDIT NOTE (2026-08-18, transitive relevance shipped): the file-local-
only version of this stage silently dropped a real, production-code GT
site in the entanglement experiment (`tool_catalog.py:46` -- see
`rule_test/entanglement_experiment/report.md`) precisely because that
file used the SDK's data shape only through a host-internal wrapper and
never referenced the package by name itself. Transitive relevance is
shipped specifically to close that gap: measured to cost real reduction
power on a host that actually exercises entanglement (49.3% -> 36.2% on
the entangled host) and to cost nothing on the one diluted host tested
so far (90.1% unchanged) -- but that diluted host is an assembly of
independent small repos with no shared "core" module most files import,
which is exactly the topology where transitive closure stays cheap. On
a real monorepo with a shared internal SDK/framework layer, transitive
closure could plausibly approach "almost nothing gets dropped," making
stage A's reduction value close to zero there. If that happens, the
documented fallback is dropping stage A entirely (stages B/C only) and
absorbing the higher adjudication volume -- a cost problem, not a
correctness one, and correctness (no silent production misses) is the
property this stage exists to protect, not reduction ratio.
"""
import ast
import io
import json
import os
import re
import tokenize
from collections import defaultdict

# Broadened relevance pattern components, reusable across targets. A
# caller still supplies the target-specific dotted-path fragments (e.g.
# "mcp" or "openai"); this function builds the full set of reference
# FORMS around that package name rather than just "import X" / "from X".
def build_relevance_pattern(package_name):
    pkg = re.escape(package_name)
    parts = [
        rf'\bimport\s+{pkg}\b',                       # import mcp
        rf'\bfrom\s+{pkg}[.\s]',                       # from mcp import X / from mcp.server...
        rf'\bimport\s+{pkg}\s+as\s+\w+',               # import mcp as m
        rf'\bfrom\s+{pkg}\.\S+\s+import',              # from mcp.server.fastmcp import X
        rf'\b{pkg}\.\w+',                              # mcp.server., mcp.types, mcp.anything -- qualified attribute/module access
        rf'sys\.modules\[[\'"][^\'"]*{pkg}',           # sys.modules['mcp...'] / ["mcp..."]
        rf'importlib\.import_module\([\'"][^\'"]*{pkg}',  # importlib.import_module("mcp...")
        rf'__import__\([\'"][^\'"]*{pkg}',             # __import__("mcp...")
        rf'[\'"][^\'"]*\b{pkg}\.[a-zA-Z_]',            # any string literal containing "mcp.something" as a substring
    ]
    return re.compile("|".join(parts))


def _find_py_files(repo_root):
    out = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(".py"):
                out.append(os.path.relpath(os.path.join(dirpath, fn), repo_root))
    return out


def _module_root_and_dotted_name(rel_path, repo_root):
    """Walk up from rel_path while ancestor dirs have __init__.py; the
    first ancestor WITHOUT __init__.py is this file's true sys.path root
    (standard Python package-resolution rule, not a heuristic). Returns
    (root_rel_dir, dotted_name), scoped naturally within one repo without
    hand-coded per-repo paths -- unrelated repos have no __init__.py
    chain connecting them, so this never crosses repo boundaries."""
    parts = rel_path.split(os.sep)
    if parts[-1] == "__init__.py":
        pkg_parts = parts[:-1]
    else:
        pkg_parts = parts[:-1] + [parts[-1][:-3]]  # strip .py

    dir_parts = parts[:-1]
    depth = len(dir_parts)
    while depth > 0:
        candidate_dir = os.path.join(repo_root, *dir_parts[:depth])
        if not os.path.isfile(os.path.join(candidate_dir, "__init__.py")):
            break
        depth -= 1
    root_rel_dir = os.sep.join(dir_parts[:depth]) if depth else ""
    dotted = ".".join(pkg_parts[depth:])
    return root_rel_dir, dotted


def _extract_imports(repo_root, rel_path):
    """Dotted module names this file imports, via `ast` (not import-syntax
    heuristics). Relative imports are resolved against this file's own
    package. A file that fails to parse contributes no outgoing edges --
    it doesn't lose its OWN direct-relevance eligibility, it just can't
    propagate relevance to whatever it might have imported."""
    full = os.path.join(repo_root, rel_path)
    try:
        with open(full, encoding="utf-8", errors="replace") as f:
            src = f.read()
        tree = ast.parse(src)
    except (OSError, SyntaxError):
        return []

    _, self_dotted = _module_root_and_dotted_name(rel_path, repo_root)
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


def _build_import_graph(repo_root, py_files):
    index = {}
    for rel_path in py_files:
        _, dotted = _module_root_and_dotted_name(rel_path, repo_root)
        index[dotted] = rel_path
    graph = {f: set() for f in py_files}
    for rel_path in py_files:
        for dotted in _extract_imports(repo_root, rel_path):
            if dotted in index and index[dotted] != rel_path:
                graph[rel_path].add(index[dotted])
    return graph


def _transitive_relevant_files(repo_root, py_files, pattern):
    """Returns (direct, transitive): files matching the pattern directly,
    and the closure of that set under "imports a relevant file" (fixpoint
    over the intra-repo import graph). Unreadable files default to
    directly relevant -- can't be certain, so keep (fail-safe)."""
    direct = set()
    for rel_path in py_files:
        full = os.path.join(repo_root, rel_path)
        try:
            with open(full, encoding="utf-8", errors="replace") as fh:
                if pattern.search(fh.read()):
                    direct.add(rel_path)
        except OSError:
            direct.add(rel_path)

    graph = _build_import_graph(repo_root, py_files)
    relevant = set(direct)
    changed = True
    while changed:
        changed = False
        for f, imported in graph.items():
            if f not in relevant and (imported & relevant):
                relevant.add(f)
                changed = True
    return direct, relevant


def stage_a_file_relevance(candidates, repo_root, target_pattern):
    """Keep a candidate unless its file has ZERO matches for target_pattern,
    directly or transitively through the repo's own import graph. See
    module docstring's AUDIT NOTEs: broadened, made transitive, and fully
    logged, but still not a claim of true certainty (see AUDIT NOTE)."""
    py_files = _find_py_files(repo_root)
    direct, transitive = _transitive_relevant_files(repo_root, py_files, target_pattern)

    kept, dropped, log = [], [], []
    for c in candidates:
        f = c["file"]
        if f in transitive:
            kept.append(c)
        else:
            dropped.append(c)
            log.append({
                "stage": "A", "rule": "file_relevance_no_match_transitive",
                "file": c["file"], "line": c["line"], "snippet": c.get("snippet", ""),
                "matched_span": None,
                "reason": "no occurrence of the broadened package-relevance pattern found "
                          "in this file, directly or transitively through any intra-repo "
                          "import chain reaching a file that does match",
            })
    return kept, dropped, log


def _analyze_file_for_stage_b(full_path):
    """Returns (lines, comment_spans, docstring_lines):
      lines            -- the file's physical lines, for re-matching
      comment_spans    -- {line: [(start_col, end_col), ...]} for COMMENT tokens
      docstring_lines  -- 1-indexed line numbers that are part of a real docstring
                           (first statement of a module/class/function body)
    Both comment and docstring detection are structurally certain (not
    heuristic): a COMMENT token is never executable by definition, and a
    docstring is identified by its syntactic position (first statement of
    a body), not by guessing at content.
    """
    try:
        with open(full_path, encoding="utf-8", errors="replace") as fh:
            src = fh.read()
    except OSError:
        return [], {}, set()

    lines = src.splitlines()

    comment_spans = defaultdict(list)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                comment_spans[tok.start[0]].append((tok.start[1], tok.end[1]))
    except (tokenize.TokenizeError, IndentationError, SyntaxError, ValueError):
        pass  # partial/no comment data -> fewer certain drops, never more (fail-safe)

    docstring_lines = set()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        tree = None

    if tree is not None:
        def mark_docstring(body):
            if body and isinstance(body[0], ast.Expr):
                val = body[0].value
                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                    start, end = val.lineno, getattr(val, "end_lineno", val.lineno)
                    for ln in range(start, end + 1):
                        docstring_lines.add(ln)

        mark_docstring(tree.body)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                mark_docstring(node.body)

    return lines, comment_spans, docstring_lines


def _span_covers(spans, col_start, col_end):
    """True if [col_start, col_end) is fully contained in at least one span."""
    for s, e in spans:
        if s <= col_start and col_end <= e:
            return True
    return False


def stage_b_comment_and_docstring(candidates, repo_root, vocab_regex):
    """Drops a candidate only if EVERY vocabulary-match span on its line is
    entirely inside a comment, or the whole line is part of a real
    docstring. Generic string literals (dict values, log messages,
    function arguments, etc.) are never dropped here -- kept unconditionally,
    since "not on a hand-built whitelist" is not proof of irrelevance."""
    kept, dropped, log = [], [], []
    analysis_cache = {}
    for c in candidates:
        f = c["file"]
        if f not in analysis_cache:
            analysis_cache[f] = _analyze_file_for_stage_b(os.path.join(repo_root, f))
        lines, comment_spans, docstring_lines = analysis_cache[f]

        ln = c["line"]
        if ln < 1 or ln > len(lines):
            kept.append(c)  # can't analyze -> not certain -> keep
            continue

        line_text = lines[ln - 1]
        matches = list(vocab_regex.finditer(line_text))
        if not matches:
            kept.append(c)  # vocab regex didn't reproduce the match -> not certain -> keep
            continue

        if ln in docstring_lines:
            dropped.append(c)
            log.append({
                "stage": "B", "rule": "docstring",
                "file": c["file"], "line": ln, "snippet": c.get("snippet", ""),
                "matched_span": [(m.start(), m.end()) for m in matches],
                "reason": "line is part of a real docstring (first statement of a "
                          "module/class/function body, confirmed via AST)",
            })
            continue

        line_comment_spans = comment_spans.get(ln, [])
        any_match_outside_comment = any(
            not _span_covers(line_comment_spans, m.start(), m.end()) for m in matches
        )

        if any_match_outside_comment:
            kept.append(c)
        else:
            dropped.append(c)
            log.append({
                "stage": "B", "rule": "comment",
                "file": c["file"], "line": ln, "snippet": c.get("snippet", ""),
                "matched_span": [(m.start(), m.end()) for m in matches],
                "reason": "every vocabulary match on this line falls inside a "
                          "`#` comment token (confirmed via tokenize)",
            })
    return kept, dropped, log


def stage_c_collapse_duplicates(candidates):
    """Group candidates within the same file whose stripped snippet text is
    byte-identical. Returns (representatives, expansion_map, log). Not a
    drop: every collapsed line is still logged and still recoverable via
    expansion_map before scoring."""
    groups = defaultdict(list)
    for c in candidates:
        key = (c["file"], c["snippet"].strip())
        groups[key].append(c)

    representatives = []
    expansion_map = {}
    log = []
    for (f, snippet_stripped), members in groups.items():
        members_sorted = sorted(members, key=lambda c: c["line"])
        rep = dict(members_sorted[0])
        if len(members_sorted) > 1:
            rep["duplicate_count"] = len(members_sorted)
            rep["duplicate_lines"] = [m["line"] for m in members_sorted]
            log.append({
                "stage": "C", "rule": "collapse_duplicate",
                "file": f, "line": members_sorted[0]["line"], "snippet": snippet_stripped,
                "matched_span": None,
                "reason": f"{len(members_sorted)} byte-identical lines in this file "
                          f"collapsed to one adjudication: lines "
                          f"{[m['line'] for m in members_sorted]}",
            })
        representatives.append(rep)
        expansion_map[(f, members_sorted[0]["line"])] = members_sorted
    return representatives, expansion_map, log


def run_pipeline(candidates, repo_root, target_pattern, vocab_regex=None, stages=("A", "B", "C")):
    """Runs the requested stages in order A -> B -> C. Returns
    (final_candidates, expansion_map, stats, full_log) where full_log is
    the concatenation of every stage's per-item audit log, in order."""
    stats = {"start": len(candidates)}
    full_log = []
    cur = candidates
    if "A" in stages:
        cur, dropped_a, log_a = stage_a_file_relevance(cur, repo_root, target_pattern)
        stats["after_A"] = len(cur)
        stats["dropped_by_A"] = len(dropped_a)
        full_log.extend(log_a)
    if "B" in stages:
        assert vocab_regex is not None, "stage B requires vocab_regex"
        cur, dropped_b, log_b = stage_b_comment_and_docstring(cur, repo_root, vocab_regex)
        stats["after_B"] = len(cur)
        stats["dropped_by_B"] = len(dropped_b)
        full_log.extend(log_b)
    expansion_map = {}
    if "C" in stages:
        cur, expansion_map, log_c = stage_c_collapse_duplicates(cur)
        stats["after_C"] = len(cur)
        stats["collapsed_by_C"] = stats.get("after_B", stats.get("after_A", stats["start"])) - len(cur)
        full_log.extend(log_c)
    stats["final"] = len(cur)
    return cur, expansion_map, stats, full_log
