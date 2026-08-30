"""Fix generation. Given confirmed sites (adjudication's proposed_sites,
pre-duplicate-expansion -- same cost-saving shape adjudicate.py itself
consumes downstream of prefilter's stage C), asks the model for either a
confident single-line replacement or a decline, per DESIGN.md section 4's
mechanical-rename vs. structural-refactor boundary. Same chunked,
idempotent-per-chunk-file design as adjudicate.py -- a partial failure costs
exactly the chunks that failed, not the whole run.

Also takes adjudication's flag_uncertain sites (context only -- see
run()'s docstring) to compute coupling groups from adjudication's
related_sites field: sites whose own correctness depends on another
site's content, per the coupling design pass. A group containing an
uncertain member, or a member the multi-line-span guard already declined,
is deterministically declined in its entirety before the model ever sees
it (`_group_consistency_flag`, flag_source "group_consistency_guard") --
this is the fix for the youtrack-mcp insufficient-fix-set failure: a
confident, independently-generated fix for one coupled site while its
companion's resolution was never confirmed. Sending a coupled group to
the model to jointly resolve is explicitly out of scope; see run()'s
docstring for why.
"""
import ast
import json
import math
import os

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


_PROMPT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")
with open(os.path.join(_PROMPT_DIR, "fixgen_system.md")) as _f:
    _TEMPLATE = _f.read()

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
                    "original_line": {"type": "string"},
                    "proposed_line": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["file", "line", "original_line", "proposed_line", "reason"],
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
    flagged_for_human entry in this increment -- sending a coupled group to
    the model together, so it could jointly resolve an uncertain member's
    dependency, is explicitly out of scope here (no run's evidence shows a
    single-line-anchor coupled case to design that against; building it
    speculatively risks the opposite failure -- a confident-looking joint
    fix nothing has verified). Omitting it (the default) means no site in
    `sites` is ever grouped with anything uncertain, which is exactly
    today's behavior.

    `cache_ttl`: see adjudicate.run()'s docstring -- same reasoning for
    the cache_system gate below."""
    fg_dir = os.path.join(workdir, "fixgen")
    os.makedirs(fg_dir, exist_ok=True)

    facts_text = factblock_stage.render_facts_text(factblock)
    system_text = _TEMPLATE.replace("{MIGRATION_FACTS}", facts_text)

    sites_by_key, group_id_by_key, group_members_by_id = _group_by_related_sites(
        sites, uncertain_sites,
    )

    # Pass 1 -- multi-line-span guard (unchanged): a site whose line is only
    # part of a multi-line statement gets flagged deterministically here,
    # before the model ever sees it -- fixgen's unit is a single line, so it
    # structurally cannot judge whether the rest of that statement also
    # needs to change, and a confident single-line rename there can leave
    # the call broken (see the tonyzorin/youtrack-mcp `FastMCP(...)` gap
    # this guards against). Only ever runs over `sites` -- an uncertain
    # site never gets a fix of its own regardless, so span-checking it here
    # would be moot.
    span_cache = {}
    auto_flagged = []
    span_declined = {}  # (file, line) -> (start, end), for pass 2's trigger text
    for site in sites:
        span = _span_for_site(reader, span_cache, site["file"], site["line"])
        if span is not None:
            flag = _multiline_span_flag(site, span)
            key = _site_key(site)
            gid = group_id_by_key.get(key)
            if gid is not None:
                # This site is also a coupled group's anchor -- pass 2 below
                # will never produce a separate group_consistency_guard entry
                # for it (it's already declined), so report.py would have no
                # way to render this group at all unless the cross-reference
                # is attached here instead. flag_source stays
                # "multiline_span_guard" -- that is still the real, sufficient
                # reason THIS site wasn't evaluated; group_id/group_members
                # are additive, read by report.py to render the group.
                flag["group_id"] = gid
                flag["group_members"] = _group_members_rendered(
                    group_members_by_id[gid], sites_by_key,
                )
            auto_flagged.append(flag)
            span_declined[key] = span

    # Pass 2 -- group-consistency guard: a multi-member group where at
    # least one member is uncertain, or was just declined by pass 1, has no
    # jointly-consistent set this increment can produce (see run()'s
    # docstring) -- every not-yet-declined proposed member of that group is
    # declined too, deterministically, before it ever reaches the model.
    # This is the fix for the coupling failure itself: without it, an
    # otherwise-confident member of a group like this would go on to get an
    # independently-generated, independently-plausible single-line fix,
    # unaware its companion's resolution was never confirmed -- the same
    # "fix the confident member alone" shape the youtrack-mcp run produced.
    group_declined = set()
    for gid, member_keys in group_members_by_id.items():
        has_uncertain = any(sites_by_key[k]["role"] == "uncertain" for k in member_keys)
        span_members = [k for k in member_keys if k in span_declined]
        if not has_uncertain and not span_members:
            continue
        trigger_clauses = []
        if has_uncertain:
            for f, l in member_keys:
                if sites_by_key[(f, l)]["role"] == "uncertain":
                    reason = sites_by_key[(f, l)]["site"]["reason"]
                    trigger_clauses.append(
                        f"{f}:{l} was not confirmed by adjudication ({reason!r})"
                    )
        for f, l in span_members:
            start, end = span_declined[(f, l)]
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

    eval_sites = [
        s for s in sites
        if _site_key(s) not in span_declined and _site_key(s) not in group_declined
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

    merged = {"fixes": [], "flagged_for_human": list(auto_flagged)}
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
    `proposed_line` is the representative's verbatim replacement text --
    valid because stage C only ever collapses byte-identical source lines,
    so the same replacement applies to every one of them; `original_line`
    is each member's own snippet, not the representative's, so a per-item
    line-match check downstream still compares against real source text."""
    expanded = {"fixes": [], "flagged_for_human": []}
    for item in merged["fixes"]:
        key = (item["file"], item["line"])
        members = expansion_map.get(key)
        if not members:
            expanded["fixes"].append(item)
            continue
        for m in members:
            entry = dict(item)
            entry["line"] = m["line"]
            entry["original_line"] = m["snippet"]
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
