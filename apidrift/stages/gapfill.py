"""Gap-fill: one scoped derivation pass for facts stage 2's vocabulary
derivation never wrote a pattern for. Confirmed on a real guide (the MCP
v1->v2 migration guide, 819 facts): 269 of 320 searchable-but-uncovered
identifier spans are real, guide-stated API surface with zero token
overlap with any of the 115 derived patterns -- stage 2 never attempted
them, not a near-miss. `guards.compute_fact_pattern_coverage` already
computes, deterministically, exactly which facts have a searchable span
with no covering pattern; that computation is this stage's entire input.
It is handed the exact per-fact uncovered-span list, never asked to
re-derive what's missing.

One pass only -- no iteration yet. See build_targets/run for the
pre-filter and the single derivation call; a future loop would recompute
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


def _system_text(vocabulary):
    addendum = _ADDENDUM.replace("{EXISTING_VOCABULARY}", _render_existing_vocabulary(vocabulary))
    return vocabulary_stage.SYSTEM_PROMPT + "\n\n---\n\n" + addendum


def _user_text(guide_text, factblock, targets):
    return (
        f"Primary package: {factblock['package_name']}\n\n"
        f"TARGET FACTS ({len(targets)}) -- each with the exact identifier spans a "
        f"deterministic coverage check found no covering pattern for:\n\n"
        f"{_render_targets_text(targets)}\n\n"
        f"ORIGINAL GUIDE TEXT (for reference/context only):\n{guide_text}"
    )


def estimate_cost_report(guide_text, vocabulary, factblock, targets, model=None):
    """Pure, offline -- makes no API call. Same scope-limited honesty as
    factblock.format_dry_run_report: input tokens only (guide text,
    existing vocabulary, target facts' own text, the addendum prompt),
    never model output or thinking, neither knowable before the call
    actually runs. Returns a list of lines to print."""
    guide_tokens = _estimate_tokens(guide_text)
    vocab_tokens = _estimate_tokens(_render_existing_vocabulary(vocabulary))
    targets_tokens = _estimate_tokens(_render_targets_text(targets))
    addendum_tokens = _estimate_tokens(_ADDENDUM)
    total = guide_tokens + vocab_tokens + targets_tokens + addendum_tokens

    lines = [
        f"GAP-FILL PLAN -- {len(targets)} target fact(s), no API call made yet:",
        f"  guide text:            ~{guide_tokens} tokens",
        f"  existing vocabulary:   ~{vocab_tokens} tokens ({len(vocabulary['patterns'])} patterns)",
        f"  target facts:          ~{targets_tokens} tokens",
        f"  gap-fill addendum:     ~{addendum_tokens} tokens",
        f"  estimated total input: ~{total} tokens (excludes the base vocabulary_system.md "
        f"prompt -- identical text to stage 2's own system prompt, so cacheable -- and "
        f"model output/thinking, neither knowable before the call runs)",
    ]
    if model is not None:
        price = llm.PRICE_PER_MTOK.get(model)
        if price is not None:
            est = total / 1_000_000 * price["input_tokens"]
            lines.append(f"  estimated input-token cost: ~${est:.4f} (before prompt-cache "
                          f"discounts; actual cost also includes model output)")
        else:
            lines.append(f"  no pricing data for model {model!r} -- cost not estimated")
    return lines


def _gapfill_dir(workdir):
    return os.path.join(workdir, "gapfill")


def _pass_path(gf_dir, idx):
    return os.path.join(gf_dir, f"pass_{idx:03d}.json")


def _pass_is_done(gf_dir, idx):
    path = _pass_path(gf_dir, idx)
    if not os.path.isfile(path):
        return False
    try:
        with open(path) as f:
            data = json.load(f)
        validate.validate_gapfill_dict(data, what=path)
    except (ValueError, json.JSONDecodeError):
        return False
    return True


def run(client, guide_text, factblock, vocabulary, coverage_rows, workdir, cache_ttl="5m"):
    """Runs exactly one gap-fill pass (idempotent: a completed pass file
    is never re-derived on resume, same per-chunk-file convention
    adjudicate.py/factblock.py already use). Returns
    (merged_vocabulary, gapfill_report, new_coverage_rows):

    - merged_vocabulary: `vocabulary` with this pass's new patterns added
      (a fresh dict; `vocabulary` itself is never mutated). Collision
      with an existing pattern id is a hard failure, not a silent
      rename -- ids must stay unique across the merged vocabulary the
      same way validate_vocabulary already requires within one
      derivation.
    - gapfill_report: {"target_fact_count", "new_patterns", "declined",
      "unresolved"}. "unresolved" is every target (fact, span) pair this
      pass neither covered nor explicitly declined -- distinct from
      "declined" (an explicit, reasoned no) and expected to be nonzero
      on a real large guide after a single pass; a future loop would
      retry exactly this set.
    - new_coverage_rows: guards.compute_fact_pattern_coverage recomputed
      against merged_vocabulary, so a caller doesn't have to recompute
      it a third time.

    Callers are expected to have already shown the caller a cost
    estimate (see estimate_cost_report) and gotten an explicit
    go-ahead before calling this -- this function itself always makes
    the call (once, for the one pass it runs) if there's no completed
    pass file yet. `build_targets(coverage_rows)` returning {} means
    there is nothing to do; callers should check that before calling
    run() at all."""
    targets = build_targets(coverage_rows)
    gf_dir = _gapfill_dir(workdir)
    os.makedirs(gf_dir, exist_ok=True)

    idx = 0
    if _pass_is_done(gf_dir, idx):
        with open(_pass_path(gf_dir, idx)) as f:
            result = json.load(f)
    else:
        result = client.complete(
            stage=f"gapfill_pass_{idx:03d}",
            system_text=_system_text(vocabulary),
            user_text=_user_text(guide_text, factblock, targets),
            schema=SCHEMA,
            cache_system=True,
            cache_ttl=cache_ttl,
            max_tokens=MAX_TOKENS,
            effort="high",
        )
        validate.validate_gapfill_dict(result, what=f"gapfill pass {idx}")
        path = _pass_path(gf_dir, idx)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(result, f, indent=2)
        os.replace(tmp, path)

    new_patterns = {}
    for item in result["patterns"]:
        name, regex = item["name"], item["regex"]
        if name in vocabulary["patterns"] or name in new_patterns:
            raise ValueError(
                f"gap-fill pattern id '{name}' collides with an existing vocabulary "
                f"pattern id -- ids must stay unique across the merged vocabulary, same "
                f"as validate_vocabulary already requires within a single derivation"
            )
        new_patterns[name] = regex

    merged_patterns = dict(vocabulary["patterns"])
    merged_patterns.update(new_patterns)
    merged_vocabulary = dict(vocabulary)
    merged_vocabulary["patterns"] = merged_patterns
    validate.validate_vocabulary(merged_vocabulary, what="merged (post-gapfill) vocabulary")

    new_coverage_rows = guards.compute_fact_pattern_coverage(factblock, merged_vocabulary)

    declined_pairs = {(d["fact"], d["span"]) for d in result["declined"]}
    unresolved = []
    for row in new_coverage_rows:
        if row["number"] not in targets:
            continue
        for sr in row["spans"]:
            if sr["searchable"] and not sr["covering"] and (row["number"], sr["span"]) not in declined_pairs:
                unresolved.append({"fact": row["number"], "span": sr["span"]})

    gapfill_report = {
        "target_fact_count": len(targets),
        "new_patterns": sorted(new_patterns),
        "declined": result["declined"],
        "unresolved": unresolved,
    }
    with open(os.path.join(gf_dir, "report.json"), "w") as f:
        json.dump(gapfill_report, f, indent=2)

    return merged_vocabulary, gapfill_report, new_coverage_rows
