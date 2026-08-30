"""Fix generation. Given confirmed sites (adjudication's proposed_sites,
pre-duplicate-expansion -- same cost-saving shape adjudicate.py itself
consumes downstream of prefilter's stage C), asks the model for either a
confident fix or a decline, per DESIGN.md section 4's mechanical-rename vs.
structural-refactor boundary. Same chunked, idempotent-per-chunk-file
design as adjudicate.py -- a partial failure costs exactly the chunks that
failed, not the whole run.

A fix is block-shaped (`line`/`end_line`/`original_lines`/`proposed_lines`),
not line-shaped -- needed regardless of grouping, since a single migration
site (e.g. a multi-line constructor call) can require touching more than
one physical line, and a block replacement can change the line count
entirely. `end_line == line` with single-element lists is the ordinary
single-line case, unchanged in effect from before this schema existed.

Also takes adjudication's flag_uncertain sites (context only -- see run()'s
docstring) to compute coupling groups from adjudication's related_sites
field: sites whose own correctness depends on another site's content, per
the coupling design pass. A group containing an uncertain member is
deterministically declined in its entirety before the model ever sees it
(`_group_consistency_flag`, flag_source "group_consistency_guard") -- this
is the fix for the youtrack-mcp insufficient-fix-set failure: a confident,
independently-generated fix for one coupled site while its companion's
resolution was never confirmed.

A group with no uncertain member but at least one member the multi-line-
span guard would otherwise decline alone (the exact youtrack-mcp shape) is
instead sent to the model as ONE joint-resolution call asking for a
consistent set of block fixes across every member, or a joint decline (see
_run_joint_group) -- the coordinated-fix increment this module didn't have
before. Every jointly-resolved group's fixes are re-verified by the
deterministic, model-free `_check_group_value_flow` guard before they are
trusted: a coordinated edit that silently drops a value (removes it from
one call, never threads it into the other) is rejected and the whole group
falls back to flagged_for_human, never shipped as a fix nothing checked."""
import ast
import json
import math
import os
import re
import textwrap

from .. import validate
from . import factblock as factblock_stage

# Statement types that never contain a nested statement -- their own
# lineno/end_lineno span is exactly the literal statement's text, never
# stretched by a block body. Deliberately excludes compound statements
# (FunctionDef, If, For, With, Try, ...): their end_lineno reaches to the
# end of the block, not the header, so using them here would falsely tag
# every line inside a multi-line function/block as an unsafe fix target.
_SIMPLE_STMT_TYPES = (
    ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Expr, ast.Return,
    ast.Raise, ast.Assert, ast.Delete, ast.Import, ast.ImportFrom,
    ast.Global, ast.Nonlocal, ast.Pass, ast.Break, ast.Continue,
)


def _multiline_spans(tree):
    """Maps each physical line number that falls inside a multi-line simple
    statement (an assignment, call, etc. spanning more than one line) to
    that statement's (start_line, end_line). Lines belonging only to
    single-line statements are absent from the result."""
    spans = {}
    for node in ast.walk(tree):
        if not isinstance(node, _SIMPLE_STMT_TYPES):
            continue
        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", None)
        if start is None or end is None or end <= start:
            continue
        for line in range(start, end + 1):
            existing = spans.get(line)
            if existing is None or (end - start) < (existing[1] - existing[0]):
                spans[line] = (start, end)
    return spans


def _span_for_site(reader, span_cache, relpath, line):
    """Returns the (start, end) multi-line span containing `line` in
    `relpath`, or None if that line is not part of one -- including the
    case where the file can't be read or doesn't parse as Python, which
    fails open (no span found) rather than blocking the normal per-site
    flow; a syntax error here is the model's problem to notice from
    context, same as any other read failure in this stage."""
    if relpath not in span_cache:
        try:
            source = reader.read_text(relpath)
            tree = ast.parse(source)
        except (OSError, SyntaxError, ValueError):
            span_cache[relpath] = {}
        else:
            span_cache[relpath] = _multiline_spans(tree)
    return span_cache[relpath].get(line)


def _multiline_span_flag(site, span):
    start, end = span
    return {
        "file": site["file"],
        "line": site["line"],
        "reason": (
            f"this line is part of a multi-line statement spanning lines "
            f"{start}-{end}; fixgen evaluates and rewrites exactly one line "
            f"at a time, so the rest of that statement (lines {start}-{end}) "
            f"was not evaluated -- a fix to this line alone may leave the "
            f"statement broken."
        ),
        "flag_source": "multiline_span_guard",
        "span": [start, end],
    }


