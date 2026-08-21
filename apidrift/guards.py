"""The two runtime guards from the fact-block experiment's one open gap:
derivation is validated when the guide states its facts clearly, but a
vague/incomplete guide, or a vocabulary that overshoots, was never tested.
Both guards stop the run (nonzero) unless --force, and both print the full
derived artifact plus the numbers that triggered the stop -- never just a
verdict.
"""
import re
from dataclasses import dataclass, field

from . import validate


@dataclass
class GuardResult:
    ok: bool
    reason: str = ""
    report: str = ""


_CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")


def _code_spans(text):
    return {m.group(1).strip() for m in _CODE_SPAN_RE.finditer(text) if m.group(1).strip()}


def check_factblock_coverage(guide_text, factblock, min_ratio=0.30):
    """Compares distinct backtick-delimited symbols named in the guide
    against distinct symbols named across the derived facts. A thin
    fact block -- one that named far fewer of the guide's own symbols
    than the guide itself names -- is the signature of a vague/badly
    written guide the derivation step couldn't get real facts out of, or
    a derivation that gave up early. Either way: stop, don't guess."""
    guide_spans = _code_spans(guide_text)
    fact_text = " ".join(f.get("text", "") for f in factblock.get("facts", []))
    fact_spans = _code_spans(fact_text)

    n_facts = len(factblock.get("facts", []))
    matched = guide_spans & fact_spans
    ratio = (len(matched) / len(guide_spans)) if guide_spans else 1.0

    report_lines = [
        "FACT-BLOCK COVERAGE CHECK",
        f"  guide distinct code-spans:        {len(guide_spans)}",
        f"  fact-block distinct code-spans:   {len(fact_spans)}",
        f"  overlap (spans named in both):    {len(matched)}",
        f"  coverage ratio:                   {ratio:.0%} (floor: {min_ratio:.0%})",
        f"  facts derived:                    {n_facts}",
        "",
        "  Derived fact block:",
    ]
    for f in factblock.get("facts", []):
        report_lines.append(f"    {f.get('number')}. {f.get('text')}")
    if guide_spans - matched:
        report_lines.append("")
        report_lines.append("  Guide symbols never named in any derived fact:")
        for s in sorted(guide_spans - matched):
            report_lines.append(f"    `{s}`")
    report = "\n".join(report_lines)

    if n_facts == 0:
        return GuardResult(False, "zero facts derived from a non-trivial guide", report)
    if guide_spans and ratio < min_ratio:
        return GuardResult(
            False,
            f"fact-block coverage ratio {ratio:.0%} is below the {min_ratio:.0%} floor -- "
            f"the guide names {len(guide_spans)} distinct symbols but the derived facts "
            f"only cover {len(matched)} of them",
            report,
        )
    return GuardResult(True, "", report)


def check_vocabulary_yield(patterns, candidates, max_total=2000,
                            max_single_pattern_share=0.35, max_single_pattern_floor=25):
    """Runs after grep. Flags either an absolute candidate-count ceiling
    (matches the volume where the study measured real completion
    failures) or one pattern alone accounting for most of the candidate
    set (the exact failure shape found in blind_vocab_experiment: a bare
    generic identifier like `data=` or `.error(` swamping everything a
    guide-faithful vocabulary was never trying to overmatch).

    max_single_pattern_floor was 100, max_single_pattern_share was 0.5 --
    both sized to the study's diluted-host worst case (1121 total
    candidates). At the scale of a normal single-repo run (tens to a few
    hundred raw candidates), a floor that high means the guard can never
    fire no matter how lopsided the vocabulary is: it just proved this on
    a real run (tasktiger/redis) where one bare, unqualified pattern took
    56/143 candidates (39%) -- exactly the failure shape this guard
    exists to catch -- and passed silently because 56 < 100. 25/0.35 is
    low enough to catch that at normal-repo scale, while still tolerating
    a legitimately dominant pattern in a genuinely small candidate set
    (e.g. a package's own constructor call at 6/10) without a false
    alarm."""
    per_pattern = {name: 0 for name in patterns}
    for c in candidates:
        name = c.get("_pattern")
        if name in per_pattern:
            per_pattern[name] += 1

    total = len(candidates)
    report_lines = [
        "VOCABULARY YIELD CHECK",
        f"  total candidates:  {total} (ceiling: {max_total})",
        "  per-pattern breakdown:",
    ]
    for name, count in sorted(per_pattern.items(), key=lambda kv: -kv[1]):
        report_lines.append(f"    {count:6d}  {name}  =  {patterns[name]}")
    report = "\n".join(report_lines)

    if total > max_total:
        return GuardResult(
            False, f"{total} candidates exceeds the {max_total} ceiling", report,
        )

    if total > 0:
        worst_name, worst_count = max(per_pattern.items(), key=lambda kv: kv[1])
        if worst_count >= max_single_pattern_floor and worst_count / total >= max_single_pattern_share:
            return GuardResult(
                False,
                f"pattern '{worst_name}' alone accounts for {worst_count}/{total} "
                f"candidates ({worst_count/total:.0%}) -- looks overly generic relative "
                f"to what the guide actually described",
                report,
            )
    return GuardResult(True, "", report)


