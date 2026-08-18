"""
Deterministic, mechanical pre-filter between grep and agent adjudication.
No LLM involved anywhere in this file. Three independent stages, each
individually measurable and individually disable-able:

  A. file_relevance  -- drop every candidate in a file that never
     mentions the target package name anywhere in the file, at all
     (not just on the matched line). Catches "coincidental vocabulary
     overlap in files that have nothing to do with the target package"
     (e.g. Django's own get_context()/Context/cursor= matching Target
     B's vocabulary despite zero relationship to the mcp package).

  B. comment_docstring_string -- drop candidates whose match is
     entirely inside a comment or a docstring, or inside an ordinary
     string literal, UNLESS the literal is one of the two syntactic
     forms this study's own spec says are load-bearing: the string
     argument to types.ModuleType(...), or a string key on
     sys.modules[...]. Everything else about a pattern's true
     positives (imports, constructions, attribute access, type
     annotations) is never a string or comment to begin with, so this
     stage only ever removes prose/log-message/dict-key/wire-format
     noise, never a real site under this study's own counting
     convention.

  C. collapse_duplicates -- within one file, group candidates whose
     (stripped) snippet text is byte-identical and route them to the
     agent as ONE representative item carrying every line number it
     stands for. The agent's single verdict is expanded back out to
     every original line before scoring, so this only ever reduces how
     many times the agent has to reason about a line, never how many
     lines end up in the final proposed/flagged/rejected accounting.
"""
import ast
import io
import json
import os
import re
import tokenize
from collections import defaultdict


def stage_a_file_relevance(candidates, repo_root, target_pattern):
    """Keep a candidate only if its file contains target_pattern ANYWHERE in the
    file -- not just on the matched line. target_pattern is a compiled regex:
    pass a module-qualified pattern (e.g. r'\\bimport\\s+mcp\\b|\\bfrom\\s+mcp[.\\s]|mcp\\.server\\.')
    rather than a bare token, or files that merely happen to have the target
    name baked into an unrelated package/repo name (e.g. "youtrack_mcp",
    "trello-mcp-server") will pass this filter without ever actually using the
    target package -- exactly the case that made this stage weak when it was a
    bare substring check."""
    pattern = target_pattern
    file_cache = {}
    kept, dropped = [], []
    for c in candidates:
        f = c["file"]
        if f not in file_cache:
            full_path = os.path.join(repo_root, f)
            try:
                with open(full_path, encoding="utf-8", errors="replace") as fh:
                    file_cache[f] = bool(pattern.search(fh.read()))
            except OSError:
                file_cache[f] = False
        if file_cache[f]:
            kept.append(c)
        else:
            dropped.append(c)
    return kept, dropped


def _analyze_file_for_stage_b(full_path):
    """Returns (lines, comment_spans, string_spans, docstring_lines, whitelist_lines):
      lines            -- the file's physical lines (0-indexed list), for re-matching
      comment_spans    -- {line: [(start_col, end_col), ...]} for COMMENT tokens
      string_spans     -- {line: [(start_col, end_col), ...]} for STRING/FSTRING tokens
                           (multi-line strings contribute a full-line span to every
                           line strictly between their start and end line)
      docstring_lines  -- 1-indexed line numbers that are part of a real docstring
                           (first statement of a module/class/function body)
      whitelist_lines  -- 1-indexed line numbers of the two load-bearing string forms
                           this study's spec cares about: types.ModuleType(<str>) args,
                           and sys.modules[<str>] = ... assignments
    """
    try:
        with open(full_path, encoding="utf-8", errors="replace") as fh:
            src = fh.read()
    except OSError:
        return [], {}, {}, set(), set()

    lines = src.splitlines()

    comment_spans = defaultdict(list)
    string_spans = defaultdict(list)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                comment_spans[tok.start[0]].append((tok.start[1], tok.end[1]))
            elif tok.type in (tokenize.STRING, getattr(tokenize, "FSTRING_START", -1)):
                start_line, start_col = tok.start
                end_line, end_col = tok.end
                if start_line == end_line:
                    string_spans[start_line].append((start_col, end_col))
                else:
                    # multi-line string: partial cols on first/last line, full-line in between
                    string_spans[start_line].append((start_col, 10**6))
                    for ln in range(start_line + 1, end_line):
                        string_spans[ln].append((0, 10**6))
                    string_spans[end_line].append((0, end_col))
    except (tokenize.TokenizeError, IndentationError, SyntaxError, ValueError):
        pass

    docstring_lines = set()
    whitelist_lines = set()
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

        # whitelist: types.ModuleType(<string>) call arguments, and the call's own line
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fname = node.func.attr if isinstance(node.func, ast.Attribute) else (
                    node.func.id if isinstance(node.func, ast.Name) else None)
                if fname == "ModuleType":
                    for arg in node.args:
                        start, end = getattr(arg, "lineno", None), getattr(arg, "end_lineno", None)
                        if start:
                            for ln in range(start, end + 1):
                                whitelist_lines.add(ln)
                    whitelist_lines.add(node.lineno)

        # whitelist: sys.modules[<string>] = ... assignments (key + whole assignment line)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Subscript):
                        obj = target.value
                        is_sys_modules = (
                            isinstance(obj, ast.Attribute) and obj.attr == "modules"
                            and isinstance(obj.value, ast.Name) and obj.value.id == "sys"
                        )
                        if is_sys_modules:
                            end_ln = getattr(node, "end_lineno", node.lineno)
                            for ln in range(node.lineno, end_ln + 1):
                                whitelist_lines.add(ln)

    return lines, comment_spans, string_spans, docstring_lines, whitelist_lines