def _site_key(site):
    return (site["file"], site["line"])


def _group_by_related_sites(proposed_sites, uncertain_sites):
    """Deterministic union-find over every proposed/uncertain site's
    related_sites links -- computed once, before the model sees anything,
    per the coupling design pass: fact-citation was measured to both
    over-group (a self-contained rename shares fact numbers with the
    constructor it has nothing to do with) and under-group (the actually
    coupled sites on run-azeroth share zero fact numbers), so grouping is
    derived from adjudication's own related_sites field instead -- the
    structural record of the dependency it already states in prose (e.g.
    "depends on what was passed to the FastMCP( constructor at line 68").

    Returns (sites_by_key, group_id_by_key, group_members_by_id):
      - sites_by_key: {(file, line): {"role": "proposed"|"uncertain", "site": dict}}
        for every site in proposed_sites + uncertain_sites (uncertain wins
        on a key collision, which should not happen -- adjudication assigns
        each candidate to exactly one bucket -- but is harmless either way,
        since role only affects auto-decline eligibility below).
      - group_id_by_key: {(file, line): group_id} for keys in a
        multi-member group; singletons are absent.
      - group_members_by_id: {group_id: sorted [(file, line), ...]}.

    A related_sites entry naming a (file, line) outside this run's own
    proposed_sites/uncertain_sites (e.g. a REJECTed candidate, or a line
    that was never a candidate at all) contributes no edge -- there is
    nothing on this run's side of that link to group with, or to decline."""
    sites_by_key = {}
    for site in proposed_sites:
        sites_by_key[_site_key(site)] = {"role": "proposed", "site": site}
    for site in uncertain_sites:
        sites_by_key.setdefault(_site_key(site), {"role": "uncertain", "site": site})

    parent = {key: key for key in sites_by_key}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            if rb < ra:
                ra, rb = rb, ra
            parent[rb] = ra

    for key, entry in sites_by_key.items():
        for rel in entry["site"].get("related_sites", []):
            other = (rel["file"], rel["line"])
            if other in sites_by_key:
                union(key, other)

    components = {}
    for key in sites_by_key:
        components.setdefault(find(key), []).append(key)

    group_id_by_key = {}
    group_members_by_id = {}
    for root, members in components.items():
        if len(members) < 2:
            continue
        gid = f"{root[0]}:{root[1]}"
        group_members_by_id[gid] = sorted(members)
        for member_key in members:
            group_id_by_key[member_key] = gid

    return sites_by_key, group_id_by_key, group_members_by_id


def _group_members_rendered(member_keys, sites_by_key):
    return [
        {
            "file": f, "line": l, "role": sites_by_key[(f, l)]["role"],
            "reason": sites_by_key[(f, l)]["site"]["reason"],
        }
        for f, l in member_keys
    ]


def _group_consistency_flag(site, group_id, member_keys, sites_by_key, trigger_clauses):
    """member_keys: sorted [(file, line), ...] for every member of this
    site's group (including `site` itself), from group_members_by_id.
    sites_by_key: the same dict _group_by_related_sites returned, used to
    look up each member's role and adjudication reason for the rendered
    group_members list report.py needs -- it renders exactly what it's
    given, not a recomputation of the group."""
    own_key = _site_key(site)
    others = ", ".join(f"{f}:{l}" for f, l in member_keys if (f, l) != own_key)
    trigger_text = "; ".join(trigger_clauses)
    return {
        "file": site["file"],
        "line": site["line"],
        "reason": (
            f"this site is part of a coupled edit group with {others} -- {trigger_text}. "
            f"Fixing this site alone, without a confirmed and jointly-consistent edit "
            f"for the rest of the group, risks leaving the group broken -- the exact "
            f"failure shape a real run (tonyzorin/youtrack-mcp) already produced. This "
            f"increment does not attempt to resolve a coupled group by sending it to the "
            f"model jointly, so the whole group is declined together instead."
        ),
        "flag_source": "group_consistency_guard",
        "group_id": group_id,
        "group_members": _group_members_rendered(member_keys, sites_by_key),
    }


