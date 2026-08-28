"""The two runtime guards from the fact-block experiment's one open gap:
derivation is validated when the guide states its facts clearly, but a
vague/incomplete guide, or a vocabulary that overshoots, was never tested.
Both guards stop the run (nonzero) unless --force, and both print the full
derived artifact plus the numbers that triggered the stop -- never just a
verdict.
"""
import builtins
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


# A backslash-escape sequence in a regex source string carries no literal
# text of its own -- `\b`/`\B` are zero-width assertions, `\d`/`\D`/`\w`/
# `\W`/`\s`/`\S` are character classes, `\A`/`\Z` are anchors, `\n`/`\t`/`\r`
# are control characters, and `\1`/`\12`/... are backreferences. None of
# them is a letter the pattern author actually typed as part of an
# identifier. A valid Python regex never uses backslash+letter to mean
# "this literal letter" (that's not a legal escape in the `re` module --
# an unrecognized one raises `re.error` at compile time, and every pattern
# here already passed `re.compile` in validate_vocabulary), so matching
# ANY backslash followed by a letter or digit-run is safe and covers the
# full set (\b \B \d \D \w \W \s \S \A \Z \n \t \r, any other single-letter
# escape, and numeric backreferences) without having to enumerate it.
_REGEX_ESCAPE_RE = re.compile(r"\\(?:[0-9]+|[A-Za-z])")


def _strip_regex_escapes(regex):
    """Replaces every backslash-escape sequence with a single space --
    never just the bare backslash, and never nothing at all. This is the
    fix for the third bug in this area (after lowercasing and substring
    containment, both fixed below): `re.split(r"[^A-Za-z0-9_]+", ...)`
    treats `\\` as a separator but the escape's own letter is
    alphanumeric and FUSES onto whichever identifier sits next to it with
    no separator in between -- `\\bMcpError\\b` split that way yields the
    single token `bMcpError`, never the real `McpError`, because the `b`
    of the leading `\\b` glues onto the front of it. Replacing the whole
    two-(or-more)-character escape with a space guarantees a real,
    non-alphanumeric boundary in its place instead of leaving a stray
    letter behind to merge into real identifier text on either side.
    Measured impact on the real MCP v1->v2 vocabulary (115 patterns): 57
    patterns are `\\b`-anchored and had at least one token corrupted this
    way; 34 of those lost every real token and could never register as
    covering any fact, purely from this bug, regardless of what identifier
    the pattern's author actually intended to match."""
    return _REGEX_ESCAPE_RE.sub(" ", regex)


def _pattern_tokens(regex, exclude=frozenset()):
    """A pattern's own regex source, split into alnum/underscore 'words',
    underscore-stripped and lowercased so an underscore-insensitive
    EQUALITY check (not substring containment) can compare it against a
    fact token. Needed because a guide names a wire command with spaces
    or no separator at all (`CLIENT TRACKINGINFO`, `MEMORY STATS`) while
    the Python client's real method name inserts underscores in
    different places (`client_tracking_info`, `memory_stats`) -- and
    Python's `\\b` treats `_` as a word character, so a literal
    `\\b`-bounded match between the two spellings never fires even
    though they plainly name the same thing. Underscore-stripped
    equality sidesteps that mismatch without falling back to substring
    containment, which is what this function used to do and is the bug
    this docstring used to justify: stripping `fastmcp` the same way
    strips to `fastmcp`, and `mcp` (from a fact token like `Mcp-Param-*`
    splitting on punctuation) is a SUBSTRING of `fastmcp`, `mcpserver`,
    `mcperror`, and dozens of other real pattern tokens for any MCP-family
    package -- substring containment made almost every fact naming
    anything MCP-flavored register as covered by almost every pattern,
    regardless of whether the pattern had anything to do with the fact.
    Equality has no such failure mode: `mcp` == `fastmcp` is False.
    Lowercased for the same reason `_fact_identifier_spans` lowercases
    its tokens -- a guide span and a pattern's identifier casing need not
    agree (`redis.Redis` vs. a fact naming it `redis`) for this to
    plausibly be the same symbol. `exclude` (already lowercased/
    underscore-stripped by the caller) drops the package name itself --
    a token that means nothing except "this package" grants no real
    coverage signal, so it's inert on both sides of the comparison.

    Regex escape sequences are stripped (see _strip_regex_escapes) BEFORE
    splitting into words -- otherwise a `\\b`-anchored pattern's own
    escape letter fuses onto the real identifier right next to it (see
    _strip_regex_escapes' docstring for the concrete failure)."""
    stripped = _strip_regex_escapes(regex)
    words = {w.lower().replace("_", "") for w in re.split(r"[^A-Za-z0-9_]+", stripped) if len(w) >= 2}
    return words - exclude


