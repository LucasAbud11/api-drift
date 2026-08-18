"""
Coverage-tuned candidate generator for the grep+adjudicate composition
experiment. Precision is deliberately irrelevant here -- this is a plain
vocabulary substring/regex search over every .py file in the target
directory, with no context-awareness (no import-path checking, no
distinguishing app-level vs SDK-level usage). Its only job is to be a
superset of every true site; the agent adjudicates precision downstream.

Vocabulary covers all 9 breaking-change patterns from the migration guide
(target_b_spec.md), broadened from the original recovered baseline
(rule_test/original_session_recovered/grep_baseline_command.sh) by adding
a bare `Context` term -- the original baseline's own comment notes it
deliberately had none, which is exactly the coverage gap this experiment
needs closed (the scale host's one decoy is a bare `Context` collision).
"""
import json
import os
import re
import sys

PATTERNS = {
    "1_fastmcp": r"FastMCP|fastmcp",
    "2_camelcase": r"\.isError\b|\.inputSchema\b|\.outputSchema\b|\.mimeType\b|\.nextCursor\b|\.structuredContent\b|\.serverInfo\b|\.protocolVersion\b|\.uriTemplate\b|\.listChanged\b|\.progressToken\b",
    "3_context": r"\bContext\b|get_context\(|client_id",
    "4_decorators_lowlevel": r"@mcp\.tool\(|@mcp\.resource\(|@mcp\.prompt\(|@mcp\.completion\(|\.add_tool\(|mcp\.server import Server\b",
    "5_client_sdk": r"ClientSession|StdioServerParameters|stdio_client|ClientSessionGroup|get_server_capabilities|cursor\s*=",
    "6_httpx": r"\bhttpx\b",
    "7_mcperror": r"McpError|ErrorData",
    "9_backchannel": r"\.elicit\(|\.sample\(|\.list_roots\(|NoBackChannelError",
}

COMBINED = re.compile("|".join(f"(?:{p})" for p in PATTERNS.values()))


def find_candidates(root_dir, restrict_to_relpaths=None):
    """Walk root_dir for .py files, grep every line against COMBINED.
    Returns a list of {file, line, snippet} with file relative to root_dir.
    restrict_to_relpaths, if given, is a set of top-level relative dir
    prefixes to include (used to scope the small-scale run to just the
    5 target repos when they share a parent dir with other things)."""
    results = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, root_dir)
            if restrict_to_relpaths is not None:
                if not any(rel == r or rel.startswith(r + os.sep) for r in restrict_to_relpaths):
                    continue
            try:
                with open(full, encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
            except OSError:
                continue
            for i, line in enumerate(lines, start=1):
                if COMBINED.search(line):
                    results.append({"file": rel, "line": i, "snippet": line.rstrip("\n")})
    return results


def main():
    if len(sys.argv) < 3:
        print("usage: python grep_candidates.py <root_dir> <output.json> [restrict_prefix ...]")
        sys.exit(1)
    root_dir = sys.argv[1]
    out_path = sys.argv[2]
    restrict = set(sys.argv[3:]) if len(sys.argv) > 3 else None

    candidates = find_candidates(root_dir, restrict)
    with open(out_path, "w") as f:
        json.dump(candidates, f, indent=2)

    by_top = {}
    for c in candidates:
        top = c["file"].split(os.sep)[0]
        by_top[top] = by_top.get(top, 0) + 1
    print(f"Total candidates: {len(candidates)}")
    for top, n in sorted(by_top.items()):
        print(f"  {top}: {n}")
    print(f"Written to {out_path}")


if __name__ == "__main__":
    main()
