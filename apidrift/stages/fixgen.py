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
one call, never threads it into the other) OR silently invents one (adds
a keyword to one call with no matching value removed from any other
member -- e.g. a hallucinated `host="0.0.0.0"` on `run()` the constructor
never carried) is rejected and the whole group falls back to
flagged_for_human, never shipped as a fix nothing checked. The guard
cannot distinguish an invented value from a legitimately new one (a
migration-required parameter with no prior equivalent anywhere in the
group); it flags both the same way, on purpose -- see the function's own
docstring.

related_sites is specified as one-way (a site names what IT needs, never
who needs it), but a prompt can be misread and an adjudication response
can name a related site backwards -- a real run (run-azeroth-joint,
main.py:68) has the constructor list its own downstream call sites as
dependencies, when the call sites correctly listed the constructor. A
DIRECTED check cannot tell which end of such a pair is wrong, but it can
detect that the pair contradicts itself: `_detect_mutual_dependencies`
finds every (A, B) where A's related_sites names B and B's names A, and
both halves of any such pair are added to the directional closure's
self-unsafe set (see run()'s docstring) -- declined for review rather
than silently trusted in either direction. Recorded unconditionally in
the run's own `mutual_dependency_warnings` output, whether or not it
changed any bucket outcome.

Joint-resolution eligibility is a property of being span-guarded, not of
having a related_sites edge: `_add_singleton_span_groups` gives a
span-guarded PROPOSED site that adjudication never linked to anything its
own single-member group, so it reaches `_run_joint_group` too, instead of
the immediate, no-model-call decline it used to get unconditionally --
real-run data showed two essentially identical span-guarded constructors
(run-secops, run-youtrack) getting different treatment for a reason that
had nothing to do with either one's own shape, only with whether
adjudication happened to draw an edge. A single-member call uses a
different addendum (`_SOLO_SPAN_ADDENDUM`) that tells the model plainly
there is no companion site and to decline rather than guess at or drop a
value with nowhere shown to go -- and `_check_group_value_flow`, unchanged,
backs that up mechanically: a value removed from a lone member's own block
always fails it, since a 1-element group has no OTHER member for that
value to reappear in. A multi-member group is entirely unaffected by any
of this -- same addendum, same classification, same everything."""
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
    """This fires in exactly one case now (see run()'s Pass 1): a
    span-guarded PROPOSED site whose RESOLUTION group is "uncertain_decline"
    -- a PROPOSED member's own dependency (this site's or a companion's)
    reaches an unconfirmed FLAG-UNCERTAIN site. Every OTHER span-guarded
    site -- with or without a related_sites companion -- is now routed to
    a joint or solo model call instead (_add_singleton_span_groups), so
    the reason text below no longer claims fixgen can't produce a
    block-level fix at all; it explains why no attempt was made for THIS
    site specifically."""
    start, end = span
    return {
        "file": site["file"],
        "line": site["line"],
        "reason": (
            f"this line is part of a multi-line statement spanning lines "
            f"{start}-{end}; a fix has to cover the whole statement, but no "
            f"coordinated attempt was made because this site's own "
            f"resolution group also depends on a site adjudication could "
            f"not confirm (see group_members below) -- resolving this "
            f"statement without also resolving what that unconfirmed site "
            f"needs from it risks shipping a fix that leaves the migration "
            f"incomplete."
        ),
        "flag_source": "multiline_span_guard",
        "span": [start, end],
    }


def _site_key(site):
    return (site["file"], site["line"])


def _union_find_groups(sites_by_key, edge_from):
    """Deterministic union-find over sites_by_key's related_sites links,
    counting an edge FROM a given site only when edge_from(entry) says to
    -- the shared core behind _group_by_related_sites (every edge counts,
    the full undirected VISIBILITY view) and _resolution_groups (only a
    PROPOSED site's own edges count, the RESOLUTION view; see that
    function's docstring for why the two must differ). Kept as one small
    function, not duplicated, so the union-find mechanics themselves --
    unrelated to which edges are being asked about -- have exactly one
    implementation.

    Returns (group_id_by_key, group_members_by_id): group_id_by_key is
    {(file, line): group_id} for keys in a multi-member group (singletons
    absent); group_members_by_id is {group_id: sorted [(file, line), ...]}."""
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
        if not edge_from(entry):
            continue
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

    return group_id_by_key, group_members_by_id


def _group_by_related_sites(proposed_sites, uncertain_sites):
    """The full undirected VISIBILITY view -- computed once, before the
    model sees anything, per the coupling design pass: fact-citation was
    measured to both over-group (a self-contained rename shares fact
    numbers with the constructor it has nothing to do with) and
    under-group (the actually coupled sites on run-azeroth share zero fact
    numbers), so grouping is derived from adjudication's own related_sites
    field instead -- the structural record of the dependency it already
    states in prose (e.g. "depends on what was passed to the FastMCP(
    constructor at line 68").

    Every edge counts here, regardless of which site's role declared it --
    this is the view report.py and every human-facing flag's group_id/
    group_members render, so a reviewer sees the WHOLE coupled
    neighborhood (an uncertain site included) around whatever declined.
    It is deliberately NOT the view that decides eligibility or what gets
    sent to the model together -- see _resolution_groups and run()'s
    docstring for the real-run regression (run-youtrack-solo) that
    conflating the two caused: an uncertain site's edge to a span-guarded
    site with no dependencies of its own pulled that site into an
    undirected group, and group_class read "contains an uncertain member"
    off that same undirected group, wrongly declining a site nothing
    about its own correctness depends on.

    Returns (sites_by_key, group_id_by_key, group_members_by_id):
      - sites_by_key: {(file, line): {"role": "proposed"|"uncertain", "site": dict}}
        for every site in proposed_sites + uncertain_sites (uncertain wins
        on a key collision, which should not happen -- adjudication assigns
        each candidate to exactly one bucket -- but is harmless either way,
        since role only affects auto-decline eligibility below).
      - group_id_by_key, group_members_by_id: see _union_find_groups.

    A related_sites entry naming a (file, line) outside this run's own
    proposed_sites/uncertain_sites (e.g. a REJECTed candidate, or a line
    that was never a candidate at all) contributes no edge -- there is
    nothing on this run's side of that link to group with, or to decline."""
    sites_by_key = {}
    for site in proposed_sites:
        sites_by_key[_site_key(site)] = {"role": "proposed", "site": site}
    for site in uncertain_sites:
        sites_by_key.setdefault(_site_key(site), {"role": "uncertain", "site": site})

    group_id_by_key, group_members_by_id = _union_find_groups(sites_by_key, lambda entry: True)
    return sites_by_key, group_id_by_key, group_members_by_id


def _resolution_groups(sites_by_key):
    """The RESOLUTION view: union-find restricted to edges declared by
    PROPOSED sites only -- an UNCERTAIN site's own related_sites entries
    contribute no edge here. This is what decides eligibility (group_class)
    and what actually gets sent to _run_joint_group together; the full
    undirected view from _group_by_related_sites is for report rendering
    only (see that function's docstring and run()'s for the regression
    this fixes).

    Why restricting to PROPOSED-declared edges is the right rule, not an
    arbitrary one: an uncertain site is NEVER itself sent to the model --
    its own resolution was never confirmed by adjudication, so it can
    never be a member of an actual _run_joint_group call. Its related_sites
    claim ("I need to see line N") therefore creates no real coordination
    NEED on line N's part; line N's own correctness does not depend on
    the uncertain site ever resolving (this is the same "blocking flows
    from a dependency to its dependents, never the reverse" principle
    _compute_unsafe_sites already applies -- this function applies the
    identical principle one step earlier, to GROUPING, not just BLOCKING).
    A PROPOSED site's own edge is different: that site DOES get sent to
    the model, and if its own fix genuinely depends on a companion's
    content, the two must be resolved together -- exactly the legitimate,
    unchanged multi-member joint_resolve case (e.g. a call site that
    needs a constructor's arguments). And a PROPOSED site's edge landing
    on an UNCERTAIN site is preserved too, correctly: if a confident site's
    own correctness depends on unconfirmed content, uncertain_decline
    SHOULD still apply to it -- that was always the legitimate reason the
    guard exists, untouched by this restriction.

    Returns (group_id_by_key, group_members_by_id), same shape as
    _group_by_related_sites' own -- see _union_find_groups."""
    return _union_find_groups(sites_by_key, lambda entry: entry["role"] == "proposed")


def _add_singleton_span_groups(group_id_by_key, group_members_by_id, sites_by_key, span_map):
    """Gives every span-guarded PROPOSED site with no group of its own a
    synthetic one-member group, so run()'s existing group_class pass (which
    already classifies ANY group with a span member and no uncertain member
    as "joint_resolve", regardless of size) picks it up for real, without
    that pass needing to know or care that this group is synthetic.

    Why this exists: before it, joint-resolution eligibility was a property
    of HAVING a related_sites edge, not of BEING span-guarded -- a site
    reached _run_joint_group only if adjudication happened to link it to a
    companion. That link is arbitrary with respect to whether a joint call
    would help a lone span-guarded site: on real run data (run-secops,
    run-youtrack) two essentially identical span-guarded constructors got
    different treatment (one got a shot at an automated fix, the other was
    unconditionally declined with no model call) purely because one had a
    related_sites edge and the other didn't. Eligibility now depends only
    on being span-guarded, matching what the guard is actually for.

    MUST be called with _resolution_groups' output, not
    _group_by_related_sites' -- run() does this. A key already grouped in
    the full undirected VISIBILITY view but NOT in the RESOLUTION view
    (an uncertain site's edge is the only thing connecting it to anyone)
    still needs a synthetic group here; only the RESOLUTION view can tell
    the two cases apart. This is the fix for the run-youtrack-solo
    regression: passing the visibility view here was the original bug --
    an uncertain site naming a span-guarded site with no dependencies of
    its own made that site look "already grouped" and skip this pass
    entirely, even though nothing about ITS OWN correctness depends on
    the uncertain site ever resolving. See run()'s docstring.

    Only PROPOSED-role, already-ungrouped (in the RESOLUTION view) keys
    are touched -- a key already in group_id_by_key there (a real,
    >=2-member RESOLUTION group) is left alone entirely, so a multi-member
    group's classification and behavior are completely unchanged by this
    pass; span_map itself only ever contains proposed-role keys in the
    first place (see run()'s docstring), so the role check here is a
    defensive assertion of that invariant, not a filter expected to ever
    exclude anything in practice.

    Returns NEW group_id_by_key/group_members_by_id dicts (does not mutate
    the ones passed in) with the synthetic single-member groups added. A
    synthetic group's id is the member's own (file, line) -- distinct by
    construction from any real group's id, since a real group's id is some
    OTHER member's key (the union-find root), and this key is, by
    definition of being processed here, not a member of any real
    RESOLUTION group."""
    group_id_by_key = dict(group_id_by_key)
    group_members_by_id = dict(group_members_by_id)
    for key in span_map:
        if key in group_id_by_key:
            continue
        if sites_by_key[key]["role"] != "proposed":
            continue
        gid = f"{key[0]}:{key[1]}"
        group_id_by_key[key] = gid
        group_members_by_id[gid] = [key]
    return group_id_by_key, group_members_by_id


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


def _detect_mutual_dependencies(depends_on):
    """Every unordered pair (A, B) where A's related_sites names B AND B's
    related_sites names A -- a raw 2-cycle in the DIRECTED depends_on graph
    _direct_dependencies builds. related_sites is specified as one-way
    (adjudication_system.md: "this relation runs ONE way... would MY
    verdict change if I saw line N"), so a real edge in both directions
    between the same two sites is always a contradiction, never a
    legitimate mutual need -- either a genuine adjudication error (one
    direction real, one backwards) or, in principle, a true cycle, which
    the guide's own migration facts never actually produce. A directed
    check like this one cannot tell WHICH end is wrong, only that the pair
    disagrees with itself -- see run()'s docstring for the real-run case
    this exists for (run-azeroth-joint, main.py:68 vs. 153/170) and why it
    is still trusted as a signal despite that limit.

    Self-loops (a site naming itself) are excluded -- not a mutual-pair
    contradiction, and not this function's concern.

    Returns a sorted list of ((file, line), (file, line)) tuples, each
    unordered pair appearing exactly once with its two keys in sorted
    order."""
    pairs = set()
    for a, deps in depends_on.items():
        for b in deps:
            if a != b and b in depends_on and a in depends_on[b]:
                pairs.add(tuple(sorted((a, b))))
    return sorted(pairs)


def _compute_unsafe_sites(all_keys, depends_on, self_unsafe):
    """Fixed-point closure over the DIRECTED depends_on graph.

    `self_unsafe`: the set of keys unsafe for their OWN reason -- an
    uncertain-role site (never confirmed by adjudication), a site with an
    unresolved multi-line span (never fixed, whether because it was never
    eligible for joint resolution or because a joint-resolution attempt
    for it did not produce a fix), or a site that is one half of a mutual
    (bidirectional) related_sites pair per _detect_mutual_dependencies --
    both halves of such a pair are treated as self-unsafe, not just one.

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


def _describe_unsafe_cause(key, unsafe_cause, sites_by_key, span_map, mutual_partners):
    """One clause explaining why `key` is unsafe, for a human-facing
    decline reason -- `key` must be a key of `unsafe_cause`. Recurses one
    logical hop at a time along the SAME chain _compute_unsafe_sites
    already resolved (never re-derives it), so the text names the real,
    concrete, base-case reason (uncertain / span / mutual-dependency /
    joint-resolution outcome) rather than stopping at a vague "it was
    declined" for a multi-hop chain.

    `mutual_partners`: {key: [partner_key, ...]} from run()'s
    _detect_mutual_dependencies pass -- checked before the generic
    fallback so a site made self-unsafe by a contradictory related_sites
    pair gets that real reason instead of the misleading generic "was not
    resolved by a coordinated fix" (it may never have been part of any
    joint-resolution attempt at all)."""
    cause = unsafe_cause[key]
    if cause == key:
        if key in mutual_partners:
            partners = ", ".join(f"{p[0]}:{p[1]}" for p in sorted(mutual_partners[key]))
            return (f"{key[0]}:{key[1]} and {partners} name each other in related_sites -- "
                     f"a self-contradictory link (mutual_dependency_guard); a directed check "
                     f"cannot tell which direction, if either, is correct, so both are "
                     f"treated as unsafe")
        if sites_by_key[key]["role"] == "uncertain":
            return f"{key[0]}:{key[1]} was not confirmed by adjudication"
        if key in span_map:
            start, end = span_map[key]
            return (f"{key[0]}:{key[1]} was not evaluated (multi-line statement "
                     f"spanning lines {start}-{end})")
        return f"{key[0]}:{key[1]} was not resolved by a coordinated fix"
    dep_reason = _describe_unsafe_cause(cause, unsafe_cause, sites_by_key, span_map, mutual_partners)
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


def _parses(text):
    """Whether `text` parses as Python once dedented, same preprocessing as
    _extract_call_keywords. Used by _check_group_value_flow to tell "this
    side genuinely has no keywords" apart from "this side failed to parse
    and _extract_call_keywords silently degraded to {}" -- the two look
    identical to that function's return value alone, but must be treated
    differently: a parse failure must not be read as proof of absence in
    either direction (see _check_group_value_flow's docstring)."""
    try:
        ast.parse(textwrap.dedent(text))
    except SyntaxError:
        return False
    return True


def _check_group_value_flow(group_fixes):
    """The deterministic safety net a jointly-resolved group's fixes must
    pass before any of them is trusted, per the design pass: a model can
    produce a coordinated edit that parses fine, passes ordinary line-match
    verification, and still silently mishandles a value that has to move
    between two calls -- either direction. Neither tier 1 nor tier 2
    verification (apidrift/verify.py) can see this: both check a fix's own
    internal consistency, never whether a SET of fixes jointly preserves a
    value that moved between them.

    Checks BOTH directions of the same move, symmetrically:

    - REMOVAL: a keyword argument present in a fix's original block but
      ABSENT (or changed) in its own proposed block is "removed" there and
      must reappear, with an AST-EQUAL value expression (ast.dump
      comparison, not name/string matching), in some OTHER member's
      proposed block. Deliberately expression-equality, not name-presence:
      `port=port` removed at one site and `port=8000` added at another has
      the same keyword NAME present but a different value expression, so
      it still fails -- the silent-substitution shape this side catches.
      Unmatched, this is reported as a value dropped on the floor.

    - ADDITION: a keyword argument present in a fix's proposed block but
      ABSENT (or changed) from its own original block is "added" there and
      must be traceable to an AST-EQUAL value removed from some OTHER
      member's original block. Unmatched, this is reported as a value that
      appeared from nowhere -- the case a purely-removal-side check misses:
      a joint call can invent `host="0.0.0.0"` on a `run()` call the
      constructor never carried, produce a plausible-looking coordinated
      edit, and pass a removal-only check clean because nothing was
      dropped anywhere.

    LEGITIMATE EXCEPTION, stated rather than assumed away: a real migration
    can require adding a keyword that existed nowhere in the group before
    (a new required parameter with no prior equivalent, not a moved one).
    This check cannot tell that case apart from an invented one -- both are
    "a value appears with no matching removal" to a purely textual/AST
    comparison. It deliberately does NOT special-case this: a grounded
    addition and an invented one are indistinguishable to a guard with no
    access to the migration semantics, so both are flagged for a human to
    resolve rather than one being silently let through on the assumption
    it must be the legitimate case. This will produce some false positives
    on real new-parameter migrations; that is the intended, safe failure
    direction -- flagged_for_human, not a silently shipped guess.

    SINGLE-MEMBER GROUPS (run()'s _add_singleton_span_groups, a lone
    span-guarded site with no related_sites companion): this function
    needs, and gets, NO special-casing for them, and that is a deliberate
    choice, not an oversight. With one fix in `group_fixes`, "some OTHER
    member's block" in both checks above can never be satisfied -- there
    is no other member. So ANY keyword removed or added at that lone site
    (relative to its own original) fails unconditionally, every time. That
    is exactly correct: this is precisely the shape of the real youtrack-mcp
    failure this whole guard exists to prevent (a constructor's host/port
    dropped with no visible site to receive them) -- for a single-member
    group specifically, there is no candidate site anywhere in the call
    that COULD have received it, so failing is not a false-positive-prone
    approximation the way the multi-member addition case sometimes is, it
    is the only sound answer available. A single-member fix that changes
    NOTHING about its own keyword arguments (a pure rename, a reordering of
    positional arguments -- invisible to this AST-Call-keyword-only check
    regardless of group size, per limit (1) below) still passes cleanly,
    which is exactly the shape a lone span-guarded site's fix should
    usually take. Special-casing single-member groups to skip this check
    -- the tempting alternative -- would silently reopen the exact failure
    this guard exists for, on exactly the sites (no companion in sight)
    where a human would least expect a dropped value to have been caught.

    Returns None if every removed value is accounted for AND every added
    value is accounted for, or a human-readable string naming what's wrong
    otherwise. Deterministic, no model call -- pure AST comparison over
    fixes already produced.

    Known limits, stated plainly rather than silently: (1) this only
    tracks KEYWORD arguments in Call nodes, in both directions -- a value
    carried via a positional argument, a plain assignment, or any
    non-call construct is invisible to it, whether it's the removed side
    or the added side of a move. (2) a block that fails to parse on its
    own (should not happen -- these blocks come from _multiline_spans,
    whose whole reason for existing is that its spans ARE complete,
    independently parseable simple statements -- but if it ever does)
    degrades to an empty keyword set for that member from
    _extract_call_keywords, but that emptiness is NOT trusted as proof of
    absence here: a member whose OWN original failed to parse contributes
    no "added" obligations from its proposed side (we can't tell whether a
    keyword was already there), and a member whose OWN proposed failed to
    parse contributes no "removed" obligations from its original side (we
    can't tell whether a keyword survived) -- tracked via _parses()
    separately from the keyword extraction itself, so a parse failure
    degrades to "neither contributes nor discharges an obligation on
    either side" exactly as documented, in both directions, not just the
    removal one. (3) this proves an expression MOVED unchanged, in either
    direction; it cannot prove the destination is the semantically right
    place for it, or that the code is behaviorally correct at runtime --
    that residual gap is real and is not closed by this or any other
    static check in this pipeline."""
    orig_kw = {}
    prop_kw = {}
    orig_ok = {}
    prop_ok = {}
    for fix in group_fixes:
        key = (fix["file"], fix["line"])
        orig_text = "\n".join(fix["original_lines"])
        prop_text = "\n".join(fix["proposed_lines"])
        orig_kw[key] = _extract_call_keywords(orig_text)
        prop_kw[key] = _extract_call_keywords(prop_text)
        orig_ok[key] = _parses(orig_text)
        prop_ok[key] = _parses(prop_text)

    missing = []
    for key, kws in orig_kw.items():
        if not prop_ok[key]:
            continue  # own proposed side failed to parse -- can't tell if this survived
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

    unexplained = []
    for key, kws in prop_kw.items():
        if not orig_ok[key]:
            continue  # own original side failed to parse -- can't tell if this is new
        own_orig = orig_kw[key]
        for name, dump in kws.items():
            if own_orig.get(name) == dump:
                continue  # unchanged at the same site -- not an addition at all
            sourced_elsewhere = any(
                other_key != key and orig_kw[other_key].get(name) == dump
                for other_key in orig_kw
            )
            if not sourced_elsewhere:
                unexplained.append(f"{key[0]}:{key[1]} keyword {name!r}")

    problems = []
    if missing:
        problems.append(
            "value(s) removed with no matching reappearance elsewhere in the group: "
            + ", ".join(missing)
        )
    if unexplained:
        problems.append(
            "value(s) added with no matching removal elsewhere in the group "
            "(grounded new parameter or invented guess -- indistinguishable here): "
            + ", ".join(unexplained)
        )
    if problems:
        return "; ".join(problems)
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


def _visibility_group_fields(member_keys, vis_group_id_by_key, vis_group_members_by_id, sites_by_key):
    """The group_id/group_members to stamp on a fix or flag coming out of
    _run_joint_group -- the full undirected VISIBILITY neighborhood for
    this call's members (see _group_by_related_sites, _resolution_groups,
    and run()'s docstring for why this differs from what the call's own
    RESOLUTION-scoped member_keys is), falling back to member_keys itself,
    rendered the same way, when none of them has a broader one.

    Every member of a real (non-synthetic) RESOLUTION group shares the
    exact same VISIBILITY group by construction -- RESOLUTION-view edges
    (PROPOSED-declared only) are a subset of VISIBILITY-view edges (every
    edge), so two keys unioned in the former are guaranteed unioned in the
    (possibly larger) latter too. Checking just the first member is
    therefore sufficient, not an assumption specific to any one caller."""
    first = member_keys[0]
    vis_gid = vis_group_id_by_key.get(first)
    if vis_gid is not None:
        return vis_gid, _group_members_rendered(vis_group_members_by_id[vis_gid], sites_by_key)
    return None, _group_members_rendered(member_keys, sites_by_key)


def _run_joint_group(client, reader, gid, member_keys, sites_by_key, span_map,
                      base_system_text, fg_dir, cache_system, cache_ttl,
                      vis_group_id_by_key, vis_group_members_by_id):
    """One idempotent, resumable call resolving every member of a
    joint_resolve group (see run()'s classification pass) together: either
    a consistent set of (possibly multi-line) block fixes for every member,
    or a joint decline for the whole group. The model's own bucket choice
    is necessary but never sufficient here -- every fixes-bucket result is
    re-verified by _check_group_value_flow below before it is trusted.

    `gid`/`member_keys` are RESOLUTION-scoped (see run()'s docstring) --
    who is actually sent to the model, and the only members validated for
    complete/consistent bucket coverage. `vis_group_id_by_key`/
    `vis_group_members_by_id` are the separate, full undirected VISIBILITY
    view, consulted ONLY to decide what `group_id`/`group_members` a
    resulting fix or flag renders for a human -- never to decide who's in
    this call or what the model sees. The two can differ: an uncertain
    site can be part of member_keys' VISIBILITY neighborhood (it depends
    on one of these members) without ever being sent here itself.

    `member_keys` of length 1 is the solo-span case (see run()'s
    _add_singleton_span_groups): a span-guarded site with no related_sites
    companion, given its own single-member call rather than the immediate,
    no-model-call decline it used to get unconditionally. It uses a
    DIFFERENT addendum (_SOLO_SPAN_ADDENDUM, not _JOINT_ADDENDUM) -- the
    multi-member addendum talks about a value moving "between these exact
    sites" and instructs the model to find where a removed value "actually
    appears... in whichever other member's block", which is nonsensical
    and actively misleading when there is no other member. The solo
    addendum instead tells the model plainly that no companion is shown
    and to decline rather than invent or silently drop a value it can't
    see a destination for -- belt-and-suspenders with _check_group_value_flow
    below, which independently enforces the same thing mechanically
    regardless of what the model was told (see that function's docstring
    for why a single-member group can never pass it if a fix drops a
    keyword: there is nowhere else in a 1-element group for it to
    reappear, so the guard fails closed exactly on the shape that matters).
    A multi-member call is completely unchanged from before this addition
    -- same addendum, same framing, same everything.

    Returns (fixes, flags): fixes is a list of fix dicts with this
    function's own group_id stamped on (never taken from the model);
    flags is a list of flagged_for_human dicts, each carrying group_id/
    group_members so report.py can render the group -- either the model's
    own joint decline, or this function's value_flow_guard override when
    the model's fixes didn't pass the deterministic check. Exactly one of
    the two returned lists is non-empty."""
    path = _group_call_path(fg_dir, gid)
    member_set = set(member_keys)
    is_solo = len(member_keys) == 1

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
        if is_solo:
            user_text = (
                f"SPAN-GUARDED SITE {gid} -- a multi-line statement with no "
                f"related_sites companion in this run (see this call's instructions "
                f"above):\n\n" + "\n\n".join(blocks)
            )
        else:
            user_text = (
                f"COORDINATED GROUP {gid} -- {len(member_keys)} member site(s) that must be "
                f"resolved TOGETHER (see this call's coordinated-group instructions above):\n\n"
                + "\n\n".join(blocks)
            )
        addendum = _SOLO_SPAN_ADDENDUM if is_solo else _JOINT_ADDENDUM
        result = client.complete(
            stage=f"fixgen_group_{_sanitize_gid(gid)}",
            system_text=base_system_text + "\n\n---\n\n" + addendum,
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

    # What a human sees on any resulting fix/flag -- the VISIBILITY
    # neighborhood if these members have one, else just themselves. NOT
    # `gid`/member_keys directly: those are RESOLUTION-scoped and may be
    # narrower (run()'s docstring; e.g. this call's own solo `gid` when an
    # uncertain site depends on this member without being sent here).
    render_gid, members_rendered = _visibility_group_fields(
        member_keys, vis_group_id_by_key, vis_group_members_by_id, sites_by_key,
    )
    if render_gid is None:
        render_gid = gid

    if result["fixes"]:
        fixes = [dict(item, group_id=render_gid) for item in result["fixes"]]
        failure = _check_group_value_flow(fixes)
        if failure is not None:
            flags = [{
                "file": f, "line": l,
                "reason": (
                    f"this site's confident-looking joint fix for coordinated group {render_gid} "
                    f"was rejected by the deterministic value-flow guard: {failure}. A "
                    f"model-proposed coordinated edit is never trusted without this check. "
                    f"Falling back to flagged_for_human for every member of this group "
                    f"rather than shipping an edit that may have silently dropped a value."
                ),
                "flag_source": "value_flow_guard",
                "group_id": render_gid,
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
         "group_id": render_gid, "group_members": members_rendered}
        for item in result["flagged_for_human"]
    ]
    return [], flags


_PROMPT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")
with open(os.path.join(_PROMPT_DIR, "fixgen_system.md")) as _f:
    _TEMPLATE = _f.read()
with open(os.path.join(_PROMPT_DIR, "fixgen_joint_addendum.md")) as _f:
    _JOINT_ADDENDUM = _f.read()
with open(os.path.join(_PROMPT_DIR, "fixgen_solo_span_addendum.md")) as _f:
    _SOLO_SPAN_ADDENDUM = _f.read()

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

    # group_id_by_key/group_members_by_id below is the full undirected
    # VISIBILITY view -- used ONLY to render group_id/group_members on a
    # human-facing flag, never again after this point. resolve_id_by_key/
    # resolve_members_by_id, computed right after, is the RESOLUTION view
    # (PROPOSED-declared edges only) -- everything that decides ELIGIBILITY
    # or what gets sent to _run_joint_group together uses that one instead.
    # See _group_by_related_sites' and _resolution_groups' own docstrings,
    # and the run-youtrack-solo regression in this docstring above, for why
    # the two must not be the same structure.
    sites_by_key, group_id_by_key, group_members_by_id = _group_by_related_sites(
        sites, uncertain_sites,
    )
    resolve_id_by_key, resolve_members_by_id = _resolution_groups(sites_by_key)

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

    # A span-guarded site adjudication never linked to anything gets its
    # own synthetic one-member group here, so the classification pass right
    # below (which already treats ANY group with a span member and no
    # uncertain member as "joint_resolve", regardless of size) picks it up
    # too -- eligibility for a joint-style call is a property of being
    # span-guarded, not of happening to have a related_sites edge. See
    # _add_singleton_span_groups's own docstring for the real-run gap this
    # closes (run-secops, run-youtrack) and _run_joint_group's docstring
    # for how a single-member call differs (a different addendum, and why
    # _check_group_value_flow is still both necessary and sufficient on a
    # 1-element group).
    resolve_id_by_key, resolve_members_by_id = _add_singleton_span_groups(
        resolve_id_by_key, resolve_members_by_id, sites_by_key, span_map,
    )

    # Classify every RESOLUTION group once (real, >=2-member groups from
    # PROPOSED-declared related_sites edges, and the synthetic 1-member
    # span groups just added above -- this loop doesn't distinguish them,
    # by design):
    #  - "uncertain_decline": a member of this group depends -- via a
    #    PROPOSED site's own edge, since that's the only kind of edge the
    #    RESOLUTION view contains -- on an unconfirmed site. Never applies
    #    to a synthetic group: _add_singleton_span_groups only ever
    #    creates one from a PROPOSED-role key with no edges of its own.
    #  - "joint_resolve": every member is confirmed, but at least one needs
    #    block-level treatment a lone per-line call can't safely give --
    #    the youtrack-mcp shape this increment adds real handling for, and
    #    what a synthetic 1-member group always is (that's the only reason
    #    it exists).
    #  - unclassified: ordinary confident members with nothing forcing
    #    coordinated handling -- already handled correctly by reaching the
    #    model independently (same chunk, no group framing), per the
    #    original coupling increment's own measured scope.
    group_class = {}
    for gid, member_keys in resolve_members_by_id.items():
        has_uncertain = any(sites_by_key[k]["role"] == "uncertain" for k in member_keys)
        if has_uncertain:
            group_class[gid] = "uncertain_decline"
        elif any(k in span_map for k in member_keys):
            group_class[gid] = "joint_resolve"

    auto_flagged = []

    # Pass 1 -- immediate multi-line-span flags. Fires for every span-having
    # site EXCEPT one whose RESOLUTION group is classified "joint_resolve":
    # that site's fate is decided jointly with the rest of that group in
    # pass 2 below, with full visibility into every member, instead of
    # alone here. Eligibility is read from the RESOLUTION view
    # (resolve_id_by_key) -- after _add_singleton_span_groups, this is
    # never None for a span-having key, so the only way a span site is
    # flagged here now is a genuine "uncertain_decline" RESOLUTION group
    # (a PROPOSED member's own edge reaches an unconfirmed site). The
    # flag's OWN group_id/group_members, though, render the full
    # undirected VISIBILITY view (group_id_by_key) -- a reviewer sees
    # every related site, uncertain ones included, even ones the
    # RESOLUTION view excluded from eligibility.
    for key, (start, end) in span_map.items():
        resolve_gid = resolve_id_by_key.get(key)
        if resolve_gid is not None and group_class.get(resolve_gid) == "joint_resolve":
            continue
        site = sites_by_key[key]["site"]
        flag = _multiline_span_flag(site, (start, end))
        vis_gid = group_id_by_key.get(key)
        if vis_gid is not None:
            flag["group_id"] = vis_gid
            flag["group_members"] = _group_members_rendered(group_members_by_id[vis_gid], sites_by_key)
        auto_flagged.append(flag)

    span_declined = {
        key for key in span_map
        if not (resolve_id_by_key.get(key) and group_class.get(resolve_id_by_key[key]) == "joint_resolve")
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
    # Cached per KIND (solo vs multi-member), not as one flag for all of
    # them: a solo call's system_text carries _SOLO_SPAN_ADDENDUM, a
    # multi-member call's carries _JOINT_ADDENDUM -- the two are different
    # byte-for-byte, so caching only pays off when there's more than one
    # call of the SAME kind to read the cache write back. Getting this
    # wrong doesn't break anything (a cache write nothing reads back just
    # costs the cache_creation rate instead of the plain input rate on that
    # one call), but there's no reason to pay it needlessly.
    solo_gids = {gid for gid in joint_gids if len(resolve_members_by_id[gid]) == 1}
    solo_count = len(solo_gids)
    multi_count = len(joint_gids) - solo_count
    joint_resolved_keys = set()  # every member of a joint_resolve group, fixed or not
    joint_fixed_keys = set()     # the subset that actually received a fix
    for gid in joint_gids:
        # member_keys -- who is ACTUALLY sent to the model together -- comes
        # from the RESOLUTION view. Never the VISIBILITY one: an uncertain
        # site can appear in the visibility group (e.g. run-youtrack-solo's
        # 70), and it must never reach the model -- its own resolution was
        # never confirmed by adjudication in the first place.
        member_keys = resolve_members_by_id[gid]
        same_kind_count = solo_count if gid in solo_gids else multi_count
        cache_this_call = same_kind_count > 1 or cache_ttl != "5m"
        result_fixes, result_flags = _run_joint_group(
            client, reader, gid, member_keys, sites_by_key, span_map,
            system_text, fg_dir, cache_this_call, cache_ttl,
            group_id_by_key, group_members_by_id,
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

    # Mutual-dependency guard: a related_sites edge is specified as
    # one-way (adjudication_system.md), so a pair that names each other
    # is always a contradiction -- see run-azeroth-joint (main.py:68 vs.
    # 153/170) for the real case this catches. Cannot tell which end is
    # wrong, so both halves of every such pair are added to self_unsafe
    # here, before the closure runs, same as any other base-case reason.
    mutual_pairs = _detect_mutual_dependencies(depends_on)
    mutual_partners = {}
    for a, b in mutual_pairs:
        mutual_partners.setdefault(a, []).append(b)
        mutual_partners.setdefault(b, []).append(a)
        self_unsafe.add(a)
        self_unsafe.add(b)

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
        cause_clause = _describe_unsafe_cause(key, unsafe_cause, sites_by_key, span_map, mutual_partners)
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

    # Added after the per-chunk merge above, never inside it: this key is
    # computed once by this function from the whole run's dependency graph,
    # not accumulated per-chunk like fixes/flagged_for_human (a model
    # response never has an opinion on it, so it isn't part of SCHEMA or
    # any chunk_NNN.json file). Recorded unconditionally, whether or not
    # the pair actually changed any bucket outcome -- a mutual pair can be
    # entirely inert (e.g. run-azeroth-joint's main.py:68, already unsafe
    # on its own multi-line span regardless of this guard) and still be a
    # real adjudication-output defect worth surfacing for a human or a
    # later prompt-quality sweep to see, independent of whether it
    # happened to change anything this run.
    merged["mutual_dependency_warnings"] = [
        {
            "sites": [{"file": a[0], "line": a[1]}, {"file": b[0], "line": b[1]}],
            "note": (
                "each site's related_sites names the other -- a self-contradictory "
                "link (related_sites is specified as one-way). A directed check "
                "cannot tell which direction, if either, is correct; both sites are "
                "treated as unsafe for blocking purposes (mutual_dependency_guard) "
                "regardless of role or final bucket."
            ),
        }
        for a, b in mutual_pairs
    ]

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
