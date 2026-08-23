"""Fix generation. Given confirmed sites (adjudication's proposed_sites,
pre-duplicate-expansion -- same cost-saving shape adjudicate.py itself
consumes downstream of prefilter's stage C), asks the model for either a
confident single-line replacement or a decline, per DESIGN.md section 4's
mechanical-rename vs. structural-refactor boundary. Same chunked,
idempotent-per-chunk-file design as adjudicate.py -- a partial failure costs
exactly the chunks that failed, not the whole run.
"""
import json
import math
import os

from .. import validate
from . import factblock as factblock_stage

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


def run(client, reader, sites, factblock, workdir, chunk_size=DEFAULT_CHUNK_SIZE):
    """Returns the merged two-bucket dict. Writes workdir/fixgen/chunk_NNN.json
    (one per chunk) and workdir/fixgen/merged.json. `sites` should be
    adjudication's proposed_sites list -- one entry per distinct
    (file, line), pre-duplicate-expansion; callers expand the result with
    expand_duplicates(), the same shape adjudicate.py's own expansion takes."""
    fg_dir = os.path.join(workdir, "fixgen")
    os.makedirs(fg_dir, exist_ok=True)

    facts_text = factblock_stage.render_facts_text(factblock)
    system_text = _TEMPLATE.replace("{MIGRATION_FACTS}", facts_text)

    chunks = _chunks(sites, chunk_size)
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
            cache_system=True,
            max_tokens=8000,
            effort="high",
        )
        validate.validate_fixgen_dict(result, what=f"chunk_{idx:03d}")
        covered = set()
        for bucket in ("fixes", "flagged_for_human"):
            for item in result[bucket]:
                covered.add((item["file"], item["line"]))
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

    merged = {"fixes": [], "flagged_for_human": []}
    for idx, _ in chunks:
        data = validate.validate_fixgen_file(_chunk_path(fg_dir, idx))
        for bucket in merged:
            merged[bucket].extend(data[bucket])

    merged_path = os.path.join(fg_dir, "merged.json")
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