def _token_covers(token, pattern_stripped_tokens):
    return token.replace("_", "") in pattern_stripped_tokens


# A span that names a real Python source construct -- an identifier, a
# dotted attribute path, a call, a decorator -- is a fair target for a grep
# pattern, even if this vocabulary happens not to have one for it (that's a
# vocabulary judgment call, tracked as a real "uncovered" gap, not a defect
# in the metric). A span that is guide PROSE ABOUT Python source -- a
# version-range constraint, a raw JSON-RPC error number, a bare `str`/
# `float` type name, an HTTP header spelled with hyphens, a `tools/list`
# wire path, a full quoted runtime-symptom sentence -- can never plausibly
# appear as that literal token in real source, so scoring it as an
# "uncovered" gap measures an unreachable target. This classifier is purely
# structural (the shape of the span text), never keyed off which specific
# identifier it is -- `TypeError` on its own is a normal, valid identifier
# and stays searchable even though a pattern for it would be a bad idea;
# that restraint is vocabulary_system.md's anti-genericity rule doing its
# job, not a gap this filter should paper over.
_VERSION_SPEC_RE = re.compile(
    r"""^
    (?:[A-Za-z_][A-Za-z0-9_.\-]*\s*)?                        # optional leading package/dep name
    (?:>=|<=|==|!=|~=|>|<)\s*[0-9][0-9A-Za-z.]*              # first constraint
    (?:\s*,\s*(?:>=|<=|==|!=|~=|>|<)\s*[0-9][0-9A-Za-z.]*)*  # further comma-joined constraints
    $""",
    re.VERBOSE,
)

_NUMERIC_CODE_RE = re.compile(r"^-?[0-9]+$")

_BUILTIN_TYPE_NAMES = {
    "str", "int", "float", "bool", "bytes", "bytearray", "complex",
    "list", "dict", "tuple", "set", "frozenset", "object", "type",
    "none", "nonetype",
}

_DATE_LITERAL_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")

# Letters/digits joined by hyphens with no other punctuation -- the shape of
# an HTTP header name (`Mcp-Name`, `MCP-Protocol-Version`) or similar wire
# token. A hyphen is not a legal character inside a Python identifier (it
# parses as subtraction), so a span with this exact shape can never be the
# literal text of a Python name -- only a string constant naming one, which
# a guide backtick-span never spells out with its own quotes.
_WIRE_HEADER_TOKEN_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+$")

# A bare (`tools/list`) or leading-slash (`/authorize`, `/etc/passwd`)
# slash-separated path -- a JSON-RPC method name or a URL route, neither of
# which is a Python identifier shape either.
_METHOD_PATH_RE = re.compile(
    r"^(?:/[A-Za-z_][A-Za-z0-9_]*(?:/[A-Za-z_][A-Za-z0-9_]*)*"
    r"|[A-Za-z_][A-Za-z0-9_]*(?:/[A-Za-z_][A-Za-z0-9_]*)+)$"
)

# Characters a whitespace-delimited "word" is stripped of before judging
# whether it's a plain English word -- deliberately NOT brackets/parens, so
# a real type expression (`Callable[..., Any]`, `Callable[[], str | None]`)
# never gets misread as prose just because it contains bracket-adjacent
# words.
_PROSE_STRIP_CHARS = "\"'`.,:;!?"

# Every name `builtins` exposes -- exceptions (TypeError, ValueError, ...),
# warnings, and callables (isinstance, len, str, ...) -- minus dunders
# (__name__, __doc__, __loader__, ...), which are a structurally different
# kind of identifier a guide might legitimately want a pattern for. This is
# gap-fill's first pre-filter: a span naming a bare Python builtin can never
# usefully be grepped for standalone (a pattern for `TypeError` matches
# every line in the host codebase that already used the language's own
# exception type, migration or not) -- see the comment above
# `_VERSION_SPEC_RE` for the same reasoning applied to version constraints,
# error codes, and the rest. Purely structural, like every other category
# here: never keyed off which identifier it is, only whether its exact text
# is a name Python itself already defines.
_PYTHON_BUILTIN_NAMES = frozenset(
    name for name in dir(builtins) if not name.startswith("__")
)


