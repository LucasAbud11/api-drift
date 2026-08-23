"""Shared scoring for fix-generation acceptance tests. Same three-way split
as rule_test/fix_generation_experiment/score.py (exact-match / semantic-
equivalent / wrong), but "wrong" is named for what it actually is here --
REPORT.md's "locally-plausible-but-globally-wrong": a confident FIX verdict
that doesn't match the hand-derived answer key. That's the failure mode
that would actually ship a bug, as opposed to an over-cautious hedge.

Scoring is scoped to whatever the pipeline actually sent to fix generation
(detection's real PROPOSE bucket this run, expanded_expanded["fixes"] +
["flagged_for_human"]) rather than the full study GT list -- detection's
own surfaced-vs-propose-only recall has measured run-to-run variance
(REPORT.md's results table), and a GT site that landed in FLAG-UNCERTAIN
instead of PROPOSE this run was never sent to fix-gen at all, which is a
detection-stage fact the calling test's own recall/precision assertions
already cover, not a fix-generation miss.
"""
import re


def _normalize(line):
    if line is None:
        return None
    s = line.strip()
    s = re.sub(r"\s+", " ", s)
    s = s.replace('"', "'")
    return s


def classify_fix(proposed_line, required_line):
    if proposed_line is None or required_line is None:
        return "locally-plausible-but-globally-wrong"
    if proposed_line.rstrip() == required_line.rstrip():
        return "exact-match"
    if _normalize(proposed_line) == _normalize(required_line):
        return "semantic-equivalent"
    return "locally-plausible-but-globally-wrong"


def score_fixgen(fixgen_expanded, required, legitimate_hedge_keys=frozenset()):
    """`fixgen_expanded`: pipeline.run()'s {"fixes": [...], "flagged_for_human": [...]}
    (post duplicate-expansion). `required`: {(file, line): required_line_text},
    the hand-derived answer key. Scores every site fix-gen actually returned
    a verdict for; a site with no entry in `required` is scored `unknown`
    (a real anomaly worth surfacing -- it means fix-gen was asked about a
    site outside what the answer key covers, which the calling test's
    precision assertion should already have ruled out)."""
    rows = []
    for item in fixgen_expanded["fixes"]:
        key = (item["file"], item["line"])
        required_line = required.get(key)
        if required_line is None:
            cls = "unknown-site"
        else:
            cls = classify_fix(item.get("proposed_line"), required_line)
        rows.append({
            "key": key, "verdict": "FIX", "class": cls,
            "proposed_line": item.get("proposed_line"), "required_line": required_line,
            "reason": item.get("reason"),
        })
    for item in fixgen_expanded["flagged_for_human"]:
        key = (item["file"], item["line"])
        required_line = required.get(key)
        if required_line is None:
            cls = "unknown-site"
        else:
            cls = "legitimate-hedge" if key in legitimate_hedge_keys else "avoidable-hedge"
        rows.append({
            "key": key, "verdict": "FLAG-FOR-HUMAN", "class": cls,
            "proposed_line": None, "required_line": required_line,
            "reason": item.get("reason"),
        })

    n = len(rows)
    counts = {}
    for cls in ("exact-match", "semantic-equivalent", "legitimate-hedge",
                "avoidable-hedge", "locally-plausible-but-globally-wrong", "unknown-site"):
        counts[cls] = sum(1 for r in rows if r["class"] == cls)

    return {"n_sites": n, "counts": counts, "rows": rows}


def verification_status_for(verification_report, file, line):
    """Human-readable summary of what tier 1/2 verification said about one
    specific (file, line), or None if verification never ran (skip_fix_generation)."""
    if verification_report is None:
        return None
    parts = []
    for item in verification_report["parse_and_line_match"]["items"]:
        if (item["file"], item["line"]) == (file, line):
            parts.append(f"tier1 line-match={'OK' if item.get('line_match_ok') else 'FAILED'}")
            break
    file_parse = verification_report["parse_and_line_match"]["file_parse_results"].get(file)
    if file_parse is not None:
        parts.append(f"tier1 parse={'OK' if file_parse.get('parses') else 'FAILED'}")
    install = verification_report.get("install", {})
    if install.get("available"):
        for item in install["items"]:
            if (item["file"], item["line"]) == (file, line):
                parts.append(f"tier2 import-resolve={'OK' if item.get('resolved') else 'FAILED'}")
                break
        else:
            parts.append("tier2 not-applicable (proposed line is not an import statement)")
    else:
        parts.append(f"tier2 unavailable ({install.get('reason')})")
    return "; ".join(parts)


def print_score_report(label, scored, verification_report=None):
    print(f"\nfix-generation scoring, {label} ({scored['n_sites']} sites sent to fix-gen):")
    for cls, n in scored["counts"].items():
        if n or cls in ("exact-match", "locally-plausible-but-globally-wrong"):
            print(f"  {cls}: {n}/{scored['n_sites']}")

    wrong = [r for r in scored["rows"] if r["class"] == "locally-plausible-but-globally-wrong"]
    if wrong:
        print("\n  WRONG sites -- verification cross-check (this is the number that matters):")
        for r in wrong:
            v = verification_status_for(verification_report, r["key"][0], r["key"][1])
            print(f"    {r['key']}: proposed={r['proposed_line']!r} required={r['required_line']!r}")
            print(f"      verification says: {v}")
            if v and "FAILED" not in v and "unavailable" not in v:
                print("      *** verification PASSED on a WRONG fix -- verification tier is too weak "
                      "to have caught this on its own ***")

    unknown = [r for r in scored["rows"] if r["class"] == "unknown-site"]
    if unknown:
        print(f"\n  UNKNOWN sites (no answer-key entry -- should not happen if precision was 100%): "
              f"{[r['key'] for r in unknown]}")