def _extract_call_keywords(text):
    """{keyword_name: ast.dump(value_node)} for every keyword argument in
    every ast.Call found in `text`, last occurrence wins on a duplicate
    name within the same block (rare, and not a case this guard needs to
    resolve precisely). Returns {} if `text` doesn't parse as Python at
    all -- see _check_group_value_flow's docstring for why that degrades
    silently rather than raising.

    `textwrap.dedent` first: a fix's original_lines/proposed_lines
    deliberately preserve real source indentation (e.g. a member sitting
    inside a function or an `if __name__ == "__main__":` block), which
    `ast.parse` rejects outright as an IndentationError -- a real block
    of otherwise-valid Python would silently degrade to "no keywords
    found" on every indented member without this, making the guard blind
    on exactly the shape (an indented `mcp.run(...)` call) the real
    youtrack-mcp case has."""
    try:
        tree = ast.parse(textwrap.dedent(text))
    except SyntaxError:
        return {}
    keywords = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg is not None:
                    keywords[kw.arg] = ast.dump(kw.value)
    return keywords


def _check_group_value_flow(group_fixes):
    """The deterministic safety net a jointly-resolved group's fixes must
    pass before any of them is trusted, per the design pass: a model can
    produce a coordinated edit that parses fine, passes ordinary line-match
    verification, and still silently drops a value -- moves a keyword
    argument out of one call and never threads it into the other, or
    replaces it with a plausible-looking but wrong literal (`port=port`
    quietly becoming `port=8000`). Neither tier 1 nor tier 2 verification
    (apidrift/verify.py) can see this: both check a fix's own internal
    consistency, never whether a SET of fixes jointly preserves a value
    that moved between them.

    For every fix in the group, a keyword argument present in its original
    block but ABSENT (or changed) in its own proposed block is "removed"
    there and must reappear, with an AST-EQUAL value expression (ast.dump
    comparison, not name/string matching), in some OTHER member's proposed
    block. Deliberately expression-equality, not name-presence: `port=port`
    removed at one site and `port=8000` added at another has the same
    keyword NAME present but a different value expression, so it still
    fails -- exactly the silent-substitution shape this check exists to
    catch.

    Returns None if every removed value is accounted for, or a
    human-readable string naming what's missing otherwise. Deterministic,
    no model call -- pure AST comparison over fixes already produced.

    Known limits, stated plainly rather than silently: (1) this only
    tracks KEYWORD arguments in Call nodes -- a value carried via a
    positional argument, a plain assignment, or any non-call construct is
    invisible to it. (2) a block that fails to parse on its own (should not
    happen -- these blocks come from _multiline_spans, whose whole reason
    for existing is that its spans ARE complete, independently parseable
    simple statements -- but if it ever does) degrades to an empty keyword
    set for that member, silently, rather than raising -- such a member
    neither contributes an obligation nor discharges one. (3) this proves
    an expression MOVED unchanged; it cannot prove the destination is the
    semantically right place for it, or that the code is behaviorally
    correct at runtime -- that residual gap is real and is not closed by
    this or any other static check in this pipeline."""
    orig_kw = {}
    prop_kw = {}
    for fix in group_fixes:
        key = (fix["file"], fix["line"])
        orig_kw[key] = _extract_call_keywords("\n".join(fix["original_lines"]))
        prop_kw[key] = _extract_call_keywords("\n".join(fix["proposed_lines"]))

    missing = []
    for key, kws in orig_kw.items():
        own_prop = prop_kw[key]
        for name, dump in kws.items():
            if own_prop.get(name) == dump:
                continue  # unchanged at the same site -- not a removal at all
            found_elsewhere = any(
                other_key != key and prop_kw[other_key].get(name) == dump
                for other_key in prop_kw
            )
            if not found_elsewhere:
                missing.append(f"{key[0]}:{key[1]} keyword {name!r}")

    if missing:
        return ("value(s) removed with no matching reappearance elsewhere in the group: "
                + ", ".join(missing))
    return None


def _sanitize_gid(gid):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", gid)


def _group_call_path(fg_dir, gid):
    return os.path.join(fg_dir, f"group_{_sanitize_gid(gid)}.json")


def _group_call_is_done(path, member_keys):
    if not os.path.isfile(path):
        return False
    try:
        data = validate.validate_fixgen_file(path)
    except ValueError:
        return False
    covered = {(it["file"], it["line"]) for b in ("fixes", "flagged_for_human") for it in data[b]}
    return covered == set(member_keys)


