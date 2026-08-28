"""Hard-fail validators for every artifact this pipeline produces.

Same discipline as rule_test/scale_experiment/validate_run.py, which this
extends rather than replaces: raise ValueError with the exact field that's
wrong, never warn/default/fill in a plausible value. Applied to the two
new artifact types the study never had to validate (fact block, vocabulary)
and to the adjudication three-bucket contract, unchanged.
"""
import json
import re


def _fail(what, msg):
    raise ValueError(f"VALIDATION FAILED for {what}: {msg}")


def _is_blank(v):
    return v is None or (isinstance(v, str) and v.strip() == "")


# ---------------------------------------------------------------------
# Fact block
# ---------------------------------------------------------------------

def _validate_facts_list(facts, what, allow_empty):
    if not isinstance(facts, list):
        _fail(what, f"'facts' must be a list, got {type(facts).__name__}")
    if not allow_empty and len(facts) == 0:
        _fail(what, "'facts' must be a non-empty list -- an empty fact block means "
                     "derivation produced nothing usable, which must stop the run, not "
                     "proceed with an empty spec")
    for idx, fact in enumerate(facts):
        if not isinstance(fact, dict):
            _fail(what, f"'facts[{idx}]' is not an object")
        if "number" not in fact or not isinstance(fact["number"], int):
            _fail(what, f"'facts[{idx}].number' missing or not an int")
        if _is_blank(fact.get("text")):
            _fail(what, f"'facts[{idx}].text' is missing or blank")


def validate_factblock(data, what="factblock"):
    if not isinstance(data, dict):
        _fail(what, "top level is not a JSON object")
    if "package_name" not in data:
        _fail(what, "missing required top-level key 'package_name'")
    if _is_blank(data["package_name"]):
        _fail(what, "'package_name' is missing or blank -- the guide-ingestion step must "
                     "name the primary import surface explicitly; this pipeline never guesses it")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", data["package_name"]):
        _fail(what, f"'package_name' must be a single bare Python import identifier, got "
                     f"{data['package_name']!r} -- this is prose/a description, not an "
                     f"importable name; the guide-ingestion step must fail here rather than "
                     f"pass a name the prefilter's relevance pattern can never match")
    if "facts" not in data:
        _fail(what, "missing required top-level key 'facts'")
    _validate_facts_list(data["facts"], what, allow_empty=False)
    return data


def validate_factblock_chunk(data, what="factblock chunk"):
    """Same structural checks as validate_factblock, relaxed for a single
    guide-SECTION chunk rather than the whole fact block: a section may
    legitimately state zero breaking-change facts (pure prose/overview/
    appendix content, no different from a whole guide having a real fact
    a human would recognize as "nothing to report here"), and most
    individual sections won't restate the guide's overall package name.
    Both are deferred to merge time -- an empty facts list contributes
    nothing and is fine; a blank package_name is excluded from the
    cross-chunk consensus in factblock.py, not itself a failure. What
    still hard-fails here exactly as it does in validate_factblock: a
    non-blank package_name that isn't a valid bare identifier (prose or
    a description, not silently accepted), and any malformed fact that
    IS present. The merged result coming out of that consensus still
    goes through validate_factblock unchanged, so the full fact block's
    contract (non-empty facts, non-blank package_name) is enforced
    exactly as before -- this relaxation applies only to one chunk's
    partial view."""
    if not isinstance(data, dict):
        _fail(what, "top level is not a JSON object")
    if "package_name" not in data:
        _fail(what, "missing required top-level key 'package_name'")
    if not _is_blank(data["package_name"]) and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", data["package_name"]):
        _fail(what, f"'package_name' must be blank or a single bare Python import "
                     f"identifier, got {data['package_name']!r} -- this is prose/a "
                     f"description, not an importable name")
    if "facts" not in data:
        _fail(what, "missing required top-level key 'facts'")
    _validate_facts_list(data["facts"], what, allow_empty=True)
    return data


def validate_factblock_file(path):
    """Same discipline as validate_adjudication_file/validate_fixgen_file --
    used by --factblock to load a previously derived fact block. Loading
    must not be a way to bypass validation: this runs the exact same
    validate_factblock check a freshly derived fact block gets."""
    with open(path) as f:
        raw = f.read()
    if raw.strip() == "":
        _fail(path, "file is empty")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        _fail(path, f"not valid JSON ({e})")
    return validate_factblock(data, what=path)


