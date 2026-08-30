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


def _direct_dependencies(sites_by_key):
    """{(file, line): [(file, line), ...]} -- exactly each site's own
    related_sites entries, restricted to keys present in sites_by_key (an
    edge to a site outside this run has nothing on this run's side to
    depend on, same restriction _group_by_related_sites already applies).

    This is the DIRECTED "depends on" relation adjudication's related_sites
    field actually states: an entry lists what THAT site needs in order to
    be correct, never what needs that site. `_group_by_related_sites`
    still unions both ends of every edge into one undirected component --
    that's still the right computation for "which sites might need to be
    shown together" (joint-resolution eligibility, report.py's coupled-
    group rendering) -- but it is the WRONG computation for "which sites
    are safe to fix," which is what this directed view is for. See
    run()'s docstring for the real-run regression (run-youtrack-joint)
    that conflating the two caused."""
    deps = {}
    for key, entry in sites_by_key.items():
        deps[key] = [
            (rel["file"], rel["line"]) for rel in entry["site"].get("related_sites", [])
            if (rel["file"], rel["line"]) in sites_by_key
        ]
    return deps


def _compute_unsafe_sites(all_keys, depends_on, self_unsafe):
    """Fixed-point closure over the DIRECTED depends_on graph.

    `self_unsafe`: the set of keys unsafe for their OWN reason -- an
    uncertain-role site (never confirmed by adjudication), or a site with
    an unresolved multi-line span (never fixed, whether because it was
    never eligible for joint resolution or because a joint-resolution
    attempt for it did not produce a fix).

    Blocking flows in exactly one direction: from a dependency to its
    dependents, never the reverse. A site becomes unsafe if it depends --
    directly, or transitively through a chain of other now-unsafe sites --
    on something unsafe. A site is NEVER made unsafe merely because
    something else depends on IT; only its OWN dependencies (named in its
    OWN related_sites) can do that. This is the fix for run-youtrack-
    joint: main.py:25 (`-> FastMCP:`) depends only on main.py:10 (the
    import) and is otherwise self-contained; main.py:70 depending on
    main.py:25 does not, and must not, make main.py:25 unsafe.

    Returns {key: cause_key} for every unsafe key -- cause_key == key for
    a site unsafe for its own reason, or the specific dependency whose own
    unsafe status made this site unsafe (one hop, chosen deterministically
    as the first such dependency found; sufficient to name in a human-
    facing reason, since that dependency's own cause is independently
    resolvable from this same map by looking IT up in turn)."""
    cause = {k: k for k in self_unsafe}
    changed = True
    while changed:
        changed = False
        for key in all_keys:
            if key in cause:
                continue
            for dep in depends_on.get(key, ()):
                if dep in cause:
                    cause[key] = dep
                    changed = True
                    break
    return cause


def _describe_unsafe_cause(key, unsafe_cause, sites_by_key, span_map):
    """One clause explaining why `key` is unsafe, for a human-facing
    decline reason -- `key` must be a key of `unsafe_cause`. Recurses one
    logical hop at a time along the SAME chain _compute_unsafe_sites
    already resolved (never re-derives it), so the text names the real,
    concrete, base-case reason (uncertain / span / joint-resolution
    outcome) rather than stopping at a vague "it was declined" for a
    multi-hop chain."""
    cause = unsafe_cause[key]
    if cause == key:
        if sites_by_key[key]["role"] == "uncertain":
            return f"{key[0]}:{key[1]} was not confirmed by adjudication"
        if key in span_map:
            start, end = span_map[key]
            return (f"{key[0]}:{key[1]} was not evaluated (multi-line statement "
                     f"spanning lines {start}-{end})")
        return f"{key[0]}:{key[1]} was not resolved by a coordinated fix"
    dep_reason = _describe_unsafe_cause(cause, unsafe_cause, sites_by_key, span_map)
    return f"{key[0]}:{key[1]} depends on {cause[0]}:{cause[1]} ({dep_reason})"