def _dequote(span):
    span = span.strip()
    if len(span) >= 2 and span[0] == span[-1] and span[0] in ('"', "'"):
        return span[1:-1]
    return span


def _looks_like_prose(span):
    """True when the span reads as an English sentence/phrase rather than
    a code token -- a quoted error message (`"Method not found"`) or an
    exception-plus-message symptom (`TypeError: Invalid "auth" argument`).
    Requires at least two whitespace-separated alphabetic words (after
    stripping only quote/sentence punctuation, never brackets/parens, from
    each word's edges) AND at least one of them lowercase-leading --
    real prose has connective words (`has`, `no`, `request`, `argument`);
    a bare union of capitalized class names (`Foo | Bar | Baz`) does not,
    and must not be caught here."""
    alpha_words = []
    for chunk in span.split():
        core = chunk.strip(_PROSE_STRIP_CHARS)
        if len(core) >= 2 and core.isalpha():
            alpha_words.append(core)
    if len(alpha_words) < 2:
        return False
    return any(w[0].islower() for w in alpha_words)


def classify_span_searchability(span, package_name=None):
    """Returns the name of the unsearchability category this span
    structurally matches, or None if it's a plausible Python source token
    (and therefore stays in the normal covered/partial/uncovered scoring).
    See the block comment above _VERSION_SPEC_RE for why this exists and
    why it never checks the span's identity, only its shape -- with two
    exceptions, both still structural in the sense that neither depends
    on what the identifier means, only on an enumerable/computable fact
    about it:

    - "python_builtin": the span's exact text is a name Python's own
      `builtins` module already defines (TypeError, isinstance, str,
      ...). Membership in `dir(builtins)` is itself a mechanical,
      general-purpose test -- not MCP-specific, not hand-curated.
    - "package_self_reference": the span, once normalized the same way
      `compute_fact_pattern_coverage` normalizes both a fact's tokens
      and a pattern's own tokens (stripped, lowercased, underscores
      removed), equals the package name. `compute_fact_pattern_coverage`
      already excludes the package-name token as a matchable candidate
      on BOTH sides (a bare `mcp` token grants no coverage signal
      against any pattern, even one that legitimately imports `mcp`) --
      so a fact whose only identifier span is the bare package name can
      never reach "covered" no matter what patterns exist. Flagging it
      here stops gap-fill (or a human) from chasing that as if it were a
      real gap; it's a property of how coverage is computed, not a
      missing pattern.

    `package_name` is optional and raw (not pre-normalized) -- pass
    None (the default) to skip the second check entirely, e.g. when
    testing this function standalone with no factblock in scope."""
    dq = _dequote(span)

    if _VERSION_SPEC_RE.match(dq):
        return "version_specifier"
    if _NUMERIC_CODE_RE.match(dq):
        return "numeric_code"

    type_parts = [p.strip().lower() for p in dq.split("|")]
    if type_parts and all(p in _BUILTIN_TYPE_NAMES for p in type_parts) and \
            any(p not in ("none", "nonetype") for p in type_parts):
        return "builtin_type"

    # Checked after builtin_type, not before: a bare `str`/`float`/`bool`
    # (or a `|`-union of them) is already caught above, and that category
    # is the more specific/informative one to keep reporting for those --
    # this check exists for the builtins _BUILTIN_TYPE_NAMES doesn't cover
    # (TypeError, isinstance, len, ...).
    if dq in _PYTHON_BUILTIN_NAMES:
        return "python_builtin"

    if package_name:
        normalized_pkg = package_name.strip().lower().replace("_", "")
        normalized_span = dq.strip().lower().replace("_", "")
        if normalized_pkg and normalized_span == normalized_pkg:
            return "package_self_reference"

    if _DATE_LITERAL_RE.match(dq):
        return "date_literal"
    if _WIRE_HEADER_TOKEN_RE.match(dq):
        return "wire_header_token"
    if _METHOD_PATH_RE.match(dq):
        return "method_path"
    if _looks_like_prose(span):
        return "multiword_prose"
    return None