# ---------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------

# Generic verbs/nouns that show up as method or attribute names on all
# kinds of unrelated Python objects (dict.get, requests.Response.json(),
# re.search, list.count, set.add, json.load, ...). A pattern that reduces
# to nothing but one of these, bare, matches most of a host codebase
# rather than the migration -- see _bare_dotted_call_alternatives below.
GENERIC_METHOD_NAMES = {
    "get", "set", "add", "remove", "delete", "update", "list", "count",
    "query", "info", "type", "range", "put", "post", "head", "options",
    "keys", "values", "items", "pop", "copy", "clear", "format", "strip",
    "split", "join", "replace", "encode", "decode", "index", "extend",
    "append", "insert", "sort", "reverse", "next", "run", "start", "stop",
    "execute", "commit", "rollback", "save", "load", "loads", "dump",
    "dumps", "parse", "match", "search", "group", "groups", "read",
    "write", "open", "close", "send", "recv", "find", "filter", "map",
    "reduce", "json",
}

# Matches a regex source string that is *nothing but* `\.word\(` or
# `\.(word|word|...)\(`, optionally with `\s*` between the group and the
# call paren -- i.e. no namespace/class prefix, no required co-occurring
# token, nothing anchoring the match to this package at all. Deliberately
# narrow (fullmatch, not search): it only condemns a branch with *zero*
# other context, never one that adds a qualifier of any kind.
_BARE_DOTTED_CALL_RE = re.compile(
    r"\\\.\(?([A-Za-z_]+(?:\|[A-Za-z_]+)*)\)?(?:\\s\*)?\\\("
)


def _split_top_level_alternatives(regex):
    """Splits on `|` at paren-depth 0 only. A `|` nested inside a group
    is scoped to that group and can't leak overmatch on its own; a `|` at
    the top level makes each side an independent whole-pattern
    alternative -- p35_hybrid's `HybridQuery|...|\\.load\\s*\\(` matches
    if EITHER side matches, so a bare, generic branch buried among
    otherwise-fine ones is exactly as overbroad as if it were the whole
    pattern."""
    parts, depth, buf, i, n = [], 0, [], 0, len(regex)
    while i < n:
        ch = regex[i]
        if ch == "\\" and i + 1 < n:
            buf.append(regex[i:i + 2])
            i += 2
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "|" and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts


def _bare_dotted_call_alternatives(regex):
    """Returns the generic method names found among any top-level
    alternative that reduces to a bare dotted call, or [] if none."""
    hits = []
    for branch in _split_top_level_alternatives(regex):
        m = _BARE_DOTTED_CALL_RE.fullmatch(branch.strip())
        if m:
            hits.extend(m.group(1).split("|"))
    return hits


# A bare global inline flag -- `(?i)`, `(?m)`, etc, with no `:` -- compiles
# fine as its own standalone pattern (the flag sits at position 0 of that
# string), but pipeline.py wraps every pattern in `(?:...)` and joins them
# all with `|` into one combined search regex; at any position other than
# the very start of the FULL combined expression, Python 3.11+ rejects a
# global flag outright ("global flags not at the start of the
# expression"). A pattern that individually compiles can still break the
# entire vocabulary this way -- catch it here, before it costs a grep-plus-
# prefilter run only to crash with a raw traceback in pipeline.py. The
# scoped form, `(?i:...)`, has none of this restriction and is the fix.
_BARE_GLOBAL_FLAG_RE = re.compile(r"\(\?[aiLmsux]+\)")