def _run_joint_group(client, reader, gid, member_keys, sites_by_key, span_map,
                      base_system_text, fg_dir, cache_system, cache_ttl):
    """One idempotent, resumable call resolving every member of a
    joint_resolve group (see run()'s classification pass) together: either
    a consistent set of (possibly multi-line) block fixes for every member,
    or a joint decline for the whole group. The model's own bucket choice
    is necessary but never sufficient here -- every fixes-bucket result is
    re-verified by _check_group_value_flow below before it is trusted.

    Returns (fixes, flags): fixes is a list of fix dicts with this
    function's own group_id stamped on (never taken from the model);
    flags is a list of flagged_for_human dicts, each carrying group_id/
    group_members so report.py can render the group -- either the model's
    own joint decline, or this function's value_flow_guard override when
    the model's fixes didn't pass the deterministic check. Exactly one of
    the two returned lists is non-empty."""
    path = _group_call_path(fg_dir, gid)
    member_set = set(member_keys)

    if not _group_call_is_done(path, member_keys):
        blocks = []
        for f, l in member_keys:
            site = sites_by_key[(f, l)]["site"]
            start, end = span_map.get((f, l), (l, l))
            blocks.append(
                f"### {f}:{l}\n"
                f"Confirmed reason: {site['reason']}\n"
                f"Fact(s): {site.get('pattern', '?')}\n"
                f"Statement span: lines {start}-{end}\n"
                f"Context (every line of this member's own statement marked with >>):\n"
                f"```\n{_context_block_for_span(reader, f, start, end)}\n```"
            )
        user_text = (
            f"COORDINATED GROUP {gid} -- {len(member_keys)} member site(s) that must be "
            f"resolved TOGETHER (see this call's coordinated-group instructions above):\n\n"
            + "\n\n".join(blocks)
        )
        result = client.complete(
            stage=f"fixgen_group_{_sanitize_gid(gid)}",
            system_text=base_system_text + "\n\n---\n\n" + _JOINT_ADDENDUM,
            user_text=user_text,
            schema=SCHEMA,
            cache_system=cache_system,
            cache_ttl=cache_ttl,
            max_tokens=8000,
            effort="high",
        )
        validate.validate_fixgen_dict(result, what=f"group_{gid}")
        tmp = path + ".tmp"
        with open(tmp, "w") as fp:
            json.dump(result, fp, indent=2)
        os.replace(tmp, path)

    result = validate.validate_fixgen_file(path)
    covered = {(it["file"], it["line"]) for b in ("fixes", "flagged_for_human") for it in result[b]}
    if covered != member_set:
        raise ValueError(
            f"joint resolution for group {gid} does not cover exactly its members -- "
            f"missing {sorted(member_set - covered)}, unexpected {sorted(covered - member_set)}"
        )
    bucketed = {(it["file"], it["line"]): b
                for b in ("fixes", "flagged_for_human") for it in result[b]}
    _check_group_consistency(bucketed, {gid: list(member_keys)}, what=path)

    members_rendered = _group_members_rendered(member_keys, sites_by_key)

    if result["fixes"]:
        fixes = [dict(item, group_id=gid) for item in result["fixes"]]
        failure = _check_group_value_flow(fixes)
        if failure is not None:
            flags = [{
                "file": f, "line": l,
                "reason": (
                    f"this site's confident-looking joint fix for coordinated group {gid} "
                    f"was rejected by the deterministic value-flow guard: {failure}. A "
                    f"model-proposed coordinated edit is never trusted without this check. "
                    f"Falling back to flagged_for_human for every member of this group "
                    f"rather than shipping an edit that may have silently dropped a value."
                ),
                "flag_source": "value_flow_guard",
                "group_id": gid,
                "group_members": members_rendered,
            } for f, l in member_keys]
            return [], flags
        return fixes, []

    # The model's flagged_for_human items only ever carry file/line/reason
    # (SCHEMA's flagged_for_human items have no flag_source property) --
    # "joint_resolution_declined" is always this function's own label, never
    # read from the model.
    flags = [
        {**item, "flag_source": "joint_resolution_declined",
         "group_id": gid, "group_members": members_rendered}
        for item in result["flagged_for_human"]
    ]
    return [], flags


_PROMPT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")
with open(os.path.join(_PROMPT_DIR, "fixgen_system.md")) as _f:
    _TEMPLATE = _f.read()