def compute_fact_pattern_coverage(factblock, vocabulary):
    """The fact<->pattern coverage relation, as structured data -- no
    report text, no pass/fail verdict. This is the one place the
    fact/pattern matching logic lives; check_vocabulary_coverage (the
    runtime guard) and any persistence caller (pipeline.py, so the
    relation is inspectable from the workdir as JSON, not only as guard
    report prose) both call this instead of each keeping their own copy.

    For every fact that names at least one backtick-quoted identifier,
    checks whether ANY derived pattern's own regex source plausibly
    represents EACH such identifier -- an underscore-insensitive EQUALITY
    test against the pattern's own tokens (there's no sample code yet to
    actually run the regex against; this is the same "text overlap as a
    proxy for coverage" approach check_factblock_coverage already uses,
    one level further down the chain -- see _pattern_tokens for why this
    is equality now, not substring containment). For a dotted command
    name (`TS.GET`), a generic segment (`get`) is not required to
    individually match if a more distinctive segment (`ts`) already does
    -- coverage for the trailing generic word is exactly what
    validate_vocabulary's breadth check now forces to route through a
    namespace qualifier instead of appearing standalone. The package name
    itself is excluded as a matchable token on both sides -- a fact whose
    only overlap with a pattern is the package name (e.g. a bare `mcp`
    token matching any pattern that happens to import `mcp`) is not
    covered in any meaningful sense, so it grants no coverage signal
    rather than a real one.

    A fact naming zero concrete identifiers (pure checklist/process prose,
    e.g. "roll the change out gradually") has nothing a syntactic pattern
    could represent -- excluded from the pass/fail requirement, reported
    separately rather than miscounted as a real gap.

    A span can also name something that is real guide content but
    structurally can never be a Python source token in the first place --
    a version-range constraint, a raw JSON-RPC error number, a bare
    builtin type name, a hyphenated wire/header token, a slash-separated
    method path, or a full quoted runtime-symptom sentence (see
    classify_span_searchability). Those spans are pulled out of the
    covered/partial/uncovered scoring entirely -- a pattern cannot
    meaningfully cover them, so counting the absence of one as a gap
    would measure an unreachable target -- and are reported in their own
    "searchable": False bucket instead, exactly like non_breaking/
    no_identifier facts are pulled out of the per-span reckoning.

    Returns a list of per-fact row dicts, in factblock order:
    {"number", "text", "status", "spans"}. `status` is one of:
      - "non_breaking"  -- the fact itself states it's not a breaking
        change (guards._is_non_breaking_fact); no pattern is expected.
      - "no_identifier" -- names no concrete backtick-quoted identifier;
        nothing for a syntactic pattern to represent either way.
      - "unsearchable"  -- names only identifier spans that are
        structurally not Python source tokens, a bare Python builtin
        name, or a self-reference to the package name itself (see
        classify_span_searchability); nothing a grep pattern could ever
        be expected to cover.
      - "covered"       -- every SEARCHABLE identifier span has at least
        one covering pattern (a fact with no searchable spans left never
        reaches this status -- it's "unsearchable" instead).
      - "partial"       -- some searchable spans covered, some not.
      - "uncovered"      -- names searchable identifiers but not one is
        covered by any derived pattern.
    `spans` is always a list (empty for non_breaking/no_identifier, one
    entry per identifier span otherwise): {"span", "covering", "searchable",
    "category"}. `searchable` is False for a structurally-unsearchable
    span (in which case `category` names why and `covering` is always
    `[]`) and True otherwise (in which case `category` is None and
    `covering` is the sorted list of pattern names whose regex source
    plausibly represents that span, empty if none do)."""
    package_name = (factblock.get("package_name") or "").strip().lower().replace("_", "")
    exclude = {package_name} if package_name else set()

    patterns = vocabulary.get("patterns", {})
    pattern_words = {name: _pattern_tokens(regex, exclude=exclude) for name, regex in patterns.items()}

    rows = []
    for fact in factblock.get("facts", []):
        num = fact.get("number")
        text = fact.get("text", "")
        if _is_non_breaking_fact(text):
            rows.append({"number": num, "text": text, "status": "non_breaking", "spans": []})
            continue
        id_spans = _fact_identifier_spans(text)
        if not id_spans:
            rows.append({"number": num, "text": text, "status": "no_identifier", "spans": []})
            continue

        span_rows = []
        for span, tokens in id_spans:
            category = classify_span_searchability(span, package_name=package_name)
            if category is not None:
                span_rows.append({
                    "span": span, "covering": [], "searchable": False, "category": category,
                })
                continue

            distinctive = [t for t in tokens if t not in validate.GENERIC_METHOD_NAMES] or tokens
            # No "or distinctive" fallback here, unlike the generic-word
            # filter above: a span whose only token IS the package name
            # (e.g. a fact naming just `` `mcp` ``) has no real
            # identifier left once that's excluded, and should be
            # reported as such -- not silently matched back in.
            distinctive = [t for t in distinctive if t not in exclude]

            candidates = set(distinctive)
            if len(tokens) > 1:
                # A guide sometimes names a multi-word wire command
                # (`CLIENT TRACKINGINFO`) that the real Python identifier
                # merges with an underscore in a different place
                # (`client_tracking_info`) -- _pattern_tokens treats that
                # whole identifier as ONE token, so per-individual-token
                # equality alone would never match it. The whole span's
                # own concatenation is still an equality check, not a
                # substring one: it either matches a pattern's merged
                # token exactly or it doesn't.
                concatenated = "".join(tokens)
                if concatenated not in exclude:
                    candidates.add(concatenated)

            covering = {
                name for tok in candidates
                for name, words in pattern_words.items()
                if _token_covers(tok, words)
            }
            span_rows.append({
                "span": span, "covering": sorted(covering), "searchable": True, "category": None,
            })

        searchable_rows = [r for r in span_rows if r["searchable"]]
        if not searchable_rows:
            status = "unsearchable"
        elif all(not r["covering"] for r in searchable_rows):
            status = "uncovered"
        elif all(r["covering"] for r in searchable_rows):
            status = "covered"
        else:
            status = "partial"
        rows.append({"number": num, "text": text, "status": status, "spans": span_rows})

    return rows