def _validate_pattern_regex(name, regex, what):
    """The per-pattern checks every vocabulary pattern must pass,
    regardless of which stage produced it: compiles, no bare global
    inline flag, no bare unqualified generic-method-call match. Factored
    out of validate_vocabulary so validate_gapfill_dict can require the
    exact same discipline of gap-fill's own output without duplicating
    it -- gap-fill patterns get merged into the same vocabulary and run
    through the same combined regex, so nothing about what makes a
    pattern safe is different for them."""
    if _is_blank(regex):
        _fail(what, f"pattern '{name}' is missing or blank")
    try:
        re.compile(regex)
    except re.error as e:
        _fail(what, f"pattern '{name}' does not compile as a regex: {e}\nregex: {regex!r}")
    if _BARE_GLOBAL_FLAG_RE.search(regex):
        _fail(
            what,
            f"pattern '{name}' ({regex!r}) uses a bare global inline flag (e.g. `(?i)`). "
            f"It compiles alone, but every pattern gets wrapped in `(?:...)` and joined "
            f"with the rest of the vocabulary into one combined regex downstream -- at "
            f"that point a global flag anywhere but position 0 of the WHOLE combined "
            f"expression is a compile error, not just a warning. Use the scoped form "
            f"instead, e.g. `(?i:...)` around only the part that needs it -- it has no "
            f"such restriction at any nesting position.",
        )
    bare_alternatives = _bare_dotted_call_alternatives(regex)
    generic_hits = [a for a in bare_alternatives if a.lower() in GENERIC_METHOD_NAMES]
    if generic_hits:
        _fail(
            what,
            f"pattern '{name}' ({regex!r}) is a bare, unqualified method-call match "
            f"-- {', '.join(sorted(set(generic_hits)))} would match that method name "
            f"on ANY Python object (dict.get, requests.Response.json(), re.search, "
            f"list.count, ...), not just this package's calls. This is the exact "
            f"overmatch failure the vocabulary-derivation prompt is instructed to "
            f"avoid -- add a namespace/class/import-path qualifier the guide's own "
            f"command name implies (e.g. `TS.GET` -> `\\.ts\\(\\)\\.get\\(`), or a "
            f"required co-occurring token from the guide's own example, rather than "
            f"matching the trailing word alone.",
        )


def validate_vocabulary(data, what="vocabulary"):
    if not isinstance(data, dict):
        _fail(what, "top level is not a JSON object")
    if "patterns" not in data:
        _fail(what, "missing required top-level key 'patterns'")
    patterns = data["patterns"]
    if not isinstance(patterns, dict) or len(patterns) == 0:
        _fail(what, "'patterns' must be a non-empty object mapping name -> regex string")
    for name, regex in patterns.items():
        _validate_pattern_regex(name, regex, what)

    try:
        re.compile("|".join(f"(?:{p})" for p in patterns.values()))
    except re.error as e:
        _fail(
            what,
            f"every individual pattern compiles, but the patterns fail to compile as the "
            f"single combined regex the pipeline actually runs (each pattern wrapped in "
            f"`(?:...)` and joined with `|`, exactly as pipeline.py does before prefiltering): "
            f"{e}. This means the per-pattern check above missed a combination-only failure -- "
            f"treat this as a hard stop, not a warning.",
        )
    return data


def validate_vocabulary_file(path):
    """Same discipline as validate_factblock_file -- used by --vocabulary
    to load a previously derived vocabulary. Loading must not be a way to
    bypass validation: this runs the exact same validate_vocabulary check
    a freshly derived vocabulary gets."""
    with open(path) as f:
        raw = f.read()
    if raw.strip() == "":
        _fail(path, "file is empty")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        _fail(path, f"not valid JSON ({e})")
    return validate_vocabulary(data, what=path)


