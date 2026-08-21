"""Chunked adjudication. Idempotent per-chunk state on disk (one validated
file per chunk, written only after it passes validate.validate_adjudication_dict),
so a partial failure costs exactly the chunks that failed, not the whole
run. Adapted from rule_test/prefilter_experiment/pipeline.py's ChunkPlan --
same design, wired to an LLMClient instead of a human/agent dispatch.
"""
import json
import math
import os

from .. import validate
from . import factblock as factblock_stage

_PROMPT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")
with open(os.path.join(_PROMPT_DIR, "adjudication_system.md")) as _f:
    _TEMPLATE = _f.read()

SCHEMA = {
    "type": "object",
    "properties": {
        "proposed_sites": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "line": {"type": "integer"},
                    "snippet": {"type": "string"},
                    "pattern": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["file", "line", "snippet", "pattern", "reason"],
                "additionalProperties": False,
            },
        },
        "flag_uncertain": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "line": {"type": "integer"},
                    "snippet": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["file", "line", "snippet", "reason"],
                "additionalProperties": False,
            },
        },
        "considered_and_rejected": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "line": {"type": "integer"},
                    "snippet": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["file", "line", "snippet", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["proposed_sites", "flag_uncertain", "considered_and_rejected"],
    "additionalProperties": False,
}

DEFAULT_CHUNK_SIZE = 40


def _chunks(candidates, chunk_size):
    n = max(1, math.ceil(len(candidates) / chunk_size))
    out = []
    for i in range(n):
        part = candidates[i * chunk_size:(i + 1) * chunk_size]
        if part:
            out.append((i, part))
    return out


def _strip_internal_fields(candidates):
    """The candidate list shown to the model must not carry apidrift's own
    bookkeeping field (_pattern, used only by guards.py)."""
    out = []
    for c in candidates:
        out.append({k: v for k, v in c.items() if not k.startswith("_")})
    return out


def _chunk_path(adj_dir, idx):
    return os.path.join(adj_dir, f"chunk_{idx:03d}.json")


def _chunk_is_done(adj_dir, idx, chunk_candidates):
    path = _chunk_path(adj_dir, idx)
    if not os.path.isfile(path):
        return False
    try:
        data = validate.validate_adjudication_file(path)
    except ValueError:
        return False
    adjudicated = set()
    for bucket in ("proposed_sites", "flag_uncertain", "considered_and_rejected"):
        for item in data[bucket]:
            adjudicated.add((item["file"], item["line"]))
    expected = {(c["file"], c["line"]) for c in chunk_candidates}
    return adjudicated == expected


def run(client, candidates, factblock, workdir, chunk_size=DEFAULT_CHUNK_SIZE):
    """Returns the merged three-bucket dict. Writes workdir/adjudication/
    chunk_NNN.json (one per chunk) and workdir/adjudication/merged.json."""
    adj_dir = os.path.join(workdir, "adjudication")
    os.makedirs(adj_dir, exist_ok=True)

    facts_text = factblock_stage.render_facts_text(factblock)
    system_text = _TEMPLATE.replace("{MIGRATION_FACTS}", facts_text)

    chunks = _chunks(candidates, chunk_size)
    for idx, chunk_candidates in chunks:
        if _chunk_is_done(adj_dir, idx, chunk_candidates):
            continue
        shown = _strip_internal_fields(chunk_candidates)
        user_text = (
            f"CANDIDATE LIST ({len(shown)} items):\n\n"
            f"```json\n{json.dumps(shown, indent=2)}\n```"
        )
        result = client.complete(
            stage=f"adjudicate_chunk_{idx:03d}",
            system_text=system_text,
            user_text=user_text,
            schema=SCHEMA,
            cache_system=True,
            max_tokens=8000,
            effort="high",
        )
        validate.validate_adjudication_dict(result, what=f"chunk_{idx:03d}")
        expected = {(c["file"], c["line"]) for c in chunk_candidates}
        adjudicated = set()
        for bucket in ("proposed_sites", "flag_uncertain", "considered_and_rejected"):
            for item in result[bucket]:
                adjudicated.add((item["file"], item["line"]))
        if adjudicated != expected:
            missing = expected - adjudicated
            extra = adjudicated - expected
            raise ValueError(
                f"chunk_{idx:03d}: adjudication does not cover exactly the candidates "
                f"given -- missing {sorted(missing)}, unexpected {sorted(extra)}"
            )

        path = _chunk_path(adj_dir, idx)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(result, f, indent=2)
        os.replace(tmp, path)

    merged = {"proposed_sites": [], "flag_uncertain": [], "considered_and_rejected": []}
    for idx, _ in chunks:
        data = validate.validate_adjudication_file(_chunk_path(adj_dir, idx))
        for bucket in merged:
            merged[bucket].extend(data[bucket])

    merged_path = os.path.join(adj_dir, "merged.json")
    with open(merged_path, "w") as f:
        json.dump(merged, f, indent=2)
    validate.validate_adjudication_dict(merged, what=merged_path)
    return merged


def expand_duplicates(merged, expansion_map):
    """A representative candidate carrying duplicate_lines got one verdict
    from the model; this fans that single verdict back out to every
    original (file, line) stage C collapsed, so scoring and the report see
    every real site, not just the one representative per group. Lossless
    as long as expansion_map itself is (verified in prefilter's stage C)."""
    expanded = {"proposed_sites": [], "flag_uncertain": [], "considered_and_rejected": []}
    for bucket in expanded:
        for item in merged[bucket]:
            key = (item["file"], item["line"])
            members = expansion_map.get(key)
            if not members:
                expanded[bucket].append(item)
                continue
            for m in members:
                entry = dict(item)
                entry["line"] = m["line"]
                entry["snippet"] = m["snippet"]
                expanded[bucket].append(entry)
    return expanded
