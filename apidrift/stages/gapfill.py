"""Gap-fill: chunked derivation for facts stage 2's vocabulary derivation
never wrote a pattern for. Confirmed on a real guide (the MCP v1->v2
migration guide, 819 facts): 269 of 320 searchable-but-uncovered
identifier spans are real, guide-stated API surface with zero token
overlap with any of the 115 derived patterns -- stage 2 never attempted
them, not a near-miss. `guards.compute_fact_pattern_coverage` already
computes, deterministically, exactly which facts have a searchable span
with no covering pattern; that computation is this stage's entire input.
It is handed the exact per-fact uncovered-span list, never asked to
re-derive what's missing.

Chunked by target-fact count, same idempotent-per-chunk-file design
adjudicate.py already uses: gap-fill's output is one pattern-or-decline
per target fact, the same "count of items in bounds output size" shape
adjudication has (unlike factblock's guide-section/token-budget
splitting) -- a single call over 323 target facts truncated at
max_tokens=16000, confirming output scales with target count. Raising
max_tokens is not the fix (it also risks crossing the SDK's non-
streaming request-duration ceiling, which is why llm.py streams every
call already); splitting the target set is.

One gap-fill PASS only -- no iteration yet. See build_targets/run for
the pre-filter and the chunked derivation; a future loop would recompute
coverage after this pass and repeat until it stops improving or a cap is
reached, but that isn't built here.
"""
import json
import os

from .. import guards, llm, validate
from . import vocabulary as vocabulary_stage

_PROMPT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")
with open(os.path.join(_PROMPT_DIR, "gapfill_addendum.md")) as _f:
    _ADDENDUM = _f.read()

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
        "declined": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "fact": {"type": "integer"},
                    "span": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["fact", "span", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["patterns", "declined"],
    "additionalProperties": False,
}

MAX_TOKENS = 16000

# Picked by anchoring to the two existing chunked stages' own item/token
# ratios, since neither is an exact match on its own:
#   - adjudicate.py: 40 candidates per chunk at max_tokens=8000 (~200
#     output tokens/item) for a SIMPLER per-item judgment -- one triage
#     verdict, no cross-referencing against 100+ existing patterns, no
#     multi-rule constraint checking.
#   - fixgen.py: 15 sites per chunk at max_tokens=8000 (~533 tokens/item)
#     for a HEAVIER per-item judgment -- a real line-level diff plus a
#     reason, closer in weight to what gap-fill's decline reasoning and
#     anti-Goodhart/qualification self-checking actually require.
# Gap-fill's max_tokens is double either (16000, kept from stage 2's own
# budget rather than lowered, since lowering it further would only
# shrink the wall this chunking is already meant to move). Scaling
# fixgen's heavier per-item ratio (chosen over adjudicate's lighter one,
# since gap-fill's per-fact judgment -- dedup against the existing
# vocabulary, the 3-branch alternation cap, the id-must-reference-the-
# symbol check, generic-noun qualification -- is closer to fixgen's
# weight than adjudicate's) to the doubled budget gives ~30 items/chunk.
# 323 target facts / 30 is 11 chunks -- more calls than a looser number
# would need, but correctness over call count: a chunk that's too small
# wastes a fraction of a cache-read; a chunk that's too large truncates
# and the whole chunk's work is lost.
DEFAULT_CHUNK_SIZE = 30