# ---------------------------------------------------------------------
# Gap-fill two-bucket contract -- same discipline as the adjudication/
# fixgen two/three-bucket contracts below: a result must declare both
# buckets even if one is empty, never defaulted. `patterns` gets every
# check validate_vocabulary already applies to a pattern (via
# _validate_pattern_regex, shared rather than duplicated) PLUS two checks
# specific to gap-fill, below.
#
# Why gap-fill gets its own, STRICTER checks that plain vocabulary
# derivation doesn't: pass-0 derivation is handed the whole guide and
# asked for good coverage across it -- a single pattern legitimately
# grouping many genuinely-related symbols (e.g. eighteen removed type
# names that all disappeared the same way) is exactly what "COVERAGE PER
# PATTERN, NOT PER FACT" in vocabulary_system.md asks for. Gap-fill is a
# narrower, more exploitable prompt: it is handed a specific list of
# facts already known to lack coverage and told, in effect, "these lack
# patterns." That framing rewards satisfying the checker over writing a
# real pattern -- the cheapest way to make N facts stop looking like
# gaps is one broad alternation whose branches are the N facts' own
# identifiers, whether or not they share any real syntactic shape. That
# pattern compiles, isn't a bare dotted call (so the existing
# generic-method check never even looks at it), and would make every
# target fact register as covered. The two extra checks below exist
# because nothing else in this file would catch it.
GAPFILL_MAX_ALTERNATIVES = 3
# Picked, not derived: gap-fill's OWN target set already groups facts
# that are individually flagged as separately lacking coverage, not
# facts a human bundled because they share a call shape -- unlike
# pass-0's "TS.GET/JSON.SET/FT.SEARCH share a namespaced-command shape"
# groupings, gap-fill has no equivalent structural signal that N target
# facts belong in one pattern together. 3 is small enough that a
# legitimate small group (e.g. two or three sibling constants named in
# the SAME fact, like `client_secret_basic`/`client_secret_post`) still
# fits, while a kitchen-sink alternation spanning a double-digit target
# list cannot -- and low enough that satisfying the id-must-reference-
# the-symbol check below (~12 characters, per vocabulary_system.md's own
# id-length guidance) stays physically plausible for every branch, which
# stops being true well before branch counts reach the double digits.


def _regex_own_words(regex):
    """A rough, regex-syntax-agnostic word split of a pattern's own
    source. Deliberately simpler than guards.py's _pattern_tokens (which
    has to be precise about escape sequences for accurate fact<->pattern
    coverage matching) -- this only needs to answer "does this pattern's
    id trace back to recognizable text in its own regex," a much cruder
    bar, and living in validate.py (which nothing in apidrift imports)
    keeps this file free of the guards.py<->validate.py import cycle
    that reusing _pattern_tokens directly would create."""
    cleaned = re.sub(r"\\[A-Za-z0-9]", " ", regex)
    return {w.lower().replace("_", "") for w in re.findall(r"[A-Za-z0-9_]{2,}", cleaned)}


def _longest_common_substring_len(a, b):
    """Longest run of contiguous characters common to both strings.
    Both operands here are short (a pattern id, ~12 chars per
    vocabulary_system.md's own guidance; a regex-derived word, rarely
    more than ~20) so the O(len(a)*len(b)) DP is cheap. Used instead of
    plain substring containment because a realistic short id truncates a
    longer word rather than repeating it whole (e.g. id 'gf_clientsess'
    for a `ClientSession` pattern) -- neither direction of `in` holds
    once a stage prefix like 'gf_' sits in front of the truncation, even
    though the id plainly does name the symbol."""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for ca in a:
        curr = [0] * (len(b) + 1)
        for j, cb in enumerate(b, start=1):
            if ca == cb:
                curr[j] = prev[j - 1] + 1
                best = max(best, curr[j])
        prev = curr
    return best


GAPFILL_ID_OVERLAP_MIN = 4


def _count_alternation_branches(regex):
    """Total `|`-separated alternatives anywhere in the pattern, at ANY
    nesting depth -- unlike _split_top_level_alternatives above (which
    only counts a depth-0 `|`, because that check specifically cares
    whether a branch is an independent WHOLE-PATTERN alternative, the
    shape a bare generic method name has to have to overmatch on its
    own), gap-fill's cap cares how many distinct things one pattern can
    match at all. `\\b(A|B|C)\\b` offers three alternatives exactly as
    much as a top-level `A|B|C` would, and the grouped form is how this
    vocabulary's own existing patterns are written (p7_removedtyp,
    p12_unions, ...), so counting only depth-0 pipes would miss the
    exact shape a gap-fill kitchen-sink pattern is written in."""
    n, i, length = 1, 0, len(regex)
    while i < length:
        ch = regex[i]
        if ch == "\\" and i + 1 < length:
            i += 2
            continue
        if ch == "|":
            n += 1
        i += 1
    return n


