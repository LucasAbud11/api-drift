"""Chunked vocabulary derivation. Stage 2's per-call output scales with
(fact count x patterns-per-fact x escaped-regex length): a single call
over a 234-fact partial derivation against the real MCP v1->v2 guide
(23k words, 819 facts once fully derived) truncated at max_tokens=16000.
Raising max_tokens again is not the fix, for the same reason stage 1
(factblock.py) and gap-fill (gapfill.py) both already reject it:
vocabulary is input to grep and to every downstream stage (adjudicate,
fixgen), so a bigger single-call ceiling makes every one of them more
expensive on every repo the guide is ever run against, not just fixes
this one call.

Chunked by fact count, same idempotent-per-chunk-file design
adjudicate.py/factblock.py/gapfill.py already use: one call derives
patterns for a slice of the fact block's own facts -- the same "output
size scales with item count" shape gap-fill's own chunking has, unlike
stage 1's guide-structure/token-budget splitting (stage 1 hasn't
produced the fact list yet when it chunks; stage 2 always has one by
the time it runs).

This was the last of this pipeline's four LLM-calling stages
(factblock, vocabulary, adjudicate, fixgen) to stay unchunked. See
REPORT.md: stage 2 fitting under one call's ceiling on the real 819-fact
MCP guide (115 patterns) was itself a symptom, not a clean bill of
health -- gap-fill later found 269 of those facts' identifier spans had
zero token overlap with any of those 115 patterns, meaning stage 2 never
attempted them at all. A single call silently narrowing its own
attempted scope to fit a ceiling looks, from the outside, identical to a
single call that covered everything; chunking removes that ambiguity by
forcing every fact into some chunk's own explicit scope, whether or not
that chunk's own response ends up producing a pattern for it.
"""
import json
import math
import os

from .. import llm, validate
from . import factblock as factblock_stage

_PROMPT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")

with open(os.path.join(_PROMPT_DIR, "vocabulary_system.md")) as _f:
    SYSTEM_PROMPT = _f.read()