def _span_covers(spans, col_start, col_end):
    """True if [col_start, col_end) is fully contained in at least one span."""
    for s, e in spans:
        if s <= col_start and col_end <= e:
            return True
    return False


def stage_b_comment_docstring_string(candidates, repo_root, vocab_regex):
    """vocab_regex: a single compiled regex (the OR of all vocabulary terms) used
    to re-find the exact column span(s) the original grep match came from on each
    candidate's line. A candidate is dropped only if EVERY match span on its line
    falls entirely inside a comment/string/docstring span and none of those spans
    are whitelisted."""
    kept, dropped = [], []
    analysis_cache = {}
    for c in candidates:
        f = c["file"]
        if f not in analysis_cache:
            analysis_cache[f] = _analyze_file_for_stage_b(os.path.join(repo_root, f))
        lines, comment_spans, string_spans, docstring_lines, whitelist_lines = analysis_cache[f]

        ln = c["line"]
        if ln < 1 or ln > len(lines):
            kept.append(c)  # can't analyze, be conservative and keep
            continue

        line_text = lines[ln - 1]
        matches = list(vocab_regex.finditer(line_text))
        if not matches:
            kept.append(c)  # shouldn't happen, be conservative
            continue

        if ln in whitelist_lines:
            kept.append(c)
            continue

        line_comment_spans = comment_spans.get(ln, [])
        line_string_spans = string_spans.get(ln, [])

        any_match_is_real_code = False
        for m in matches:
            in_comment = _span_covers(line_comment_spans, m.start(), m.end())
            in_string = _span_covers(line_string_spans, m.start(), m.end())
            if not in_comment and not in_string:
                any_match_is_real_code = True
                break

        if any_match_is_real_code:
            kept.append(c)
        else:
            dropped.append(c)
    return kept, dropped


def stage_c_collapse_duplicates(candidates):
    """Group candidates within the same file whose stripped snippet text is
    byte-identical. Returns (representatives, expansion_map) where
    expansion_map[repr_key] = [all original candidate dicts in that group],
    keyed by (file, representative_line)."""
    groups = defaultdict(list)
    for c in candidates:
        key = (c["file"], c["snippet"].strip())
        groups[key].append(c)

    representatives = []
    expansion_map = {}
    for (f, snippet_stripped), members in groups.items():
        members_sorted = sorted(members, key=lambda c: c["line"])
        rep = dict(members_sorted[0])
        if len(members_sorted) > 1:
            rep["duplicate_count"] = len(members_sorted)
            rep["duplicate_lines"] = [m["line"] for m in members_sorted]
        representatives.append(rep)
        expansion_map[(f, members_sorted[0]["line"])] = members_sorted
    return representatives, expansion_map


def run_pipeline(candidates, repo_root, target_pattern, vocab_regex=None, stages=("A", "B", "C")):
    """Runs the requested stages in order A -> B -> C. Returns
    (final_candidates, expansion_map, stats) where expansion_map is {} if
    stage C wasn't run (i.e. 1:1), and stats records counts at each step.
    vocab_regex is required if "B" is in stages."""
    stats = {"start": len(candidates)}
    cur = candidates
    if "A" in stages:
        cur, dropped_a = stage_a_file_relevance(cur, repo_root, target_pattern)
        stats["after_A"] = len(cur)
        stats["dropped_by_A"] = len(dropped_a)
    if "B" in stages:
        assert vocab_regex is not None, "stage B requires vocab_regex"
        cur, dropped_b = stage_b_comment_docstring_string(cur, repo_root, vocab_regex)
        stats["after_B"] = len(cur)
        stats["dropped_by_B"] = len(dropped_b)
    expansion_map = {}
    if "C" in stages:
        cur, expansion_map = stage_c_collapse_duplicates(cur)
        stats["after_C"] = len(cur)
        stats["collapsed_by_C"] = stats.get("after_B", stats.get("after_A", stats["start"])) - len(cur)
    stats["final"] = len(cur)
    return cur, expansion_map, stats
