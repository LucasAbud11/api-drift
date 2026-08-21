"""
Deterministic, mechanical pre-filter between grep and agent adjudication.
No LLM involved anywhere in this file.

Adapted from rule_test/prefilter_experiment/prefilter.py -- logic
unchanged, only the file-access mechanism is swapped: every read goes
through a RepoReader (apidrift/reposafe.py) instead of raw os.walk/open,
so this module cannot write to the target repo even by accident (the
reader it's handed has no write method to call).

FAIL-SAFE PRINCIPLE (binding on every stage below, carried forward
unchanged): a candidate is only ever dropped when the reason for dropping
it is provably, syntactically certain -- not merely "no evidence of
relevance was found." Where a stage cannot establish certainty, the
candidate is kept. Every actual drop is logged with the stage, the
specific rule that fired, the file/line, and the matched span/text.

  A. file_relevance -- drop a file's candidates only if the broadened
     module-qualified reference pattern finds nothing DIRECTLY in the
     file AND the file does not TRANSITIVELY import (through the repo's
     own intra-repo import graph, resolved via `ast`) any other file that
     does.

  B. comment_and_docstring -- drop a match ONLY if it is entirely inside
     a `#` comment or a real docstring (first statement of a
     module/class/function body, identified structurally via AST).
     Generic string-literal matches are kept unconditionally.

  C. collapse_duplicates -- not a drop. Groups candidates within one file
     whose stripped snippet text is byte-identical and routes them to the
     agent as ONE representative item; the verdict is expanded back to
     every original line before scoring.
"""
import ast
import io
import re
import tokenize
from collections import defaultdict


def build_relevance_pattern(package_name):
    pkg = re.escape(package_name)
    parts = [
        rf'\bimport\s+{pkg}\b',
        rf'\bfrom\s+{pkg}[.\s]',
        rf'\bimport\s+{pkg}\s+as\s+\w+',
        rf'\bfrom\s+{pkg}\.\S+\s+import',
        rf'\b{pkg}\.\w+',
        rf'sys\.modules\[[\'"][^\'"]*{pkg}',
        rf'importlib\.import_module\([\'"][^\'"]*{pkg}',
        rf'__import__\([\'"][^\'"]*{pkg}',
        rf'[\'"][^\'"]*\b{pkg}\.[a-zA-Z_]',
    ]
    return re.compile("|".join(parts))


def _module_root_and_dotted_name(rel_path, py_files):
    parts = rel_path.split("/")
    if parts[-1] == "__init__.py":
        pkg_parts = parts[:-1]
    else:
        pkg_parts = parts[:-1] + [parts[-1][:-3]]

    dir_parts = parts[:-1]
    depth = len(dir_parts)
    while depth > 0:
        candidate_init = "/".join(dir_parts[:depth]) + "/__init__.py"
        if candidate_init not in py_files:
            break
        depth -= 1
    dotted = ".".join(pkg_parts[depth:])
    return dotted


def _extract_imports(reader, rel_path, py_files):
    try:
        src = reader.read_text(rel_path)
        tree = ast.parse(src)
    except (OSError, SyntaxError):
        return []

    self_dotted = _module_root_and_dotted_name(rel_path, py_files)
    self_pkg_parts = self_dotted.split(".")
    if not rel_path.endswith("__init__.py"):
        self_pkg_parts = self_pkg_parts[:-1]

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


def _build_import_graph(reader, py_files):
    index = {}
    for rel_path in py_files:
        dotted = _module_root_and_dotted_name(rel_path, py_files)
        index[dotted] = rel_path
    graph = {f: set() for f in py_files}
    for rel_path in py_files:
        for dotted in _extract_imports(reader, rel_path, py_files):
            if dotted in index and index[dotted] != rel_path:
                graph[rel_path].add(index[dotted])
    return graph


def _transitive_relevant_files(reader, py_files, pattern):
    direct = set()
    for rel_path in py_files:
        try:
            if pattern.search(reader.read_text(rel_path)):
                direct.add(rel_path)
        except OSError:
            direct.add(rel_path)  # can't be certain -> keep (fail-safe)

    graph = _build_import_graph(reader, py_files)
    relevant = set(direct)
    changed = True
    while changed:
        changed = False
        for f, imported in graph.items():
            if f not in relevant and (imported & relevant):
                relevant.add(f)
                changed = True
    return direct, relevant


def stage_a_file_relevance(candidates, reader, target_pattern):
    py_files = reader.list_py_files()
    direct, transitive = _transitive_relevant_files(reader, py_files, target_pattern)

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


def _analyze_file_for_stage_b(reader, rel_path):
    try:
        src = reader.read_text(rel_path)
    except OSError:
        return [], {}, set()

    lines = src.splitlines()

    comment_spans = defaultdict(list)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                comment_spans[tok.start[0]].append((tok.start[1], tok.end[1]))
    except (tokenize.TokenizeError, IndentationError, SyntaxError, ValueError):
        pass

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
    for s, e in spans:
        if s <= col_start and col_end <= e:
            return True
    return False


def stage_b_comment_and_docstring(candidates, reader, vocab_regex):
    kept, dropped, log = [], [], []
    analysis_cache = {}
    for c in candidates:
        f = c["file"]
        if f not in analysis_cache:
            analysis_cache[f] = _analyze_file_for_stage_b(reader, f)
        lines, comment_spans, docstring_lines = analysis_cache[f]

        ln = c["line"]
        if ln < 1 or ln > len(lines):
            kept.append(c)
            continue

        line_text = lines[ln - 1]
        matches = list(vocab_regex.finditer(line_text))
        if not matches:
            kept.append(c)
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


def run_pipeline(candidates, reader, target_pattern, vocab_regex=None, stages=("A", "B", "C")):
    stats = {"start": len(candidates)}
    full_log = []
    cur = candidates
    if "A" in stages:
        cur, dropped_a, log_a = stage_a_file_relevance(cur, reader, target_pattern)
        stats["after_A"] = len(cur)
        stats["dropped_by_A"] = len(dropped_a)
        full_log.extend(log_a)
    if "B" in stages:
        assert vocab_regex is not None, "stage B requires vocab_regex"
        cur, dropped_b, log_b = stage_b_comment_and_docstring(cur, reader, vocab_regex)
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