def _estimate_tokens(text):
    """Same rough ~4-chars/token heuristic as factblock.py's identically-
    named helper -- good enough for a --gapfill plan/cost estimate, not
    for billing precision. Kept as its own tiny copy rather than an
    import: stages/factblock.py's version is private (leading
    underscore) and this is a two-line function, not worth a cross-
    module reach for."""
    return max(1, len(text) // 4)


def build_targets(coverage_rows):
    """Returns {fact_number: {"text", "spans"}} for every fact whose
    status is "partial" or "uncovered" -- i.e. every fact left over
    after classify_span_searchability's structural pre-filter (bare
    Python builtins, package self-references, version specifiers, and
    the rest) has already excluded what no pattern could ever usefully
    cover. `spans` is the exact list of searchable, uncovered span texts
    guards.compute_fact_pattern_coverage already computed for that fact
    -- this is gap-fill's entire "here is the gap" signal; nothing here
    re-derives it."""
    targets = {}
    for row in coverage_rows:
        if row["status"] not in ("partial", "uncovered"):
            continue
        spans = [sr["span"] for sr in row["spans"] if sr["searchable"] and not sr["covering"]]
        if spans:
            targets[row["number"]] = {"text": row["text"], "spans": spans}
    return targets


def _render_targets_text(targets):
    lines = []
    for num in sorted(targets):
        t = targets[num]
        span_list = ", ".join(f"`{s}`" for s in t["spans"])
        lines.append(f"{num}. {t['text']}\n   UNCOVERED SPANS: {span_list}")
    return "\n\n".join(lines)


def _render_existing_vocabulary(vocabulary):
    lines = [f"{name}: {regex}" for name, regex in sorted(vocabulary["patterns"].items())]
    return "\n".join(lines) if lines else "(none)"


def plan_chunks(targets, chunk_size=DEFAULT_CHUNK_SIZE):
    """Slices `targets` into an ordered list of chunk dicts (each a
    {fact_number: {"text", "spans"}} sub-mapping of `targets`), at most
    `chunk_size` target facts each, sorted by fact number for
    determinism. Mirrors adjudicate.py's _chunks -- gap-fill's output is
    one pattern-or-decline per target fact, the same "N items in, N
    verdicts out" shape adjudication has, not factblock's token-budget-
    driven guide-section splitting."""
    numbers = sorted(targets)
    return [
        {n: targets[n] for n in numbers[i:i + chunk_size]}
        for i in range(0, len(numbers), chunk_size)
    ]


def _system_text(guide_text, factblock, vocabulary):
    """Everything that does NOT vary between chunks of the same gap-fill
    pass: the base vocabulary-derivation rules, the gap-fill addendum
    (with the existing vocabulary rendered into it), the package name,
    and the full guide text. Deliberately built as the SYSTEM prompt,
    not folded into user_text, specifically so it sits in the cacheable
    prefix -- llm.py's cache_system caches the whole system block, and a
    chunk's own varying target-fact slice is the only thing that
    changes call to call within one pass, so this ordering is what
    makes a cache write from chunk 0 actually redeemable by chunk 1
    onward."""
    addendum = _ADDENDUM.replace("{EXISTING_VOCABULARY}", _render_existing_vocabulary(vocabulary))
    return (
        vocabulary_stage.SYSTEM_PROMPT + "\n\n---\n\n" + addendum +
        f"\n\n---\n\nPrimary package: {factblock['package_name']}\n\n"
        f"ORIGINAL GUIDE TEXT (for reference/context only):\n{guide_text}"
    )


def _user_text(chunk_targets, idx, total_chunks):
    return (
        f"TARGET FACTS -- chunk {idx + 1} of {total_chunks} ({len(chunk_targets)} fact(s) "
        f"in this chunk), each with the exact identifier spans a deterministic coverage "
        f"check found no covering pattern for:\n\n"
        f"{_render_targets_text(chunk_targets)}"
    )


def estimate_cost_report(guide_text, vocabulary, factblock, targets,
                          chunk_size=DEFAULT_CHUNK_SIZE, model=None):
    """Pure, offline -- makes no API call. Reports the planned chunk
    list and, when `model` is given, a cost estimate that accounts for
    prompt caching across chunks: the shared prefix (base rules +
    addendum + existing vocabulary + package name + guide text) is
    identical every chunk and sits entirely in system_text, so it's
    paid once at cache-write price and read back at the much cheaper
    cache-read price by every chunk after the first. Never includes
    model output/thinking -- neither is knowable before a chunk
    actually runs. Used both for --dry-run (with a loaded factblock and
    vocabulary, no client needed) and for the confirmation plan
    pipeline.run prints before a real --gapfill call."""
    chunks = plan_chunks(targets, chunk_size)
    shared_tokens = (
        _estimate_tokens(vocabulary_stage.SYSTEM_PROMPT)
        + _estimate_tokens(_ADDENDUM)
        + _estimate_tokens(_render_existing_vocabulary(vocabulary))
        + _estimate_tokens(guide_text)
    )

    lines = [
        f"GAP-FILL PLAN -- {len(targets)} target fact(s), {len(chunks)} planned chunk(s) "
        f"of up to {chunk_size} each, no API calls made yet:",
    ]
    varying_total = 0
    for idx, chunk_targets in enumerate(chunks):
        chunk_tokens = _estimate_tokens(_render_targets_text(chunk_targets))
        varying_total += chunk_tokens
        lines.append(f"  [{idx + 1}/{len(chunks)}] {len(chunk_targets)} target fact(s)  "
                      f"(~{chunk_tokens} varying input tokens)")
    lines.append(f"  shared/cacheable prefix: ~{shared_tokens} tokens (base rules + "
                  f"gap-fill addendum + existing vocabulary + guide text -- identical "
                  f"every chunk; paid once at cache-write price, read back at cache-read "
                  f"price by every later chunk)")
    lines.append(f"  varying per-chunk input, summed: ~{varying_total} tokens")

    if model is not None:
        price = llm.PRICE_PER_MTOK.get(model)
        if price is None:
            lines.append(f"  no pricing data for model {model!r} -- cost not estimated")
        elif not chunks:
            lines.append("  0 chunks planned -- nothing to cost.")
        else:
            cache_write_cost = shared_tokens / 1_000_000 * price["cache_creation_input_tokens"]
            cache_read_cost = (
                shared_tokens * (len(chunks) - 1) / 1_000_000 * price["cache_read_input_tokens"]
            )
            varying_cost = varying_total / 1_000_000 * price["input_tokens"]
            est = cache_write_cost + cache_read_cost + varying_cost
            lines.append(f"  estimated input-token cost: ~${est:.4f} (1 cache write + "
                          f"{max(len(chunks) - 1, 0)} cache read(s) of the shared prefix, "
                          f"plus each chunk's own varying input at full price; excludes "
                          f"model output/thinking)")
    return lines


def _chunk_dir(workdir):
    return os.path.join(workdir, "gapfill")


def _chunk_path(gf_dir, idx):
    return os.path.join(gf_dir, f"chunk_{idx:03d}.json")


def _chunk_is_done(gf_dir, idx):
    path = _chunk_path(gf_dir, idx)
    if not os.path.isfile(path):
        return False
    try:
        with open(path) as f:
            data = json.load(f)
        validate.validate_gapfill_dict(data, what=path)
    except (ValueError, json.JSONDecodeError):
        return False
    return True


def _merge_patterns(chunk_results, existing_pattern_ids):
    """Concatenates every chunk's patterns -- nothing dropped. Returns
    ({name: regex}, [(original_name, final_name), ...]) for the renamed
    ones.

    Two different collision cases, two different responses:
    - A pattern id equal to one already in the PRE-EXISTING vocabulary
      is a hard failure, unchanged from the single-call design: ids
      must stay unique across the merged vocabulary, and a gap-fill
      chunk naming something after a pattern that was already there
      before gap-fill ran is a real, more concerning signal, not a
      structural artifact of chunking.
    - A pattern id colliding with another GAP-FILL CHUNK's own new
      pattern is not a defect -- each chunk is derived independently,
      with zero visibility into what id any other chunk picked, so two
      chunks coincidentally choosing the same short abbreviation is an
      expected consequence of splitting one derivation into several
      calls. Renamed with a numeric suffix appended to the ORIGINAL id
      (never replaced wholesale), so the "id must reference its own
      regex" property validate_gapfill_dict already checked per-chunk
      still holds after the rename -- the suffix doesn't erase the
      original content the check matched against."""
    existing = set(existing_pattern_ids)
    seen_new = set()
    merged = {}
    renamed = []
    for cr in chunk_results:
        for item in cr["patterns"]:
            name, regex = item["name"], item["regex"]
            if name in existing:
                raise ValueError(
                    f"gap-fill pattern id '{name}' collides with an existing vocabulary "
                    f"pattern id -- ids must stay unique across the merged vocabulary, "
                    f"same as validate_vocabulary already requires within a single "
                    f"derivation. (A collision between two gap-fill CHUNKS' own new "
                    f"patterns is renumbered automatically, not failed -- this is a "
                    f"different case: the model named something after a pattern that was "
                    f"already there before gap-fill ran.)"
                )
            final_name = name
            if final_name in seen_new:
                i = 2
                while f"{name}_{i}" in seen_new or f"{name}_{i}" in existing:
                    i += 1
                final_name = f"{name}_{i}"
                renamed.append((name, final_name))
            seen_new.add(final_name)
            merged[final_name] = regex
    return merged, renamed


def _merge_declined(chunk_results):
    declined = []
    for cr in chunk_results:
        declined.extend(cr["declined"])
    return declined


def run(client, guide_text, factblock, vocabulary, coverage_rows, workdir,
        chunk_size=DEFAULT_CHUNK_SIZE, cache_ttl="5m"):
    """Runs this gap-fill pass's chunks (idempotent: a completed chunk
    file is never re-derived on resume, same per-chunk-file convention
    adjudicate.py/factblock.py already use -- a failure partway through
    costs exactly the chunks that hadn't finished, not the whole pass).
    Returns (merged_vocabulary, gapfill_report, new_coverage_rows):

    - merged_vocabulary: `vocabulary` with every chunk's new patterns
      added (a fresh dict; `vocabulary` itself is never mutated). See
      _merge_patterns for the two different collision responses.
    - gapfill_report: {"target_fact_count", "chunk_count", "new_patterns",
      "renamed_on_merge", "declined", "unresolved", "anti_goodhart_warnings"}.
      "unresolved" is every target (fact, span) pair no chunk either
      covered or explicitly declined -- distinct from "declined" (an
      explicit, reasoned no) and expected to be nonzero on a real large
      guide after one pass; a future loop would retry exactly this set.
      "anti_goodhart_warnings" is every pattern either of
      validate_gapfill_dict's two anti-Goodhart checks (the distinct-
      symbol cap, the id-reads-as-an-abbreviation check) flagged --
      non-fatal for both (see validate.py's
      _validate_gapfill_pattern_anti_goodhart), still merged in, worth a
      human glancing at: both checks' real-world false-positive rate on
      valid patterns has been high enough that neither blocks a run
      anymore, but the signal is still often right.
    - new_coverage_rows: guards.compute_fact_pattern_coverage recomputed
      against merged_vocabulary, so a caller doesn't have to recompute
      it a third time.

    Callers are expected to have already shown a cost estimate (see
    estimate_cost_report) and gotten an explicit go-ahead before calling
    this -- this function itself always makes every not-yet-completed
    chunk's call. `build_targets(coverage_rows)` returning {} means
    there is nothing to do; callers should check that before calling
    run() at all (plan_chunks on an empty target set returns zero
    chunks, so this function degrades to a no-op merge either way, but
    the cost estimate has nothing to show)."""
    targets = build_targets(coverage_rows)
    gf_dir = _chunk_dir(workdir)
    os.makedirs(gf_dir, exist_ok=True)

    chunks = plan_chunks(targets, chunk_size)
    system_text = _system_text(guide_text, factblock, vocabulary)
    # A single chunk can never redeem its own cache write -- same gate
    # adjudicate.py uses. Cache anyway on a non-default TTL: that's the
    # signal the caller intends to redeem it from a LATER run.
    cache_system = len(chunks) > 1 or cache_ttl != "5m"

    for idx, chunk_targets in enumerate(chunks):
        if _chunk_is_done(gf_dir, idx):
            continue
        try:
            result = client.complete(
                stage=f"gapfill_chunk_{idx:03d}",
                system_text=system_text,
                user_text=_user_text(chunk_targets, idx, len(chunks)),
                schema=SCHEMA,
                cache_system=cache_system,
                cache_ttl=cache_ttl,
                max_tokens=MAX_TOKENS,
                effort="high",
            )
        except llm.TruncatedResponseError as e:
            raise llm.TruncatedResponseError(
                f"{e} This chunk covers {len(chunk_targets)} target fact(s) (gap-fill "
                f"chunk {idx + 1}/{len(chunks)}). Lower --gapfill-chunk-size (currently "
                f"{chunk_size}) so it splits into smaller chunks instead of raising "
                f"max_tokens again -- gap-fill's output scales with target fact count, so "
                f"a bigger ceiling just moves the wall this chunking exists to avoid."
            ) from e
        validate.validate_gapfill_dict(result, what=f"gapfill chunk_{idx:03d}")

        path = _chunk_path(gf_dir, idx)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(result, f, indent=2)
        os.replace(tmp, path)

    chunk_results = []
    anti_goodhart_warnings = []
    for idx in range(len(chunks)):
        path = _chunk_path(gf_dir, idx)
        with open(path) as f:
            chunk_results.append(
                validate.validate_gapfill_dict(json.load(f), what=path, warnings=anti_goodhart_warnings)
            )

    new_patterns, renamed = _merge_patterns(chunk_results, vocabulary["patterns"].keys())
    declined = _merge_declined(chunk_results)

    merged_patterns = dict(vocabulary["patterns"])
    merged_patterns.update(new_patterns)
    merged_vocabulary = dict(vocabulary)
    merged_vocabulary["patterns"] = merged_patterns
    validate.validate_vocabulary(merged_vocabulary, what="merged (post-gapfill) vocabulary")

    merged_path = os.path.join(gf_dir, "merged.json")
    with open(merged_path, "w") as f:
        json.dump(
            {"patterns": [{"name": n, "regex": r} for n, r in new_patterns.items()],
             "declined": declined},
            f, indent=2,
        )

    new_coverage_rows = guards.compute_fact_pattern_coverage(factblock, merged_vocabulary)

    declined_pairs = {(d["fact"], d["span"]) for d in declined}
    unresolved = []
    for row in new_coverage_rows:
        if row["number"] not in targets:
            continue
        for sr in row["spans"]:
            if sr["searchable"] and not sr["covering"] and (row["number"], sr["span"]) not in declined_pairs:
                unresolved.append({"fact": row["number"], "span": sr["span"]})

    gapfill_report = {
        "target_fact_count": len(targets),
        "chunk_count": len(chunks),
        "new_patterns": sorted(new_patterns),
        "renamed_on_merge": [{"from": a, "to": b} for a, b in renamed],
        "declined": declined,
        "unresolved": unresolved,
        "anti_goodhart_warnings": anti_goodhart_warnings,
    }
    with open(os.path.join(gf_dir, "report.json"), "w") as f:
        json.dump(gapfill_report, f, indent=2)

    return merged_vocabulary, gapfill_report, new_coverage_rows
