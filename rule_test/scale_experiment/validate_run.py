"""
Hard-fail validation for persisted detector run files.

This exists because reconstruction-from-memory has silently corrupted run
data three times in this study (see results.md revision 5 / commit
b643db3). The fix is structural, not a promise: no scorer in this
directory may read a run file without passing it through
validate_run_file() first, and this function raises -- it does not warn,
default, or fill in a plausible-looking value for anything missing.

Rules enforced:
  - The file must be valid JSON. A parse error is fatal.
  - Exactly three list-valued top-level keys are required, present, and
    each item-typed: proposed_sites, flag_uncertain, considered_and_rejected.
    A MISSING key is fatal (this is what silently defaulted to [] before).
    An empty list is allowed -- a run can legitimately propose/flag/reject
    nothing in one of the three buckets -- but the key itself must exist.
  - Every item in every one of the three lists must have non-empty,
    correctly-typed file (str), line (int), and reason (str) fields.
    A blank/whitespace-only string counts as missing.
  - Every item in proposed_sites must additionally have a non-empty
    pattern (str) and snippet (str).
  - target, repo, run must be present at the top level and non-empty.

Raises ValueError with a message identifying the exact file and field on
any violation. Never returns a partially-valid structure.
"""
import json
import os


REQUIRED_TOP_LEVEL = ["target", "repo", "run", "proposed_sites", "flag_uncertain", "considered_and_rejected"]
BUCKET_KEYS = ["proposed_sites", "flag_uncertain", "considered_and_rejected"]
COMMON_ITEM_FIELDS = ["file", "line", "reason"]
PROPOSED_EXTRA_FIELDS = ["pattern", "snippet"]


def _fail(path, msg):
    raise ValueError(f"VALIDATION FAILED for {path}: {msg}")


def _is_blank(v):
    return v is None or (isinstance(v, str) and v.strip() == "")


def validate_run_file(path):
    """Load, validate, and return the run dict at `path`. Raises ValueError on any defect."""
    if not os.path.isfile(path):
        _fail(path, "file does not exist on disk")

    with open(path) as f:
        raw = f.read()
    if raw.strip() == "":
        _fail(path, "file is empty")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        _fail(path, f"not valid JSON ({e})")

    if not isinstance(data, dict):
        _fail(path, "top level is not a JSON object")

    for key in REQUIRED_TOP_LEVEL:
        if key not in data:
            _fail(path, f"missing required top-level key '{key}' "
                        f"(this is exactly the silent-default failure mode being prevented -- "
                        f"a run file must declare all three buckets even if some are empty lists)")

    for key in ["target", "repo"]:
        if _is_blank(data[key]):
            _fail(path, f"top-level field '{key}' is missing or blank")

    if not isinstance(data["run"], int):
        _fail(path, f"top-level field 'run' must be an int, got {type(data['run']).__name__}")

    for bucket in BUCKET_KEYS:
        items = data[bucket]
        if not isinstance(items, list):
            _fail(path, f"'{bucket}' must be a list, got {type(items).__name__}")
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                _fail(path, f"'{bucket}[{idx}]' is not an object")
            for field in COMMON_ITEM_FIELDS:
                if field not in item:
                    _fail(path, f"'{bucket}[{idx}]' missing required field '{field}'")
                if field == "line":
                    if not isinstance(item["line"], int):
                        _fail(path, f"'{bucket}[{idx}].line' must be an int, got {type(item['line']).__name__}")
                elif _is_blank(item[field]):
                    _fail(path, f"'{bucket}[{idx}].{field}' is missing, null, or blank")
            if bucket == "proposed_sites":
                for field in PROPOSED_EXTRA_FIELDS:
                    if field not in item or _is_blank(item[field]):
                        _fail(path, f"'{bucket}[{idx}].{field}' is missing, null, or blank "
                                    f"(required for proposed_sites specifically)")

    return data


def validate_all(run_paths):
    """Validate every path in run_paths. Returns {path: data}. Raises on first failure
    (fail fast, not partial) -- prints which files were already confirmed valid first
    so a failure mid-batch is easy to locate."""
    validated = {}
    for path in run_paths:
        data = validate_run_file(path)
        validated[path] = data
    return validated


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: python validate_run.py <run_file.json> [more files...]")
        sys.exit(1)
    ok = 0
    for p in sys.argv[1:]:
        validate_run_file(p)
        print(f"OK  {p}")
        ok += 1
    print(f"\n{ok}/{len(sys.argv)-1} run files passed validation.")
