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
    facts = data["facts"]
    if not isinstance(facts, list) or len(facts) == 0:
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
    return data


# ---------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------

def validate_vocabulary(data, what="vocabulary"):
    if not isinstance(data, dict):
        _fail(what, "top level is not a JSON object")
    if "patterns" not in data:
        _fail(what, "missing required top-level key 'patterns'")
    patterns = data["patterns"]
    if not isinstance(patterns, dict) or len(patterns) == 0:
        _fail(what, "'patterns' must be a non-empty object mapping name -> regex string")
    for name, regex in patterns.items():
        if _is_blank(regex):
            _fail(what, f"pattern '{name}' is missing or blank")
        try:
            re.compile(regex)
        except re.error as e:
            _fail(what, f"pattern '{name}' does not compile as a regex: {e}\nregex: {regex!r}")
    return data


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
