"""Score targetB_diluted fix-generation runs.

Same 20 sites, same required v2 lines as targetB_small (the diluted host is
a byte-identical copy of the same 5 repos under host/integrations/) --
reuses the answer key from ../score.py rather than re-transcribing it, to
remove one source of hand-copy error.
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(BASE))
from score import REQUIRED, LEGITIMATE_HEDGE_OK, classify  # noqa: E402

ALL_IDS = set(REQUIRED)


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

    for site_id, required_line in REQUIRED.items():
        item = by_id.get(site_id)
        if item is None:
            results.append({"id": site_id, "verdict": "MISSING_FROM_RUN", "class": "wrong"})
            continue
        verdict = item.get("verdict")
        if verdict == "FIX":
            cls = classify(item.get("proposed_line"), required_line)
        elif verdict == "FLAG-FOR-HUMAN":
            cls = "hedge-legitimate" if site_id in LEGITIMATE_HEDGE_OK else "hedge-avoidable"
        elif verdict == "SKIP":
            cls = "wrong-skip"
        else:
            cls = "wrong-unknown-verdict"
        results.append({
            "id": site_id, "verdict": verdict, "class": cls,
            "proposed_line": item.get("proposed_line"), "required_line": required_line,
            "reason": item.get("reason"),
        })

    n = len(REQUIRED)
    n_exact = sum(1 for r in results if r["class"] == "exact")
    n_semantic = sum(1 for r in results if r["class"] == "semantic-equivalent")
    n_hedge_legit = sum(1 for r in results if r["class"] == "hedge-legitimate")
    n_hedge_avoid = sum(1 for r in results if r["class"] == "hedge-avoidable")
    n_wrong = n - n_exact - n_semantic - n_hedge_legit - n_hedge_avoid

    return {
        "run_file": os.path.basename(run_path), "n_sites": n,
        "exact_match_rate": n_exact / n, "semantic_equivalent_rate": n_semantic / n,
        "legitimate_hedge_rate": n_hedge_legit / n, "avoidable_hedge_rate": n_hedge_avoid / n,
        "wrong_rate": n_wrong / n,
        "duplicate_ids_in_run": dup_ids, "missing_ids": sorted(missing_ids),
        "unexpected_extra_ids": sorted(extra_ids), "detail": results,
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
        print(f"  exact-match:          {r['exact_match_rate']:.1%}")
        print(f"  semantic-equivalent:   {r['semantic_equivalent_rate']:.1%}")
        print(f"  legitimate hedge:      {r['legitimate_hedge_rate']:.1%}")
        print(f"  avoidable hedge:       {r['avoidable_hedge_rate']:.1%}")
        print(f"  wrong:                 {r['wrong_rate']:.1%}")
        if r["duplicate_ids_in_run"]:
            print(f"  WARNING duplicate ids: {r['duplicate_ids_in_run']}")
        if r["missing_ids"]:
            print(f"  WARNING missing ids:   {r['missing_ids']}")
        if r["unexpected_extra_ids"]:
            print(f"  WARNING extra ids:     {r['unexpected_extra_ids']}")
        wrong_detail = [d for d in r["detail"] if d["class"] in ("wrong", "wrong-skip", "wrong-unknown-verdict")]
        if wrong_detail:
            print("  WRONG sites:")
            for d in wrong_detail:
                print(f"    {d['id']}: verdict={d.get('verdict')} proposed={d.get('proposed_line')!r} required={d.get('required_line')!r}")

    with open(os.path.join(BASE, "score_output.json"), "w") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