def render_fact_pattern_coverage_report(rows):
    """The human-readable report check_vocabulary_coverage prints/writes
    -- factored out from the guard decision so a caller that only wants
    the structured `rows` (to persist as JSON) isn't forced to also
    build a report string it will discard."""
    report_lines = ["VOCABULARY COVERAGE CHECK (fact block -> derived vocabulary)", ""]
    for row in rows:
        if row["status"] == "no_identifier":
            report_lines.append(f"  [{row['number']:>3}] (no concrete identifier stated) {row['text'][:90]}")
            continue
        if row["status"] == "non_breaking":
            report_lines.append(f"  [{row['number']:>3}] (explicitly non-breaking -- no pattern expected) {row['text'][:90]}")
            continue
        if row["status"] == "unsearchable":
            report_lines.append(f"  [{row['number']:>3}] (identifiers named are not searchable Python tokens) {row['text'][:90]}")
            for sr in row["spans"]:
                report_lines.append(f"        `{sr['span']}` -> UNSEARCHABLE ({sr['category']})")
            continue
        report_lines.append(f"  [{row['number']:>3}] {row['status'].upper()}: {row['text'][:90]}")
        for sr in row["spans"]:
            if not sr["searchable"]:
                report_lines.append(f"        `{sr['span']}` -> UNSEARCHABLE ({sr['category']})")
                continue
            covering = ", ".join(sr["covering"]) if sr["covering"] else "*** MISSING -- no pattern references it ***"
            report_lines.append(f"        `{sr['span']}` -> {covering}")
    return "\n".join(report_lines)


def check_vocabulary_coverage(factblock, vocabulary):
    """Runs right after vocabulary derivation, before grep. The last
    unchecked link in the coverage chain: check_factblock_coverage already
    guards guide -> factblock; this guards factblock -> vocabulary. Exists
    because vocabulary derivation is demonstrably non-deterministic call to
    call (observed directly: the same fact block, re-derived, silently
    dropped a keyword-argument pattern present in an earlier derivation,
    with zero signal anywhere in the pipeline) -- a fact naming a concrete
    identifier can lose its pattern between one run and the next with
    nothing today to notice. See compute_fact_pattern_coverage for the
    actual matching logic this wraps."""
    rows = compute_fact_pattern_coverage(factblock, vocabulary)
    report = render_fact_pattern_coverage_report(rows)

    gap_facts = [row["number"] for row in rows if row["status"] in ("partial", "uncovered")]
    if gap_facts:
        return GuardResult(
            False,
            f"{len(gap_facts)} fact(s) name a concrete identifier with no derived pattern "
            f"covering it: facts {gap_facts}",
            report,
        )
    return GuardResult(True, "", report)