with open(os.path.join(_PROMPT_DIR, "fixgen_joint_addendum.md")) as _f:
    _JOINT_ADDENDUM = _f.read()

# `group_id` is deliberately absent from this schema -- see
# _validate_fix_block_fields's docstring in validate.py: it is stamped by
# this module onto a jointly-resolved group's own fixes, never asked of or
# trusted from the model, for either the ordinary per-chunk calls or the
# joint-resolution calls below (both use this same schema).
SCHEMA = {
    "type": "object",
    "properties": {
        "fixes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                    "original_lines": {"type": "array", "items": {"type": "string"}},
                    "proposed_lines": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                },
                "required": ["file", "line", "end_line", "original_lines",
                             "proposed_lines", "reason"],
                "additionalProperties": False,
            },
        },
        "flagged_for_human": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "line": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["file", "line", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["fixes", "flagged_for_human"],
    "additionalProperties": False,
}

DEFAULT_CHUNK_SIZE = 15
DEFAULT_CONTEXT_RADIUS = 8


def _chunks(sites, chunk_size):
    n = max(1, math.ceil(len(sites) / chunk_size))
    out = []
    for i in range(n):
        part = sites[i * chunk_size:(i + 1) * chunk_size]
        if part:
            out.append((i, part))
    return out


def _context_block(reader, relpath, line, radius=DEFAULT_CONTEXT_RADIUS):
    """Numbered source lines around `line`, target marked with `>>`. Read
    failures degrade to a note rather than raising -- a site whose file
    became unreadable between adjudication and fix-gen should not crash the
    whole chunk; it just won't get useful context and the model can flag it."""
    try:
        text = reader.read_text(relpath)
    except OSError as e:
        return f"(could not read {relpath}: {e})"
    lines = text.splitlines()
    lo = max(1, line - radius)
    hi = min(len(lines), line + radius)
    out = []
    for i in range(lo, hi + 1):
        marker = ">>" if i == line else "  "
        out.append(f"{marker} {i:5d}| {lines[i - 1]}")
    return "\n".join(out)


def _context_block_for_span(reader, relpath, start, end, radius=DEFAULT_CONTEXT_RADIUS):
    """Same numbered-source-with-markers shape as _context_block, but marks
    every physical line in [start, end] with `>>`, not just one -- used for
    a joint-resolution group member so a multi-line statement is never
    shown with only its opening line marked (the exact partial-visibility
    gap the multi-line-span guard exists to avoid in the first place).
    start == end reproduces _context_block's own single-line behavior
    exactly."""
    try:
        text = reader.read_text(relpath)
    except OSError as e:
        return f"(could not read {relpath}: {e})"
    lines = text.splitlines()
    lo = max(1, start - radius)
    hi = min(len(lines), end + radius)
    out = []
    for i in range(lo, hi + 1):
        marker = ">>" if start <= i <= end else "  "
        out.append(f"{marker} {i:5d}| {lines[i - 1]}")
    return "\n".join(out)


def _site_block(reader, site):
    return (
        f"### {site['file']}:{site['line']}\n"
        f"Confirmed reason: {site['reason']}\n"
        f"Fact(s): {site.get('pattern', '?')}\n"
        f"Context (target line marked with >>):\n"
        f"```\n{_context_block(reader, site['file'], site['line'])}\n```"
    )


def _chunk_path(dir_, idx):
    return os.path.join(dir_, f"chunk_{idx:03d}.json")


def _chunk_is_done(dir_, idx, chunk_sites):
    path = _chunk_path(dir_, idx)
    if not os.path.isfile(path):
        return False
    try:
        data = validate.validate_fixgen_file(path)
    except ValueError:
        return False
    covered = set()
    for bucket in ("fixes", "flagged_for_human"):
        for item in data[bucket]:
            covered.add((item["file"], item["line"]))
    expected = {(s["file"], s["line"]) for s in chunk_sites}
    return covered == expected