def _validate_gapfill_pattern_anti_goodhart(name, regex, what):
    branches = _count_alternation_branches(regex)
    if branches > GAPFILL_MAX_ALTERNATIVES:
        _fail(
            what,
            f"gap-fill pattern '{name}' ({regex!r}) has {branches} alternation "
            f"branches, over the gap-fill cap of {GAPFILL_MAX_ALTERNATIVES}. "
            f"If these branches genuinely share one call shape from the same fact or "
            f"sibling facts, that's still capped here deliberately -- split into more "
            f"than one pattern. If some of them don't actually belong together, decline "
            f"the ones that don't fit (see the 'declined' bucket) rather than folding "
            f"them into one pattern to shrink the decline count.",
        )
    id_norm = name.lower().replace("_", "")
    words = [w for w in _regex_own_words(regex) if len(w) >= 3]
    if words and not any(
        _longest_common_substring_len(id_norm, w) >= min(GAPFILL_ID_OVERLAP_MIN, len(w))
        for w in words
    ):
        _fail(
            what,
            f"gap-fill pattern '{name}' ({regex!r}) -- id does not reference any "
            f"recognizable word from its own regex text. Every gap-fill pattern's id "
            f"must name the specific symbol it targets (e.g. 'gf_rootmodel' for a "
            f"RootModel pattern) -- an id that can't be traced back to its own "
            f"pattern's content is exactly the shape a pattern written to satisfy the "
            f"coverage checker, rather than to name a real symbol, would have.",
        )


GAPFILL_BUCKET_KEYS = ["patterns", "declined"]
GAPFILL_DECLINED_FIELDS = ["fact", "span", "reason"]


def validate_gapfill_dict(data, what="gapfill result"):
    if not isinstance(data, dict):
        _fail(what, "top level is not a JSON object")
    for key in GAPFILL_BUCKET_KEYS:
        if key not in data:
            _fail(what, f"missing required top-level key '{key}' (a result must declare "
                         f"both buckets even if one is empty -- the whole point of the "
                         f"decline channel is that 'no pattern' and 'never addressed' "
                         f"must never be indistinguishable again)")

    patterns = data["patterns"]
    if not isinstance(patterns, list):
        _fail(what, f"'patterns' must be a list of {{name, regex}} objects, got "
                     f"{type(patterns).__name__}")
    seen_names = set()
    for idx, item in enumerate(patterns):
        if not isinstance(item, dict) or "name" not in item or "regex" not in item:
            _fail(what, f"'patterns[{idx}]' malformed: expected {{'name', 'regex'}}, got {item!r}")
        name, regex = item["name"], item["regex"]
        if name in seen_names:
            _fail(what, f"duplicate pattern id '{name}' within this gap-fill pass -- "
                         f"every id must be unique, same as validate_vocabulary already "
                         f"requires for a full vocabulary")
        seen_names.add(name)
        _validate_pattern_regex(name, regex, what)
        _validate_gapfill_pattern_anti_goodhart(name, regex, what)

    declined = data["declined"]
    if not isinstance(declined, list):
        _fail(what, f"'declined' must be a list of {{fact, span, reason}} objects, got "
                     f"{type(declined).__name__}")
    for idx, item in enumerate(declined):
        if not isinstance(item, dict):
            _fail(what, f"'declined[{idx}]' is not an object")
        for field in GAPFILL_DECLINED_FIELDS:
            if field not in item:
                _fail(what, f"'declined[{idx}]' missing required field '{field}'")
            if field == "fact":
                if not isinstance(item["fact"], int):
                    _fail(what, f"'declined[{idx}].fact' must be an int, got "
                                 f"{type(item['fact']).__name__}")
            elif _is_blank(item[field]):
                _fail(what, f"'declined[{idx}].{field}' is missing, null, or blank")
    return data


def validate_gapfill_file(path):
    """Same discipline as validate_vocabulary_file -- used to resume a
    run by loading an already-completed gap-fill pass instead of
    re-deriving it."""
    with open(path) as f:
        raw = f.read()
    if raw.strip() == "":
        _fail(path, "file is empty")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        _fail(path, f"not valid JSON ({e})")
    return validate_gapfill_dict(data, what=path)


# ---------------------------------------------------------------------
# Adjudication three-bucket contract -- same rules as validate_run.py,
# operating on an in-memory dict as well as a file on disk, since the
# adjudication stage validates a chunk's result right after the LLM
# call returns, before it's ever written anywhere.
# ---------------------------------------------------------------------