def _check_no_fix_depends_on_an_unresolved_site(merged_bucketed, depends_on, what):
    """The real invariant this pipeline must never violate, replacing the
    old undirected "every group member must land in the same bucket"
    check for this run-wide sweep (see run()'s docstring for why that
    check over-declined on run-youtrack-joint): a site that shipped as a
    FIX must never depend on something that did not ALSO ship as a fix.
    A fix depending on another fix is fine regardless of grouping; a fix
    depending on a decline, an uncertain site, or anything not in
    `merged_bucketed` at all, is the exact insufficient-fix-set shape the
    original coupling increment exists to catch -- checked precisely by
    dependency now, instead of by blanket group membership."""
    for key, bucket in merged_bucketed.items():
        if bucket != "fixes":
            continue
        for dep in depends_on.get(key, ()):
            dep_bucket = merged_bucketed.get(dep, "not resolved by this run")
            if dep_bucket != "fixes":
                raise ValueError(
                    f"{what}: {key[0]}:{key[1]} shipped as a fix but its own dependency "
                    f"{dep[0]}:{dep[1]} did not (bucket: {dep_bucket}) -- a coupled pair "
                    f"split across buckets this way is never safe to ship: a fix must "
                    f"never depend on something that was not also fixed"
                )


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
    """Used only within ONE joint-resolution call's own response (see
    _run_joint_group) -- not, since the directional-dependency fix for
    run-youtrack-joint, as a run-wide sweep over every undirected group.
    A single call was explicitly asked to resolve its own member set
    jointly; if it tears that exact set across buckets (some fixed, some
    flagged), that is always a defect in that one response, regardless of
    dependency direction, because every member of THIS set was presented
    to the model as one coordinated unit. The broader, run-wide question
    -- may a site that reached 'fixes' through some OTHER path depend on
    a site that did not -- is answered by
    _check_no_fix_depends_on_an_unresolved_site instead, directionally.

    bucketed: {(file, line): bucket_name} for every site whose verdict is
    known. Raises ValueError the moment a group's known members disagree
    on which bucket they landed in."""
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
    which proposed sites depend on an uncertain one via related_sites (see
    _group_by_related_sites and _direct_dependencies), so that coupling can
    be deterministically declined below. An uncertain site never itself
    becomes a fix or a flagged_for_human entry -- its own resolution was
    never confirmed by adjudication in the first place. Omitting
    `uncertain_sites` (the default) means no site in `sites` ever depends
    on anything uncertain, which is exactly today's behavior.

    Blocking is DIRECTIONAL, not blanket-per-group: a site is declined if
    something IT depends on (per its own related_sites) is unresolved or
    declined, transitively; a site is never declined merely because
    something else depends on IT. This is a fix for a real regression
    (run-youtrack-joint): adjudication produced main.py:10 (an import
    rename, no dependencies), main.py:25 (a return-annotation rename
    depending only on 10), main.py:27 (a multi-line constructor call also
    depending on 10), and an UNCERTAIN main.py:70 depending on both 27 and
    25. Treating related_sites as an undirected edge -- the original
    design -- put all four in one connected component and declined every
    member because the component contained an uncertain site, even though
    nothing about 10 or 25's OWN correctness depends on 70 ever being
    resolved. 10 and 25 are self-contained and safe regardless of 70's
    status; only 27 (multi-line, its own separate reason) and 70 (uncertain
    itself) decline.

    One subtlety this directional rule does NOT paper over: does shipping
    10 and 25 as fixes while 27 stays on the old symbol leave the file
    broken? If a human applies fixes.json's `fixes` list via `api-drift
    apply` without ALSO addressing 27's flagged_for_human entry, yes --
    27 still references the renamed symbol under its old name, and that
    reference breaks the moment the code path through it runs, regardless
    of whether 10 was ever touched. This is not a NEW risk 10/25 being
    fixed introduces, though: 27 already, unconditionally, needs a human
    (the multi-line-span guard declines it regardless of this rule, both
    before and after this fix), and this tool has never guaranteed that
    applying its `fixes` bucket alone yields a fully migrated repo when
    flagged_for_human entries remain elsewhere -- report.md's own header
    already says to review everything before applying, and 27's own
    flagged entry still cross-references 10 and 25 in its group_members
    roster (group_members_by_id, the undirected view, is still computed
    and still used for that visibility -- only the BLOCKING decision
    became directional, not the reporting). The real, narrower danger the
    original coupling design exists to prevent -- a fix that looks
    confident and complete but silently omits a value another site was
    supposed to supply it -- is unaffected: 10 and 25 are each genuinely
    self-contained mechanical renames, not fixes assuming missing context.

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

    # Pass 2 -- joint resolution: one call per "joint_resolve" group, asking
    # the model to resolve every member together instead of declining the
    # group outright (see _run_joint_group). Every fixes-bucket result is
    # re-verified by the deterministic _check_group_value_flow guard before
    # being trusted -- a rejected coordinated fix falls back to
    # flagged_for_human for the whole group. Run BEFORE the directional
    # closure below: whether a joint-resolve member ends up safe depends on
    # whether this call actually produced a fix for it, not merely on
    # whether it was eligible to try.
    joint_fixes = []
    joint_gids = sorted(gid for gid, c in group_class.items() if c == "joint_resolve")
    cache_joint = len(joint_gids) > 1 or cache_ttl != "5m"
    joint_resolved_keys = set()  # every member of a joint_resolve group, fixed or not
    joint_fixed_keys = set()     # the subset that actually received a fix
    for gid in joint_gids:
        member_keys = group_members_by_id[gid]
        result_fixes, result_flags = _run_joint_group(
            client, reader, gid, member_keys, sites_by_key, span_map,
            system_text, fg_dir, cache_joint, cache_ttl,
        )
        joint_fixes.extend(result_fixes)
        auto_flagged.extend(result_flags)
        joint_resolved_keys.update(member_keys)
        joint_fixed_keys.update((f["file"], f["line"]) for f in result_fixes)

    # Pass 3 -- directional dependency closure (see run()'s docstring for
    # the regression this replaces the old undirected group decline with).
    # Base "unsafe for its own reason" cases: every uncertain-role site,
    # and every site with an unresolved span -- whether it was never
    # eligible for joint resolution (already in span_declined) or WAS
    # eligible but that attempt did not produce a fix for it (a joint call
    # can decline non-span members too; both kinds belong here equally).
    self_unsafe = {key for key, entry in sites_by_key.items() if entry["role"] == "uncertain"}
    self_unsafe |= span_declined
    self_unsafe |= (joint_resolved_keys - joint_fixed_keys)

    depends_on = _direct_dependencies(sites_by_key)
    unsafe_cause = _compute_unsafe_sites(sites_by_key.keys(), depends_on, self_unsafe)

    # Every "proposed" site not already resolved one way or another above,
    # but unsafe per the closure, is declined here -- necessarily via a
    # TRANSITIVE cause (every base case is already excluded by the
    # span_declined/joint_resolved_keys checks), so this is exactly the
    # "depends on something unresolved" case, never "something depends on
    # me." group_id/group_members still come from the undirected view --
    # visibility into the whole coupled neighborhood is preserved even
    # though the block decision no longer is.
    group_declined = set()
    for key, entry in sites_by_key.items():
        if entry["role"] != "proposed":
            continue
        if key in span_declined or key in joint_resolved_keys:
            continue
        if key not in unsafe_cause:
            continue
        gid = group_id_by_key.get(key)
        cause_clause = _describe_unsafe_cause(key, unsafe_cause, sites_by_key, span_map)
        auto_flagged.append(_group_consistency_flag(
            entry["site"], gid, group_members_by_id.get(gid, [key]), sites_by_key,
            [cause_clause],
        ))
        group_declined.add(key)

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
        covered = {
            (item["file"], item["line"])
            for bucket in ("fixes", "flagged_for_human") for item in result[bucket]
        }
        expected = {(s["file"], s["line"]) for s in chunk_sites}
        if covered != expected:
            missing = expected - covered
            extra = covered - expected
            raise ValueError(
                f"chunk_{idx:03d}: fix generation does not cover exactly the sites "
                f"given -- missing {sorted(missing)}, unexpected {sorted(extra)}"
            )
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

    # The complete, run-wide check, directional (see
    # _check_no_fix_depends_on_an_unresolved_site and run()'s docstring):
    # every site's final bucket is now known (auto-declined/joint-resolved
    # above, model-generated from every ordinary chunk), so a fix that
    # depends on something NOT also fixed -- whether that split happened
    # across chunk boundaries or within one chunk's own model call -- is
    # caught here. Note this is not cleanly resumable: if it fires, the
    # individual chunks it spans each independently passed their own
    # coverage check and are already written to disk as "done", so
    # re-running without deleting those chunk files first reaches the
    # exact same split again.
    merged_bucketed = {}
    for bucket in ("fixes", "flagged_for_human"):
        for item in merged[bucket]:
            merged_bucketed[(item["file"], item["line"])] = bucket
    _check_no_fix_depends_on_an_unresolved_site(merged_bucketed, depends_on, what=merged_path)

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