_LITERAL_VALUE_SPANS = {"none", "true", "false", "self", "cls"}

# Phrases the fact-block deriver consistently uses (per factblock_system.md's
# own instruction to capture explicit non-scope statements) to mark a fact
# as deliberately NOT breaking -- e.g. "CONFIRMED UNCHANGED: `.add_tool(...)`
# is unchanged in v2." vocabulary_system.md's own first rule tells the
# deriver NOT to write a pattern for these; requiring pattern coverage for
# them would be flagging correct, intentional behavior as a gap. Heuristic,
# same spirit as the rest of this guard -- not a structured field.
_NON_BREAKING_MARKERS = (
    "out of scope", "not a breaking change", "confirmed unchanged",
    "not breaking", "unaffected by", "does not change", "no change needed",
)


def _is_non_breaking_fact(text):
    lowered = text.lower()
    return any(marker in lowered for marker in _NON_BREAKING_MARKERS)


def _fact_identifier_spans(fact_text):
    """Backtick-quoted spans in one fact's text, each split into its
    alnum/underscore tokens (dots, spaces, punctuation as separators),
    lowercased -- e.g. `TS.GET` -> ["ts", "get"], `legacy_responses` ->
    ["legacy_responses"]. One (span, tokens) pair per backtick span.

    Skips a span that opens with `[`, `(`, or `{`: that shape is how facts
    illustrate an abstract old-vs-new response VALUE (`[(member, score)]`,
    `(key, value)`, `{stream: entries}`) -- placeholder words like
    `member`/`score`/`stream` describing shape, not real code identifiers
    a pattern could ever be expected to search for. A real symbol/command/
    call span always opens with a letter or underscore (`TS.GET`,
    `redis.Redis(...)`, `age-seconds`). Also skips a bare Python literal
    keyword (`None`, `True`) used the same illustrative way (fact 61:
    "changed from `[None]` to `None`")."""
    out = []
    for span in _code_spans(fact_text):
        if span[:1] in "([{" or span.strip().lower() in _LITERAL_VALUE_SPANS:
            continue
        tokens = [t.lower() for t in re.split(r"[^A-Za-z0-9_]+", span) if len(t) >= 2]
        out.append((span, tokens))
    return out


def _pattern_tokens(regex):
    """A pattern's own regex source, split into alnum/underscore 'words'
    the same way a fact span is, each paired with its underscore-stripped
    form. Needed because a guide names a wire command with spaces or no
    separator at all (`CLIENT TRACKINGINFO`, `MEMORY STATS`) while the
    Python client's real method name inserts underscores in different
    places (`client_tracking_info`, `memory_stats`) -- and Python's `\\b`
    treats `_` as a word character, so a literal `\\b`-bounded match
    between the two spellings never fires even though they plainly name
    the same thing. Stripping underscores from both sides before a plain
    substring check sidesteps that mismatch entirely. Lowercased for the
    same reason `_fact_identifier_spans` lowercases its tokens -- a guide
    span and a pattern's identifier casing need not agree (`redis.Redis`
    vs. a fact naming it `redis`) for this to plausibly be the same
    symbol."""
    words = [w.lower() for w in re.split(r"[^A-Za-z0-9_]+", regex) if len(w) >= 2]
    return [(w, w.replace("_", "")) for w in words]