BUCKET_KEYS = ["proposed_sites", "flag_uncertain", "considered_and_rejected"]
COMMON_ITEM_FIELDS = ["file", "line", "reason"]
PROPOSED_EXTRA_FIELDS = ["pattern", "snippet"]


def validate_adjudication_dict(data, what="adjudication result"):
    if not isinstance(data, dict):
        _fail(what, "top level is not a JSON object")

    for key in BUCKET_KEYS:
        if key not in data:
            _fail(what, f"missing required top-level key '{key}' (this is exactly the "
                         f"silent-default failure mode being prevented -- a result must "
                         f"declare all three buckets even if some are empty lists)")

    for bucket in BUCKET_KEYS:
        items = data[bucket]
        if not isinstance(items, list):
            _fail(what, f"'{bucket}' must be a list, got {type(items).__name__}")
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                _fail(what, f"'{bucket}[{idx}]' is not an object")
            for field in COMMON_ITEM_FIELDS:
                if field not in item:
                    _fail(what, f"'{bucket}[{idx}]' missing required field '{field}'")
                if field == "line":
                    if not isinstance(item["line"], int):
                        _fail(what, f"'{bucket}[{idx}].line' must be an int, got "
                                     f"{type(item['line']).__name__}")
                elif _is_blank(item[field]):
                    _fail(what, f"'{bucket}[{idx}].{field}' is missing, null, or blank")
            if bucket == "proposed_sites":
                for field in PROPOSED_EXTRA_FIELDS:
                    if field not in item or _is_blank(item[field]):
                        _fail(what, f"'{bucket}[{idx}].{field}' is missing, null, or blank "
                                     f"(required for proposed_sites specifically)")
    return data


def validate_adjudication_file(path):
    with open(path) as f:
        raw = f.read()
    if raw.strip() == "":
        _fail(path, "file is empty")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        _fail(path, f"not valid JSON ({e})")
    return validate_adjudication_dict(data, what=path)


# ---------------------------------------------------------------------
# Fix generation two-bucket contract -- DESIGN.md's "two-bucket analogue"
# to the adjudication three-bucket contract: FIX / FLAG-FOR-HUMAN. Same
# discipline -- a missing bucket key is fatal, never defaulted to [].
# ---------------------------------------------------------------------

FIXGEN_BUCKET_KEYS = ["fixes", "flagged_for_human"]
FIXGEN_COMMON_FIELDS = ["file", "line", "reason"]
FIXGEN_FIX_EXTRA_FIELDS = ["original_line", "proposed_line"]


def validate_fixgen_dict(data, what="fixgen result"):
    if not isinstance(data, dict):
        _fail(what, "top level is not a JSON object")

    for key in FIXGEN_BUCKET_KEYS:
        if key not in data:
            _fail(what, f"missing required top-level key '{key}' (a result must declare "
                         f"both buckets even if one is empty)")

    for bucket in FIXGEN_BUCKET_KEYS:
        items = data[bucket]
        if not isinstance(items, list):
            _fail(what, f"'{bucket}' must be a list, got {type(items).__name__}")
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                _fail(what, f"'{bucket}[{idx}]' is not an object")
            for field in FIXGEN_COMMON_FIELDS:
                if field not in item:
                    _fail(what, f"'{bucket}[{idx}]' missing required field '{field}'")
                if field == "line":
                    if not isinstance(item["line"], int):
                        _fail(what, f"'{bucket}[{idx}].line' must be an int, got "
                                     f"{type(item['line']).__name__}")
                elif _is_blank(item[field]):
                    _fail(what, f"'{bucket}[{idx}].{field}' is missing, null, or blank")
            if bucket == "fixes":
                for field in FIXGEN_FIX_EXTRA_FIELDS:
                    if field not in item or _is_blank(item[field]):
                        _fail(what, f"'{bucket}[{idx}].{field}' is missing, null, or blank "
                                     f"(required for fixes specifically)")
    return data


def validate_fixgen_file(path):
    with open(path) as f:
        raw = f.read()
    if raw.strip() == "":
        _fail(path, "file is empty")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        _fail(path, f"not valid JSON ({e})")
    return validate_fixgen_dict(data, what=path)
