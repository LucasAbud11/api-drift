"""Chunked fact-block derivation. A large real guide (the MCP v1->v2
guide: 23k words, 116 `##` sections, 102 `###` subsections) cannot be
derived in one call -- it truncated at max_tokens=8000, then again at
max_tokens=32000. Raising max_tokens a third time is not the fix: the
fact block is input to every downstream call (vocabulary derivation,
every adjudication chunk), so a bigger fact block makes every one of
them more expensive, on every repo the guide is ever run against.

Chunked by guide structure instead, same idempotent-per-chunk-file design
adjudicate.py/fixgen.py already use: one `##` section is normally one
chunk; a section too large for the budget is split further on its own
`###` subheadings, never at an arbitrary offset, so a fact never straddles
a chunk boundary. A completed chunk is never re-derived on resume.
"""
import json
import os
import re

from .. import llm, validate

_PROMPT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")

with open(os.path.join(_PROMPT_DIR, "factblock_system.md")) as _f:
    SYSTEM_PROMPT = _f.read()

SCHEMA = {
    "type": "object",
    "properties": {
        "package_name": {"type": "string"},
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "number": {"type": "integer"},
                    "text": {"type": "string"},
                },
                "required": ["number", "text"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["package_name", "facts"],
    "additionalProperties": False,
}

# Approx. input-token budget per chunk (preamble + section text together --
# the preamble is prepended to every chunk, so it counts against every
# chunk's own budget, not just paid once). Deliberately conservative: a
# section's fact-derivation OUTPUT tends to run larger than its own guide
# text, so keeping input chunks well under the 32000-token max_tokens
# ceiling leaves real headroom for that expansion.
DEFAULT_CHUNK_SIZE = 6000

# `##`/`###` at the start of a line, not immediately followed by another
# `#` (so `## Heading` matches but `### Heading` does not match the `##`
# pattern, and `#### Heading`, if a guide ever has one, matches neither).
_H2_RE = re.compile(r"^##(?!#)[ \t]+(.*)$", re.MULTILINE)
_H3_RE = re.compile(r"^###(?!#)[ \t]+(.*)$", re.MULTILINE)


def _estimate_tokens(text):
    """A rough ~4-chars/token heuristic -- not a real tokenizer count.
    Good enough for chunk-planning and --dry-run cost-safety estimates,
    not for billing precision. The only ground truth for actual token
    counts is usage.input_tokens on a real API response."""
    return max(1, len(text) // 4)


def _split_with_preamble(text, heading_re):
    """Splits `text` at every `heading_re` match into whole sections --
    never at an arbitrary offset, so a fact can never straddle a
    boundary. Returns (preamble, sections); sections is [] if
    `heading_re` matches nothing, in which case preamble is all of
    `text`. Each section's own text starts at its heading line and runs
    to the next heading (or end of text) -- preamble + every section's
    text, concatenated in order, reconstructs `text` exactly."""
    matches = list(heading_re.finditer(text))
    if not matches:
        return text, []
    preamble = text[:matches[0].start()]
    sections = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append({"heading": m.group(1).strip(), "text": text[start:end]})
    return preamble, sections


def plan_chunks(guide_text, chunk_token_budget=DEFAULT_CHUNK_SIZE):
    """Returns (preamble, chunks): chunks is a list of {"heading", "text",
    "approx_tokens"} dicts in guide order. `approx_tokens` already
    includes the preamble's own token cost, since the preamble is
    prepended to every chunk's real user message.

    A `##` section that fits the budget (preamble included) is one
    chunk. One that doesn't is subdivided on its own `###` subheadings --
    still whole subsections, never an arbitrary offset cut. A `###`
    subsection that STILL doesn't fit is kept whole anyway (there is no
    smaller structural unit to split on) and reported honestly by the
    per-chunk max_tokens/truncation check in run(), rather than silently
    truncated further."""
    preamble, h2_sections = _split_with_preamble(guide_text, _H2_RE)
    preamble_tokens = _estimate_tokens(preamble) if preamble.strip() else 0

    if not h2_sections:
        return "", [{
            "heading": "(whole guide -- no `##` sections found)",
            "text": guide_text,
            "approx_tokens": preamble_tokens + _estimate_tokens(guide_text),
        }]

    chunks = []
    for sec in h2_sections:
        total = preamble_tokens + _estimate_tokens(sec["text"])
        if total <= chunk_token_budget:
            chunks.append({"heading": sec["heading"], "text": sec["text"], "approx_tokens": total})
            continue

        sub_preamble, h3_sections = _split_with_preamble(sec["text"], _H3_RE)
        if not h3_sections:
            chunks.append({"heading": sec["heading"], "text": sec["text"], "approx_tokens": total})
            continue
        for j, sub in enumerate(h3_sections):
            # The section's own intro prose before its first `###` (if
            # any) belongs to the first subsection chunk, not dropped.
            body = (sub_preamble + sub["text"]) if j == 0 else sub["text"]
            chunks.append({
                "heading": f"{sec['heading']} > {sub['heading']}",
                "text": body,
                "approx_tokens": preamble_tokens + _estimate_tokens(body),
            })
    return preamble, chunks


def _chunk_user_text(preamble, chunk, idx, total):
    parts = []
    if preamble.strip():
        parts.append(
            "GUIDE PREAMBLE (context only -- the guide's own introduction/scope note, "
            "shown for background. Do NOT derive facts from this preamble alone; only "
            "from the SECTION TEXT below):\n\n" + preamble.strip()
        )
    parts.append(
        f"SECTION TEXT (chunk {idx + 1} of {total} -- this is one section of a larger "
        f"guide, split for processing. Derive every fact stated in THIS section's "
        f"text):\n\n{chunk['text']}"
    )
    return "\n\n---\n\n".join(parts)


def _chunk_path(fb_dir, idx):
    return os.path.join(fb_dir, f"chunk_{idx:03d}.json")


def _chunk_is_done(fb_dir, idx):
    path = _chunk_path(fb_dir, idx)
    if not os.path.isfile(path):
        return False
    try:
        with open(path) as f:
            data = json.load(f)
        validate.validate_factblock_chunk(data, what=path)
    except (ValueError, json.JSONDecodeError):
        return False
    return True


def _consensus_package_name(chunk_results):
    """Most chunks will state either the same package name or none at
    all (a section that never mentions the import). If every non-empty
    answer across chunks agrees, that's the consensus. If two chunks
    give DIFFERENT non-empty bare identifiers, that's a real signal
    something is wrong -- a chunk misread the guide, or the guide
    genuinely discusses more than one package -- and gets hard-failed
    rather than silently resolved by majority vote."""
    non_empty = [r["package_name"] for r in chunk_results if r.get("package_name", "").strip()]
    distinct = sorted(set(non_empty))
    if len(distinct) > 1:
        extra = f" (and {len(distinct) - 2} more)" if len(distinct) > 2 else ""
        raise ValueError(
            f"fact-block chunks disagree on package_name: {distinct[0]!r} vs "
            f"{distinct[1]!r}{extra} -- this is a real signal something is wrong "
            f"(a chunk misread the guide, or the guide genuinely discusses more than "
            f"one package), not something to silently resolve by majority vote."
        )
    return distinct[0] if distinct else ""


def _merge_chunk_results(chunk_results):
    """Concatenates facts in guide order (chunk_results is already
    index-aligned with the chunk plan, which is itself guide-ordered) and
    renumbers globally -- facts are carried through verbatim, never
    paraphrased or rewritten. Flags exact-duplicate fact text (guides
    cross-reference themselves) in 'duplicate_facts' without dropping
    either copy -- losing a fact silently is exactly the failure mode
    this project exists to avoid."""
    package_name = _consensus_package_name(chunk_results)

    merged_facts = []
    next_number = 1
    for result in chunk_results:
        for fact in result["facts"]:
            merged_facts.append({"number": next_number, "text": fact["text"]})
            next_number += 1

    by_text = {}
    for fact in merged_facts:
        by_text.setdefault(fact["text"].strip(), []).append(fact["number"])
    duplicate_facts = [nums for nums in by_text.values() if len(nums) > 1]

    return {"package_name": package_name, "facts": merged_facts, "duplicate_facts": duplicate_facts}


def _cost_note(client, model):
    """Best-effort, never raises: only real AnthropicLLMClient.calls
    entries are {"stage", "usage"} dicts shaped for estimate_cost -- a
    fake/scripted test client's calls list (a list of stage strings, or
    dicts with different keys) safely yields no cost note instead of
    crashing the run."""
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


def run(client, guide_text, workdir, chunk_token_budget=DEFAULT_CHUNK_SIZE,
        model=None, print_fn=lambda *a, **k: None):
    """Returns the merged fact-block dict: {"package_name", "facts",
    "duplicate_facts"}. Writes workdir/factblock/chunk_NNN.json (one per
    chunk, idempotent -- a completed chunk is never re-derived on resume)
    and workdir/factblock/merged.json."""
    fb_dir = os.path.join(workdir, "factblock")
    os.makedirs(fb_dir, exist_ok=True)

    preamble, chunks = plan_chunks(guide_text, chunk_token_budget)

    for idx, chunk in enumerate(chunks):
        if _chunk_is_done(fb_dir, idx):
            continue
        user_text = _chunk_user_text(preamble, chunk, idx, len(chunks))
        try:
            result = client.complete(
                stage=f"factblock_chunk_{idx:03d}",
                system_text=SYSTEM_PROMPT,
                user_text=user_text,
                schema=SCHEMA,
                cache_system=True,
                max_tokens=32000,
                effort="high",
            )
        except llm.TruncatedResponseError as e:
            raise llm.TruncatedResponseError(
                f"{e} This chunk covers guide section {chunk['heading']!r} "
                f"(~{chunk['approx_tokens']} estimated input tokens). Stage 1 is "
                f"chunked by guide section specifically to avoid this -- a single "
                f"section still overflowing max_tokens=32000 means that ONE section "
                f"is unusually fact-dense. Lower --factblock-chunk-size so it splits "
                f"further (on its own `###` subheadings) instead of raising "
                f"max_tokens again."
            ) from e
        validate.validate_factblock_chunk(result, what=f"chunk_{idx:03d} ({chunk['heading']})")

        path = _chunk_path(fb_dir, idx)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(result, f, indent=2)
        os.replace(tmp, path)

        print_fn(f"      chunk {idx + 1}/{len(chunks)} ({chunk['heading']}): "
                  f"{len(result['facts'])} facts{_cost_note(client, model)}")

    chunk_results = []
    for idx in range(len(chunks)):
        path = _chunk_path(fb_dir, idx)
        with open(path) as f:
            chunk_results.append(validate.validate_factblock_chunk(json.load(f), what=path))

    merged = _merge_chunk_results(chunk_results)

    merged_path = os.path.join(fb_dir, "merged.json")
    with open(merged_path, "w") as f:
        json.dump(merged, f, indent=2)
    validate.validate_factblock(merged, what=merged_path)

    if merged["duplicate_facts"]:
        print_fn(f"      {len(merged['duplicate_facts'])} group(s) of exact-duplicate "
                  f"facts across chunks (kept, not dropped) -- see factblock.json's "
                  f"'duplicate_facts' field: {merged['duplicate_facts']}")

    return merged


def format_dry_run_report(guide_text, chunk_token_budget=DEFAULT_CHUNK_SIZE, model=None):
    """Pure, offline, makes no API call: the planned chunk list and an
    approximate cost estimate for --dry-run. Returns a list of lines to
    print. The cost estimate covers guide-content input tokens only --
    it excludes the fixed system prompt (small, and cached after the
    first chunk) and cannot include model output, which isn't knowable
    before a chunk actually runs."""
    _preamble, chunks = plan_chunks(guide_text, chunk_token_budget)
    lines = [f"DRY RUN -- {len(chunks)} planned fact-block chunk(s), no API calls made:"]
    total_tokens = 0
    for idx, chunk in enumerate(chunks):
        total_tokens += chunk["approx_tokens"]
        lines.append(f"  [{idx + 1}/{len(chunks)}] {chunk['heading']}  "
                      f"(~{chunk['approx_tokens']} input tokens)")
    lines.append("")
    lines.append(f"Estimated total input tokens: ~{total_tokens} (guide content only -- "
                  f"excludes the fixed system prompt and any model output, neither "
                  f"knowable here)")
    if model is not None:
        price = llm.PRICE_PER_MTOK.get(model)
        if price is not None:
            est = total_tokens / 1_000_000 * price["input_tokens"]
            lines.append(f"Estimated input-token cost: ~${est:.4f} (before prompt-cache "
                          f"discounts; actual cost also includes model output)")
        else:
            lines.append(f"No pricing data for model {model!r} -- cost not estimated.")
    return lines


def render_facts_text(factblock):
    """The exact text that fills {MIGRATION_FACTS} in the adjudication
    prompt -- one line per fact, numbered."""
    lines = []
    for fact in factblock["facts"]:
        lines.append(f"{fact['number']}. {fact['text']}")
    return "\n\n".join(lines)