def _token_covers(token, pattern_word_pairs):
    token_stripped = token.replace("_", "")
    return any(
        token_stripped in stripped or stripped in token_stripped
        for _, stripped in pattern_word_pairs
    )


def check_vocabulary_coverage(factblock, vocabulary):
    """Runs right after vocabulary derivation, before grep. The last
    unchecked link in the coverage chain: check_factblock_coverage already
    guards guide -> factblock; this guards factblock -> vocabulary. Exists
    because vocabulary derivation is demonstrably non-deterministic call to
    call (observed directly: the same fact block, re-derived, silently
    dropped a keyword-argument pattern present in an earlier derivation,
    with zero signal anywhere in the pipeline) -- a fact naming a concrete
    identifier can lose its pattern between one run and the next with
    nothing today to notice.

    For every fact that names at least one backtick-quoted identifier,
    checks whether ANY derived pattern's own regex source plausibly
    represents EACH such identifier -- an underscore-insensitive substring
    test against the pattern text itself (there's no sample code yet to
    actually run the regex against; this is the same "text overlap as a
    proxy for coverage" approach check_factblock_coverage already uses,
    one level further down the chain). For a dotted command name
    (`TS.GET`), a generic segment (`get`) is not required to individually
    match if a more distinctive segment (`ts`) already does -- coverage
    for the trailing generic word is exactly what validate_vocabulary's
    breadth check now forces to route through a namespace qualifier
    instead of appearing standalone.

    A fact naming zero concrete identifiers (pure checklist/process prose,
    e.g. "roll the change out gradually") has nothing a syntactic pattern
    could represent -- excluded from the pass/fail requirement, reported
    separately rather than miscounted as a real gap."""
    patterns = vocabulary.get("patterns", {})
    pattern_words = {name: _pattern_tokens(regex) for name, regex in patterns.items()}

    rows = []
    any_gap = False

    for fact in factblock.get("facts", []):
        num = fact.get("number")
        text = fact.get("text", "")
        if _is_non_breaking_fact(text):
            rows.append({"number": num, "text": text, "status": "non_breaking"})
            continue
        id_spans = _fact_identifier_spans(text)
        if not id_spans:
            rows.append({"number": num, "text": text, "status": "no_identifier"})
            continue

        span_rows = []
        fact_gap = False
        for span, tokens in id_spans:
            distinctive = [t for t in tokens if t not in validate.GENERIC_METHOD_NAMES] or tokens
            covering = {
                name for tok in distinctive
                for name, words in pattern_words.items()
                if _token_covers(tok, words)
            }
            if not covering:
                fact_gap = True
            span_rows.append({"span": span, "covering": sorted(covering)})

        status = "uncovered" if all(not r["covering"] for r in span_rows) else (
            "partial" if fact_gap else "covered"
        )
        if fact_gap:
            any_gap = True
        rows.append({"number": num, "text": text, "status": status, "spans": span_rows})

    report_lines = ["VOCABULARY COVERAGE CHECK (fact block -> derived vocabulary)", ""]
    gap_facts = []
    for row in rows:
        if row["status"] == "no_identifier":
            report_lines.append(f"  [{row['number']:>3}] (no concrete identifier stated) {row['text'][:90]}")
            continue
        if row["status"] == "non_breaking":
            report_lines.append(f"  [{row['number']:>3}] (explicitly non-breaking -- no pattern expected) {row['text'][:90]}")
            continue
        report_lines.append(f"  [{row['number']:>3}] {row['status'].upper()}: {row['text'][:90]}")
        for sr in row["spans"]:
            covering = ", ".join(sr["covering"]) if sr["covering"] else "*** MISSING -- no pattern references it ***"
            report_lines.append(f"        `{sr['span']}` -> {covering}")
        if row["status"] != "covered":
            gap_facts.append(row["number"])
    report = "\n".join(report_lines)

    if any_gap:
        return GuardResult(
            False,
            f"{len(gap_facts)} fact(s) name a concrete identifier with no derived pattern "
            f"covering it: facts {gap_facts}",
            report,
        )
    return GuardResult(True, "", report)
