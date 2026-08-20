"""Score entangled-host fix-generation runs against fix_ground_truth.md.

Three categories per this task's request: exact-match, semantically-
equivalent-but-different, and locally-plausible-but-globally-wrong (a
confident FIX on one of the 4 sites that has no correct single-line
answer -- E4, E5, E6, E9). Also tracks legitimate-hedge and wrong.
"""
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))

# The 6 sites with one confident, correct, single-line answer.
REQUIRED = {
    "E1": 'from mcp.server.mcpserver import MCPServer',
    "E2": 'class OpsMeshServer(MCPServer):',
    "E3": 'from mcp.server.mcpserver import Context',
    "E7": '                        input_schema=getattr(tool, "input_schema", {}) or {},',
    "E8": '    with patch("mcp.server.mcpserver.MCPServer.run") as fastmcp_run:',
    "E10": '    return SimpleNamespace(name=name, description=description, input_schema=schema)',
}

# The 4 sites where NO single-line answer is correct -- see fix_ground_truth.md.
# Any FIX verdict here (regardless of proposed text) is locally-plausible-but-
# globally-wrong. FLAG-FOR-HUMAN is the only verdict that scores as correct.
NO_SINGLE_LINE_FIX = {"E4", "E5", "E6", "E9"}

ALL_IDS = set(REQUIRED) | NO_SINGLE_LINE_FIX


def normalize(line):
    if line is None:
        return None
    s = line.strip()
    s = re.sub(r"\s+", " ", s)
    s = s.replace('"', "'")
    return s


def classify_single_line(proposed, required):
    if proposed is None:
        return "wrong"
    if proposed.rstrip() == required.rstrip():
        return "exact"
    if normalize(proposed) == normalize(required):
        return "semantic-equivalent"
    return "wrong"


def score_run(run_path):
    with open(run_path) as f:
        data = json.load(f)
    by_id = {}
    dup_ids = []
    for item in data:
        i = item.get("id")
        if i in by_id:
            dup_ids.append(i)
        by_id[i] = item

    results = []
    missing_ids = ALL_IDS - set(by_id)
    extra_ids = set(by_id) - ALL_IDS

    for site_id in REQUIRED:
        item = by_id.get(site_id)
        if item is None:
            results.append({"id": site_id, "verdict": "MISSING_FROM_RUN", "class": "wrong"})
            continue
        verdict = item.get("verdict")
        if verdict == "FIX":
            cls = classify_single_line(item.get("proposed_line"), REQUIRED[site_id])
        elif verdict == "FLAG-FOR-HUMAN":
            cls = "hedge-avoidable"  # these 6 sites DO have one confident correct answer
        elif verdict == "SKIP":
            cls = "wrong-skip"
        else:
            cls = "wrong-unknown-verdict"
        results.append({
            "id": site_id, "verdict": verdict, "class": cls, "site_type": "single-line",
            "proposed_line": item.get("proposed_line"), "required_line": REQUIRED[site_id],
            "reason": item.get("reason"),
        })

    for site_id in NO_SINGLE_LINE_FIX:
        item = by_id.get(site_id)
        if item is None:
            results.append({"id": site_id, "verdict": "MISSING_FROM_RUN", "class": "wrong"})
            continue
        verdict = item.get("verdict")
        if verdict == "FIX":
            cls = "locally-plausible-but-globally-wrong"
        elif verdict == "FLAG-FOR-HUMAN":
            cls = "hedge-legitimate"
        elif verdict == "SKIP":
            cls = "wrong-skip"
        else:
            cls = "wrong-unknown-verdict"
        results.append({
            "id": site_id, "verdict": verdict, "class": cls, "site_type": "no-single-line-fix",
            "proposed_line": item.get("proposed_line"), "reason": item.get("reason"),
        })

    n = len(ALL_IDS)
    counts = {}
    for r in results:
        counts[r["class"]] = counts.get(r["class"], 0) + 1

    return {
        "run_file": os.path.basename(run_path),
        "n_sites": n,
        "exact_match_rate": counts.get("exact", 0) / n,
        "semantic_equivalent_rate": counts.get("semantic-equivalent", 0) / n,
        "locally_plausible_globally_wrong_rate": counts.get("locally-plausible-but-globally-wrong", 0) / n,
        "legitimate_hedge_rate": counts.get("hedge-legitimate", 0) / n,
        "avoidable_hedge_rate": counts.get("hedge-avoidable", 0) / n,
        "wrong_rate": (counts.get("wrong", 0) + counts.get("wrong-skip", 0) + counts.get("wrong-unknown-verdict", 0)) / n,
        "duplicate_ids_in_run": dup_ids,
        "missing_ids": sorted(missing_ids),
        "unexpected_extra_ids": sorted(extra_ids),
        "detail": results,
    }


def main():
    runs_dir = os.path.join(BASE, "runs")
    out = {}
    for n in (1, 2, 3):
        path = os.path.join(runs_dir, f"run{n}.json")
        if not os.path.exists(path):
            print(f"HARD FAIL: {path} does not exist -- refusing to score a partial set.", file=sys.stderr)
            sys.exit(1)
        r = score_run(path)
        out[f"run{n}"] = r
        print(f"\n===== run{n} ({r['run_file']}) =====")
        print(f"  exact-match (6 single-line sites):              {r['exact_match_rate']:.1%}")
        print(f"  semantic-equivalent (6 single-line sites):       {r['semantic_equivalent_rate']:.1%}")
        print(f"  LOCALLY-PLAUSIBLE-BUT-GLOBALLY-WRONG (4 sites):  {r['locally_plausible_globally_wrong_rate']:.1%}")
        print(f"  legitimate hedge (4 sites):                      {r['legitimate_hedge_rate']:.1%}")
        print(f"  avoidable hedge (6 sites):                       {r['avoidable_hedge_rate']:.1%}")
        print(f"  wrong:                                            {r['wrong_rate']:.1%}")
        if r["duplicate_ids_in_run"]:
            print(f"  WARNING duplicate ids: {r['duplicate_ids_in_run']}")
        if r["missing_ids"]:
            print(f"  WARNING missing ids:   {r['missing_ids']}")
        if r["unexpected_extra_ids"]:
            print(f"  WARNING extra ids:     {r['unexpected_extra_ids']}")
        print("  Per-site detail on the 4 hard sites:")
        for d in r["detail"]:
            if d["id"] in NO_SINGLE_LINE_FIX:
                print(f"    {d['id']}: verdict={d.get('verdict')} class={d['class']}")
                if d["class"] == "locally-plausible-but-globally-wrong":
                    print(f"      proposed: {d.get('proposed_line')!r}")

    with open(os.path.join(BASE, "score_output.json"), "w") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