def _check_group_consistency(bucketed, group_members_by_id, what):
    """bucketed: {(file, line): bucket_name} for every site whose verdict
    is known so far -- a chunk's own result (partial: only that chunk's
    sites) or the full merged result (complete: every site). Raises
    ValueError, same discipline as the coverage check this sits beside,
    the moment a group's known members disagree on which bucket they
    landed in. A group with a member not yet present in `bucketed` (still
    in an unprocessed chunk, at the per-chunk call site) is not checkable
    yet and is silently skipped here -- the merged-level call, which sees
    every site, is what actually guarantees no group escapes torn."""
    for gid, members in group_members_by_id.items():
        seen = {bucketed[m] for m in members if m in bucketed}
        if len(seen) > 1:
            detail = ", ".join(
                f"{f}:{l}={bucketed[(f, l)]}" for f, l in members if (f, l) in bucketed
            )
            raise ValueError(
                f"{what}: group {gid} was split across buckets -- {detail} -- a coupled "
                f"edit group must be entirely in 'fixes' or entirely in "
                f"'flagged_for_human', never both (this is exactly the youtrack-mcp "
                f"insufficient-fix-set failure: a confident fix for one member without "
                f"a consistent resolution for the rest)"
            )


def run(client, reader, sites, factblock, workdir, uncertain_sites=(),
        chunk_size=DEFAULT_CHUNK_SIZE, cache_ttl="5m"):
    """Returns the merged two-bucket dict. Writes workdir/fixgen/chunk_NNN.json
    (one per chunk) and workdir/fixgen/merged.json. `sites` should be
    adjudication's proposed_sites list -- one entry per distinct
    (file, line), pre-duplicate-expansion; callers expand the result with
    expand_duplicates(), the same shape adjudicate.py's own expansion takes.

    `uncertain_sites` should be adjudication's flag_uncertain list, same
    pre-expansion shape. It is consumed for exactly one purpose: computing
    which proposed sites are coupled to an uncertain one via related_sites
    (see _group_by_related_sites), so that coupling can be deterministically
    declined below. An uncertain site never itself becomes a fix or a
    flagged_for_human entry -- a group containing one has no jointly-
    consistent set this pipeline can produce (its own resolution was never
    confirmed by adjudication in the first place), so it is always declined
    in its entirety, never sent to the model even jointly. Omitting
    `uncertain_sites` (the default) means no site in `sites` is ever grouped
    with anything uncertain, which is exactly today's behavior.

    `cache_ttl`: see adjudicate.run()'s docstring -- same reasoning for
    the cache_system gate below."""
    fg_dir = os.path.join(workdir, "fixgen")
    os.makedirs(fg_dir, exist_ok=True)

    facts_text = factblock_stage.render_facts_text(factblock)
    system_text = _TEMPLATE.replace("{MIGRATION_FACTS}", facts_text)

    sites_by_key, group_id_by_key, group_members_by_id = _group_by_related_sites(
        sites, uncertain_sites,
    )

    # Every site's enclosing-statement span, computed once, up front,
    # independent of any decline/joint-resolution decision below -- the
    # same _span_for_site the old single-pass span guard used, just no
    # longer coupled to an immediate "flag it now" verdict for a site that
    # turns out to belong to a group this run CAN jointly resolve.
    span_cache = {}
    span_map = {}  # (file, line) -> (start, end)
    for site in sites:
        span = _span_for_site(reader, span_cache, site["file"], site["line"])
        if span is not None:
            span_map[_site_key(site)] = span

    # Classify every multi-member group once:
    #  - "uncertain_decline": contains a not-confirmed member -- no
    #    jointly-consistent set is possible this run, exactly as before.
    #  - "joint_resolve": every member is confirmed, but at least one needs
    #    block-level treatment a lone per-line call can't safely give --
    #    the youtrack-mcp shape this increment adds real handling for.
    #  - unclassified: ordinary confident members with nothing forcing
    #    coordinated handling -- already handled correctly by reaching the
    #    model independently (same chunk, no group framing), per the
    #    original coupling increment's own measured scope.
    group_class = {}
    for gid, member_keys in group_members_by_id.items():
        has_uncertain = any(sites_by_key[k]["role"] == "uncertain" for k in member_keys)
        if has_uncertain:
            group_class[gid] = "uncertain_decline"
        elif any(k in span_map for k in member_keys):
            group_class[gid] = "joint_resolve"

    auto_flagged = []

    # Pass 1 -- immediate multi-line-span flags. Fires for every span-having
    # site EXCEPT one whose group is classified "joint_resolve": that
    # site's fate is decided jointly with the rest of its group in pass 3
    # below, with full visibility into every member, instead of alone here.
    # An ungrouped span site, or one in an "uncertain_decline" group, is
    # flagged immediately exactly as before this increment.
    for key, (start, end) in span_map.items():
        gid = group_id_by_key.get(key)
        if gid is not None and group_class.get(gid) == "joint_resolve":
            continue
        site = sites_by_key[key]["site"]
        flag = _multiline_span_flag(site, (start, end))
        if gid is not None:
            flag["group_id"] = gid
            flag["group_members"] = _group_members_rendered(group_members_by_id[gid], sites_by_key)
        auto_flagged.append(flag)

    span_declined = {
        key for key in span_map
        if not (group_id_by_key.get(key) and group_class.get(group_id_by_key[key]) == "joint_resolve")
    }

    # Pass 2 -- group-consistency guard for "uncertain_decline" groups only,
    # unchanged in behavior from before this increment: every not-yet-
    # declined proposed member is declined too, deterministically, before
    # it ever reaches the model. This is the fix for the coupling failure
    # itself: without it, an otherwise-confident member of a group like
    # this would go on to get an independently-generated, independently-
    # plausible fix, unaware its companion's resolution was never
    # confirmed -- the "fix the confident member alone" shape the
    # youtrack-mcp run produced.
    group_declined = set()
    for gid, member_keys in group_members_by_id.items():
        if group_class.get(gid) != "uncertain_decline":
            continue
        trigger_clauses = []
        for f, l in member_keys:
            if sites_by_key[(f, l)]["role"] == "uncertain":
                reason = sites_by_key[(f, l)]["site"]["reason"]
                trigger_clauses.append(
                    f"{f}:{l} was not confirmed by adjudication ({reason!r})"
                )
        for f, l in member_keys:
            if (f, l) in span_declined:
                start, end = span_map[(f, l)]
                trigger_clauses.append(
                    f"{f}:{l} was not evaluated (multi-line statement spanning "
                    f"lines {start}-{end})"
                )
        for f, l in member_keys:
            key = (f, l)
            if sites_by_key[key]["role"] != "proposed" or key in span_declined:
                continue
            auto_flagged.append(_group_consistency_flag(
                sites_by_key[key]["site"], gid, member_keys, sites_by_key, trigger_clauses,
            ))
            group_declined.add(key)

    # Pass 3 -- joint resolution: one call per "joint_resolve" group, asking
    # the model to resolve every member together instead of declining the
    # group outright (see _run_joint_group). Every fixes-bucket result is
    # re-verified by the deterministic _check_group_value_flow guard before
    # being trusted -- a rejected coordinated fix falls back to
    # flagged_for_human for the whole group, same outcome pass 2 would have
    # produced, just reached with a real attempt in between instead of an
    # automatic decline.
    joint_fixes = []
    joint_gids = sorted(gid for gid, c in group_class.items() if c == "joint_resolve")
    cache_joint = len(joint_gids) > 1 or cache_ttl != "5m"
    joint_resolved_keys = set()
    for gid in joint_gids:
        member_keys = group_members_by_id[gid]
        result_fixes, result_flags = _run_joint_group(
            client, reader, gid, member_keys, sites_by_key, span_map,
            system_text, fg_dir, cache_joint, cache_ttl,
        )
        joint_fixes.extend(result_fixes)
        auto_flagged.extend(result_flags)
        joint_resolved_keys.update(member_keys)

    eval_sites = [
        s for s in sites
        if _site_key(s) not in span_declined
        and _site_key(s) not in group_declined
        and _site_key(s) not in joint_resolved_keys
    ]

    chunks = _chunks(eval_sites, chunk_size)
    # See adjudicate.run(): a single chunk can't redeem its own cache
    # write within this run, so only cache it unconditionally when there
    # are multiple chunks to read it back, or when the caller explicitly
    # asked for a non-default TTL (signaling cross-run reuse is intended).
    cache_system = len(chunks) > 1 or cache_ttl != "5m"
    for idx, chunk_sites in chunks:
        if _chunk_is_done(fg_dir, idx, chunk_sites):
            continue
        blocks = "\n\n".join(_site_block(reader, s) for s in chunk_sites)
        user_text = f"CONFIRMED SITES ({len(chunk_sites)}):\n\n{blocks}"
        result = client.complete(
            stage=f"fixgen_chunk_{idx:03d}",
            system_text=system_text,
            user_text=user_text,
            schema=SCHEMA,
            cache_system=cache_system,
            cache_ttl=cache_ttl,
            max_tokens=8000,
            effort="high",
        )
        validate.validate_fixgen_dict(result, what=f"chunk_{idx:03d}")
        covered = set()
        bucketed = {}
        for bucket in ("fixes", "flagged_for_human"):
            for item in result[bucket]:
                key = (item["file"], item["line"])
                covered.add(key)
                bucketed[key] = bucket
        expected = {(s["file"], s["line"]) for s in chunk_sites}
        if covered != expected:
            missing = expected - covered
            extra = covered - expected
            raise ValueError(
                f"chunk_{idx:03d}: fix generation does not cover exactly the sites "
                f"given -- missing {sorted(missing)}, unexpected {sorted(extra)}"
            )
        # Catches only a group fully contained in this one chunk -- a group
        # split across chunk boundaries isn't checkable until every chunk
        # is in, so it's re-checked at the merged level below regardless.
        _check_group_consistency(bucketed, group_members_by_id, what=f"chunk_{idx:03d}")

        path = _chunk_path(fg_dir, idx)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(result, f, indent=2)
        os.replace(tmp, path)

    merged = {"fixes": list(joint_fixes), "flagged_for_human": list(auto_flagged)}
    for idx, _ in chunks:
        data = validate.validate_fixgen_file(_chunk_path(fg_dir, idx))
        for bucket in merged:
            merged[bucket].extend(data[bucket])

    merged_path = os.path.join(fg_dir, "merged.json")

    # The complete, run-wide check: every group's members are now known
    # (auto-declined ones from pass 2, model-generated ones from every
    # chunk), so a group split across chunk boundaries -- not checkable
    # above -- is caught here. Note this one is not cleanly resumable: if
    # it fires, the individual chunks it spans each independently passed
    # their own (necessarily partial) coverage and group checks and are
    # already written to disk as "done", so re-running without deleting
    # those chunk files first will reach the exact same split again. A
    # real occurrence needs group-aware chunking to fix properly, which is
    # out of scope for this increment -- see the design pass's own §5.
    merged_bucketed = {}
    for bucket in ("fixes", "flagged_for_human"):
        for item in merged[bucket]:
            merged_bucketed[(item["file"], item["line"])] = bucket
    _check_group_consistency(merged_bucketed, group_members_by_id, what=merged_path)

    with open(merged_path, "w") as f:
        json.dump(merged, f, indent=2)
    validate.validate_fixgen_dict(merged, what=merged_path)
    return merged