# Structured-output schemas can't express an open-ended "object with
# arbitrary keys" (additionalProperties must be false) -- so the model
# returns a list of {name, regex} pairs instead of a name->regex mapping,
# and _merge_patterns converts the concatenated list into the dict every
# downstream consumer (grep.py, guards.py, pipeline.py, report.py)
# already expects.
SCHEMA = {
    "type": "object",
    "properties": {
        "patterns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "regex": {"type": "string"},
                },
                "required": ["name", "regex"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["patterns"],
    "additionalProperties": False,
}

MAX_TOKENS = 16000

# One real data point: a 234-fact partial derivation against the real
# MCP v1->v2 guide truncated at max_tokens=16000 -- ~68 output tokens of
# pattern JSON per fact if the response was near-complete when it got
# cut off (16000 / 234). vocabulary_system.md's own "COVERAGE PER
# PATTERN, NOT PER FACT" rule means several facts sharing one call shape
# can collapse into a single alternation pattern, pulling the true
# per-fact cost below that figure -- but a chunk whose facts don't group
# (the worst case a chunk-size default has to survive, same reasoning
# gapfill.py's own DEFAULT_CHUNK_SIZE comment uses) degrades to roughly
# one pattern per fact, at close to that observed ratio. 40 facts/chunk
# budgets ~40 * 68 =~ 2720 output tokens at that ratio -- well under the
# 16000 ceiling even if a chunk's real per-fact cost runs several times
# higher than the guide-average figure the one real truncation gives.
DEFAULT_CHUNK_SIZE = 40


def _chunks(facts, chunk_size):
    n = max(1, math.ceil(len(facts) / chunk_size))
    out = []
    for i in range(n):
        part = facts[i * chunk_size:(i + 1) * chunk_size]
        if part:
            out.append((i, part))
    return out


def _system_text(guide_text, factblock):
    """Everything that does NOT vary between chunks of the same
    derivation: the base vocabulary-derivation rules, the package name,
    and the full guide text. Built as the SYSTEM prompt, not folded into
    user_text, specifically so it sits in the cacheable prefix -- a
    chunk's own fact slice is the only thing that changes call to call,
    same split gapfill.py's _system_text uses for the same reason."""
    return (
        SYSTEM_PROMPT +
        f"\n\n---\n\nPrimary package: {factblock['package_name']}\n\n"
        f"ORIGINAL GUIDE TEXT (for reference/context only):\n{guide_text}"
    )


def _user_text(chunk_facts, idx, total_chunks):
    facts_text = factblock_stage.render_facts_text({"facts": chunk_facts})
    return (
        f"FACT BLOCK -- chunk {idx + 1} of {total_chunks} ({len(chunk_facts)} fact(s) in "
        f"this chunk). Derive patterns covering every breaking-change fact stated below, "
        f"per the rules above:\n\n{facts_text}"
    )


def _chunk_path(voc_dir, idx):
    return os.path.join(voc_dir, f"chunk_{idx:03d}.json")


def _chunk_is_done(voc_dir, idx):
    path = _chunk_path(voc_dir, idx)
    if not os.path.isfile(path):
        return False
    try:
        with open(path) as f:
            data = json.load(f)
        validate.validate_vocabulary_chunk(data, what=path)
    except (ValueError, json.JSONDecodeError):
        return False
    return True


def _merge_patterns(chunk_results):
    """Concatenates every chunk's patterns -- nothing dropped. Returns
    ({name: regex}, [(original_name, final_name), ...]) for the renamed
    ones.

    Every chunk is derived independently, with zero visibility into any
    other chunk's own choices, so two chunks coincidentally picking the
    same short id for two different symbols is an expected consequence
    of splitting one derivation into several calls, not a defect --
    renamed with a numeric suffix appended to the ORIGINAL id (never
    replaced wholesale), the same collision response gapfill.py's own
    _merge_patterns gives its cross-chunk case. Unlike gap-fill, there is
    no pre-existing vocabulary here to collide against and hard-fail on
    -- every chunk's output is equally "new," so every collision gets the
    same renumber-and-log treatment; an id colliding with nothing already
    merged is unchanged."""
    seen = set()
    merged = {}
    renamed = []
    for cr in chunk_results:
        for item in cr["patterns"]:
            name, regex = item["name"], item["regex"]
            final_name = name
            if final_name in seen:
                i = 2
                while f"{name}_{i}" in seen:
                    i += 1
                final_name = f"{name}_{i}"
                renamed.append((name, final_name))
            seen.add(final_name)
            merged[final_name] = regex
    return merged, renamed


def _cost_note(client, model):
    """Same best-effort, never-raises shape as factblock.py's own helper
    -- kept as its own copy rather than a cross-module import, same as
    gapfill.py's _estimate_tokens: a small private helper, not worth a
    cross-module reach for."""
    if model is None:
        return ""
    calls = getattr(client, "calls", None)
    if not calls:
        return ""
    last = calls[-1]
    if not isinstance(last, dict) or "usage" not in last:
        return ""
    cost = llm.estimate_cost(last["usage"], model)
    return f", ${cost:.4f}" if cost is not None else ""


def run(client, guide_text, factblock, workdir, chunk_size=DEFAULT_CHUNK_SIZE,
        model=None, cache_ttl="5m", print_fn=lambda *a, **k: None):
    """Returns the merged vocabulary dict: {"patterns": {name: regex}}.
    Writes workdir/vocabulary/chunk_NNN.json (one per chunk, idempotent
    -- a completed chunk is never re-derived on resume) and
    workdir/vocabulary/merged.json.

    `cache_ttl`: prompt-cache TTL for the (guide-text-embedding) system
    prompt -- see the cache_system gate just below for when caching is
    even attempted, same reasoning as adjudicate.run()/gapfill.run()."""
    voc_dir = os.path.join(workdir, "vocabulary")
    os.makedirs(voc_dir, exist_ok=True)

    facts = factblock["facts"]
    chunks = _chunks(facts, chunk_size)
    system_text = _system_text(guide_text, factblock)
    # A single chunk can never redeem its own cache write -- same gate
    # adjudicate.py/gapfill.py use. Cache anyway on a non-default TTL:
    # that's the signal the caller intends to redeem it from a LATER run.
    cache_system = len(chunks) > 1 or cache_ttl != "5m"

    for idx, chunk_facts in chunks:
        if _chunk_is_done(voc_dir, idx):
            continue
        user_text = _user_text(chunk_facts, idx, len(chunks))
        try:
            result = client.complete(
                stage=f"vocabulary_chunk_{idx:03d}",
                system_text=system_text,
                user_text=user_text,
                schema=SCHEMA,
                cache_system=cache_system,
                cache_ttl=cache_ttl,
                max_tokens=MAX_TOKENS,
                effort="high",
            )
        except llm.TruncatedResponseError as e:
            raise llm.TruncatedResponseError(
                f"{e} This chunk covers {len(chunk_facts)} fact(s) (vocabulary chunk "
                f"{idx + 1}/{len(chunks)}). Lower --vocabulary-chunk-size (currently "
                f"{chunk_size}) so it splits into smaller chunks instead of raising "
                f"max_tokens again -- vocabulary derivation's output scales with fact "
                f"count, so a bigger ceiling just moves the wall this chunking exists "
                f"to avoid."
            ) from e
        validate.validate_vocabulary_chunk(result, what=f"vocabulary chunk_{idx:03d}")

        path = _chunk_path(voc_dir, idx)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(result, f, indent=2)
        os.replace(tmp, path)

        print_fn(f"      chunk {idx + 1}/{len(chunks)}: {len(result['patterns'])} "
                  f"pattern(s){_cost_note(client, model)}")

    chunk_results = []
    for idx, _ in chunks:
        path = _chunk_path(voc_dir, idx)
        with open(path) as f:
            chunk_results.append(validate.validate_vocabulary_chunk(json.load(f), what=path))

    merged_patterns, renamed = _merge_patterns(chunk_results)
    merged = validate.validate_vocabulary({"patterns": merged_patterns}, what="merged vocabulary")

    merged_path = os.path.join(voc_dir, "merged.json")
    with open(merged_path, "w") as f:
        json.dump({"patterns": [{"name": n, "regex": r} for n, r in merged_patterns.items()]},
                   f, indent=2)

    if renamed:
        print_fn(f"      {len(renamed)} pattern id(s) renamed on merge (collided across "
                  f"chunks): {renamed}")

    return merged
