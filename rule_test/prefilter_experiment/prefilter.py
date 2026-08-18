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

  A. file_relevance -- drop a file's candidates only if an intentionally
     BROAD module-qualified reference pattern finds nothing anywhere in
     the file. This is the one stage that cannot reach true certainty:
     a file could reference the target package through a form no static
     regex enumerates (e.g. building a module name via string
     concatenation at runtime, or an import gated behind a condition
     never seen in source). That residual risk is real and is not
     "fixed" here -- it is reduced (the pattern is broadened well past
     the original narrow one to cover aliased imports, importlib,
     __import__, and any string literal containing the package's
     dotted-path prefix, not just sys.modules keys) and made fully
     auditable via the drop log, so a missed file is discoverable, not
     silently gone. See AUDIT NOTE below.

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
package" is structurally an absence-based claim no matter how the
pattern is written, because Python allows references the pattern doesn't
enumerate. It remains in the pipeline because, broadened and logged, its
false-negative rate is low enough to be worth the reduction it buys, and
because every drop it makes is recorded with the exact pattern-miss
reason -- but it is the one stage where "kept because uncertain" does
not fully apply, and that should not be papered over.
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


def stage_a_file_relevance(candidates, repo_root, target_pattern):
    """Keep a candidate unless its file has ZERO matches anywhere for the
    (broad) target_pattern. See module docstring's AUDIT NOTE: this is the
    one stage that cannot reach true certainty, only a low false-negative
    rate plus full audit logging of what it drops and why."""
    pattern = target_pattern
    file_cache = {}
    kept, dropped, log = [], [], []
    for c in candidates:
        f = c["file"]
        if f not in file_cache:
            full_path = os.path.join(repo_root, f)
            try:
                with open(full_path, encoding="utf-8", errors="replace") as fh:
                    file_cache[f] = bool(pattern.search(fh.read()))
            except OSError:
                file_cache[f] = True  # can't read it -> can't be certain -> keep
        if file_cache[f]:
            kept.append(c)
        else:
            dropped.append(c)
            log.append({
                "stage": "A", "rule": "file_relevance_no_match",
                "file": c["file"], "line": c["line"], "snippet": c.get("snippet", ""),
                "matched_span": None,
                "reason": "no occurrence of the broadened package-relevance pattern "
                          "found anywhere in this file",
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
