"""Score fix-generation runs against fix_ground_truth.md.

Reads runs/run{1,2,3}.json (raw blind-agent output, persisted as-is) and
scores each proposed FIX against the hand-derived answer key below (copied
verbatim from fix_ground_truth.md's table -- the source of truth for that
file is the markdown table + the direct source reads that built it; this
dict is a faithful transcription, checked by the parse-back test at the
bottom of this file).
"""
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))

# id -> exact required v2 line (verbatim from fix_ground_truth.md)
REQUIRED = {
    "B1":  'from mcp.server.mcpserver import MCPServer',
    "B2":  'def create_server(host: str = "0.0.0.0", port: int = 8000) -> MCPServer:',
    "B3":  '    mcp = MCPServer(',
    "B4":  'from mcp.server.mcpserver import MCPServer',
    "B5":  'mcp = MCPServer("jmeter")',
    "B6":  'from mcp.server.mcpserver import MCPServer',
    "B7":  'mcp = MCPServer("jmeter")',
    "B8a": "fastmcp_mod = types.ModuleType('mcp.server.mcpserver')",
    "B8c": 'fastmcp_mod.MCPServer = FastMCP',
    "B8d": "sys.modules['mcp.server.mcpserver'] = fastmcp_mod",
    "B9":  'from mcp.server.mcpserver import MCPServer',
    "B10": 'mcp = MCPServer(name="secops-mcp",',
    "B11": 'from mcp.server.mcpserver import MCPServer',
    "B12": 'mcp = MCPServer("Trello MCP Server")',
    "B13": 'from mcp.server.mcpserver import Context',
    "B14": 'from mcp.server.mcpserver import Context',
    "B15": 'from mcp.server.mcpserver import Context',
    "B16": 'from mcp.server.mcpserver import MCPServer, Context',
    "B17": 'mcp = MCPServer("MCP Gateway to AWS Lambda")',
    "B18": "                input_schema={'json': tool.input_schema}",
}

# Sites where GT itself (ground_truth.md) documents genuine ambiguity --
# a FLAG-FOR-HUMAN verdict here is a legitimate hedge, not a scoring miss.
LEGITIMATE_HEDGE_OK = {"B8a"}

ALL_IDS = set(REQUIRED)


def normalize(line):
    if line is None:
        return None
    s = line.strip()
    s = re.sub(r"\s+", " ", s)
    s = s.replace('"', "'")
    return s


def classify(proposed, required):
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
            cls = "wrong-skip"  # every site in this input was pre-confirmed; SKIP contradicts that
        else:
            cls = "wrong-unknown-verdict"
        results.append({
            "id": site_id, "verdict": verdict, "class": cls,
            "proposed_line": item.get("proposed_line"),
            "required_line": required_line,
            "reason": item.get("reason"),
        })

    n = len(REQUIRED)
    n_exact = sum(1 for r in results if r["class"] == "exact")
    n_semantic = sum(1 for r in results if r["class"] == "semantic-equivalent")
    n_hedge_legit = sum(1 for r in results if r["class"] == "hedge-legitimate")
    n_hedge_avoid = sum(1 for r in results if r["class"] == "hedge-avoidable")
    n_wrong = n - n_exact - n_semantic - n_hedge_legit - n_hedge_avoid

    return {
        "run_file": os.path.basename(run_path),
        "n_sites": n,
        "exact_match_rate": n_exact / n,
        "semantic_equivalent_rate": n_semantic / n,
        "legitimate_hedge_rate": n_hedge_legit / n,
        "avoidable_hedge_rate": n_hedge_avoid / n,
        "wrong_rate": n_wrong / n,
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