def expand_duplicates(merged, expansion_map):
    """Same job as adjudicate.expand_duplicates, over the fixgen two-bucket
    shape: fans a representative site's single fix/flag back out to every
    original (file, line) prefilter stage C collapsed. A duplicate line's
    `proposed_lines` is the representative's verbatim replacement text --
    valid because stage C only ever collapses byte-identical source lines,
    so the same replacement applies to every one of them.

    For the ordinary, overwhelmingly common case -- a single-line fix
    (`len(original_lines) == 1`) -- `original_lines[0]` becomes each
    duplicate member's own snippet, not the representative's, so a per-item
    line-match check downstream still compares against real source text,
    and `line`/`end_line` both become the duplicate's own line. A
    multi-line (block) representative fix is never produced by stage C
    dedup in practice -- stage C collapses individual candidate lines
    before fixgen ever computes a span, and a jointly-resolved group's
    members are specific confirmed sites, not dedup representatives -- so
    that case is left with the representative's own original_lines
    unchanged beyond shifting line/end_line by the duplicate's offset,
    rather than inventing per-line snippets this function has no source
    for."""
    expanded = {"fixes": [], "flagged_for_human": []}
    for item in merged["fixes"]:
        key = (item["file"], item["line"])
        members = expansion_map.get(key)
        if not members:
            expanded["fixes"].append(item)
            continue
        span_len = item["end_line"] - item["line"]
        for m in members:
            entry = dict(item)
            entry["line"] = m["line"]
            entry["end_line"] = m["line"] + span_len
            if len(item["original_lines"]) == 1:
                entry["original_lines"] = [m["snippet"]]
            expanded["fixes"].append(entry)
    for item in merged["flagged_for_human"]:
        key = (item["file"], item["line"])
        members = expansion_map.get(key)
        if not members:
            expanded["flagged_for_human"].append(item)
            continue
        for m in members:
            entry = dict(item)
            entry["line"] = m["line"]
            expanded["flagged_for_human"].append(entry)
    return expanded
