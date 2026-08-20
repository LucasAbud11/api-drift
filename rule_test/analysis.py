import re, os, json
from collections import defaultdict

REPO_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "repos")

# ---------------------------------------------------------------------------
# GROUND TRUTH  (transcribed verbatim from ground_truth/ground_truth.md)
# key = (repo_dirname, relpath, line)  -> class
# ---------------------------------------------------------------------------

GT = {}

def gt(repo, path, line, cls, target):
    GT[(target, repo, path, line)] = cls

# --- TARGET A ---
gt("TomaszRewak_MAGI", "ai.py", 6, "helper-wrapped", "A")
gt("TomaszRewak_MAGI", "ai.py", 7, "helper-wrapped", "A")
gt("TomaszRewak_MAGI", "ai.py", 51, "helper-wrapped", "A")
gt("TomaszRewak_MAGI", "ai.py", 52, "helper-wrapped", "A")
gt("TomaszRewak_MAGI", "ai.py", 64, "helper-wrapped", "A")
gt("TomaszRewak_MAGI", "ai.py", 65, "helper-wrapped", "A")
gt("franalgaba_chatgpt-telegram-bot-serverless", "app.py", 41, "helper-wrapped", "A")
gt("batuhantoker_Flask-OpenAI-Chatbot", "app.py", 8, "literal", "A")
gt("batuhantoker_Flask-OpenAI-Chatbot", "app.py", 48, "helper-wrapped", "A")
gt("g0ldencybersec_sus_params", "PoC.py", 7, "literal", "A")
gt("g0ldencybersec_sus_params", "PoC.py", 11, "helper-wrapped", "A")
gt("g0ldencybersec_sus_params", "PoC.py", 192, "literal", "A")
gt("g0ldencybersec_sus_params", "PoC.py", 201, "literal", "A")

# --- TARGET B ---
gt("tonyzorin_youtrack-mcp", "main.py", 10, "literal", "B")
gt("tonyzorin_youtrack-mcp", "main.py", 25, "literal", "B")
gt("tonyzorin_youtrack-mcp", "main.py", 27, "literal", "B")

gt("QAInsights_jmeter-mcp-server", "main.py", 2, "literal", "B")
gt("QAInsights_jmeter-mcp-server", "main.py", 9, "literal", "B")
gt("QAInsights_jmeter-mcp-server", "jmeter_server.py", 4, "literal", "B")
gt("QAInsights_jmeter-mcp-server", "jmeter_server.py", 23, "literal", "B")
gt("QAInsights_jmeter-mcp-server", "tests/test_jmeter_server.py", 11, "test/mock", "B")
gt("QAInsights_jmeter-mcp-server", "tests/test_jmeter_server.py", 12, "test/mock", "B")
gt("QAInsights_jmeter-mcp-server", "tests/test_jmeter_server.py", 21, "test/mock", "B")
gt("QAInsights_jmeter-mcp-server", "tests/test_jmeter_server.py", 22, "test/mock", "B")

gt("securityfortech_secops-mcp", "main.py", 7, "literal", "B")
gt("securityfortech_secops-mcp", "main.py", 26, "literal", "B")

gt("m0xai_trello-mcp-server", "main.py", 6, "literal", "B")
gt("m0xai_trello-mcp-server", "main.py", 23, "literal", "B")
gt("m0xai_trello-mcp-server", "server/tools/board.py", 8, "literal", "B")
gt("m0xai_trello-mcp-server", "server/tools/card.py", 8, "literal", "B")
gt("m0xai_trello-mcp-server", "server/tools/list.py", 8, "literal", "B")

gt("danilop_MCP2Lambda", "main.py", 6, "literal", "B")
gt("danilop_MCP2Lambda", "main.py", 30, "literal", "B")
gt("danilop_MCP2Lambda", "mcp_client_bedrock/main.py", 44, "client-side", "B")

GT_A = {k: v for k, v in GT.items() if k[0] == "A"}
GT_B = {k: v for k, v in GT.items() if k[0] == "B"}
assert len(GT_A) == 13, len(GT_A)
assert len(GT_B) == 21, len(GT_B)

# ---------------------------------------------------------------------------
# CANDIDATE GENERATION -- GREP (naive full-tree vocabulary grep, word-boundary
# safe, per methodology_notes.md's documented search procedure). Re-run fresh
# against the actual repo trees since the original raw grep output was not
# persisted anywhere in this repo.
# ---------------------------------------------------------------------------

TARGET_A_REPOS = [
    "TomaszRewak_MAGI",
    "franalgaba_chatgpt-telegram-bot-serverless",
    "batuhantoker_Flask-OpenAI-Chatbot",
    "g0ldencybersec_sus_params",
]
TARGET_B_REPOS = [
    "tonyzorin_youtrack-mcp",
    "QAInsights_jmeter-mcp-server",
    "securityfortech_secops-mcp",
    "m0xai_trello-mcp-server",
    "danilop_MCP2Lambda",
]

VOCAB_A = [
    ("import_openai",   r"^\s*import\s+openai\b"),
    ("import_openai2",  r"^\s*from\s+openai\s+import"),
    ("openai_create",   r"openai\.\w+\.create\("),
    ("openai_error",    r"openai\.error\."),
    ("openai_attr",     r"openai\.(api_key|api_base|organization)\s*="),
]

VOCAB_B = [
    ("import_fastmcp",   r"^\s*from\s+mcp\.server\.fastmcp\s+import"),
    ("import_fastmcp2",  r"^\s*import\s+mcp\.server\.fastmcp"),
    ("fastmcp_path_str", r"mcp\.server\.fastmcp"),
    ("FastMCP_token",    r"\bFastMCP\b"),
    ("Context_token",    r"\bContext\b"),
    ("inputSchema",      r"\binputSchema\b"),
    ("ClientSessionGroup", r"\bClientSessionGroup\b"),
    ("ClientSession",    r"\bClientSession\b"),
    ("stdio_client",     r"\bstdio_client\b"),
    ("StdioServerParameters", r"\bStdioServerParameters\b"),
    ("mcp_tool_decorator", r"@mcp\.tool\("),
    ("mcp_resource_decorator", r"@mcp\.resource\("),
    ("mcp_prompt_decorator", r"@mcp\.prompt\("),
    ("add_tool",         r"\.add_tool\("),
    ("httpx_token",      r"\bhttpx\b"),
    ("get_context",      r"\bget_context\("),
    ("ctx_error",        r"ctx\.error\("),
    ("ctx_info",         r"ctx\.info\("),
    ("mcp_types",        r"\bmcp\.types\b"),
]

def scan_repo(repo, vocab):
    repo_path = os.path.join(REPO_ROOT, repo)
    hits = []
    for dirpath, dirnames, filenames in os.walk(repo_path):
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            fpath = os.path.join(dirpath, fn)
            relpath = os.path.relpath(fpath, repo_path)
            try:
                with open(fpath, errors="ignore") as f:
                    lines = f.readlines()
            except Exception:
                continue
            for i, line in enumerate(lines, start=1):
                tags = [tag for tag, pat in vocab if re.search(pat, line)]
                if tags:
                    hits.append({"repo": repo, "file": relpath, "line": i,
                                 "tags": tags, "snippet": line.rstrip("\n")})
    return hits

grep_hits_A = []
for r in TARGET_A_REPOS:
    grep_hits_A += scan_repo(r, VOCAB_A)
grep_hits_B = []
for r in TARGET_B_REPOS:
    grep_hits_B += scan_repo(r, VOCAB_B)

def to_candidates(hits, target):
    cands = {}
    for h in hits:
        key = (target, h["repo"], h["file"], h["line"])
        cands.setdefault(key, {"tags": set(), "snippet": h["snippet"]})
        cands[key]["tags"] |= set(h["tags"])
    return cands

GREP_A = to_candidates(grep_hits_A, "A")
GREP_B = to_candidates(grep_hits_B, "B")

# ---------------------------------------------------------------------------
# CANDIDATE GENERATION -- AGENT (reconstructed).
# Per results.md: agent recall was 100%/100% on every class, both targets --
# i.e. agent's proposed set == GT exactly, for target A (13/13, 0 FP) and for
# target B's non-literal classes. Target B literal precision was 48.5%
# (16 GT / 33 proposed) and results.md documents, with exact counts, the
# single systematic mechanism behind every one of the 17 FPs: `ctx: Context`
# style function-signature annotations flagged as separately-broken in m0xai
# (14 instances) and danilop (3 instances) = 17, matching the reported gap
# exactly. Verified directly against the live repos above (14 in m0xai, 3 in
# danilop -- see grep run). Reconstruction = GT UNION these 17 verified sites.
# ---------------------------------------------------------------------------

AGENT_B_EXTRA_FP = [
    ("m0xai_trello-mcp-server", "server/tools/board.py", 20),
    ("m0xai_trello-mcp-server", "server/tools/board.py", 41),
    ("m0xai_trello-mcp-server", "server/tools/board.py", 59),
    ("m0xai_trello-mcp-server", "server/tools/board.py", 80),
    ("m0xai_trello-mcp-server", "server/tools/list.py", 20),
    ("m0xai_trello-mcp-server", "server/tools/list.py", 41),
    ("m0xai_trello-mcp-server", "server/tools/list.py", 63),
    ("m0xai_trello-mcp-server", "server/tools/list.py", 87),
    ("m0xai_trello-mcp-server", "server/tools/list.py", 109),
    ("m0xai_trello-mcp-server", "server/tools/card.py", 21),
    ("m0xai_trello-mcp-server", "server/tools/card.py", 42),
    ("m0xai_trello-mcp-server", "server/tools/card.py", 63),
    ("m0xai_trello-mcp-server", "server/tools/card.py", 87),
    ("m0xai_trello-mcp-server", "server/tools/card.py", 112),
    ("danilop_MCP2Lambda", "main.py", 68),
    ("danilop_MCP2Lambda", "main.py", 94),
    ("danilop_MCP2Lambda", "main.py", 136),
]
assert len(AGENT_B_EXTRA_FP) == 17

def read_line(repo, path, line):
    fpath = os.path.join(REPO_ROOT, repo, path)
    with open(fpath, errors="ignore") as f:
        lines = f.readlines()
    return lines[line - 1].rstrip("\n")

def tags_for(snippet, vocab):
    return {tag for tag, pat in vocab if re.search(pat, snippet)}

# SUPERSEDED -- kept only for audit trail, NOT used for scoring below.
# This was flagged (correctly) as circular: it was built as GT UNION the one
# documented FP mechanism, then scored against a rule targeting that exact
# mechanism, so its "100% after rule" result was guaranteed by construction,
# not measured. Real agents were re-run from scratch (see agent_runs/*.json)
# to replace this.
AGENT_A_RECONSTRUCTED = {}
for (target, repo, path, line), cls in GT_A.items():
    snippet = read_line(repo, path, line)
    AGENT_A_RECONSTRUCTED[(target, repo, path, line)] = {"tags": tags_for(snippet, VOCAB_A), "snippet": snippet}

AGENT_B_RECONSTRUCTED = {}
for (target, repo, path, line), cls in GT_B.items():
    snippet = read_line(repo, path, line)
    AGENT_B_RECONSTRUCTED[(target, repo, path, line)] = {"tags": tags_for(snippet, VOCAB_B), "snippet": snippet}
for repo, path, line in AGENT_B_EXTRA_FP:
    snippet = read_line(repo, path, line)
    AGENT_B_RECONSTRUCTED[("B", repo, path, line)] = {"tags": tags_for(snippet, VOCAB_B), "snippet": snippet}

# ---------------------------------------------------------------------------
# REAL agent output -- loaded from the persisted raw JSON files in
# rule_test/agent_runs/, one per repo, written immediately after each of the
# 9 freshly-launched, walled-off agents reported back, before any scoring.
# This is the actual measurement.
# ---------------------------------------------------------------------------

AGENT_RUNS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_runs")

def load_agent_runs():
    agent_a, agent_b = {}, {}
    for fn in sorted(os.listdir(AGENT_RUNS_DIR)):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(AGENT_RUNS_DIR, fn)) as f:
            run = json.load(f)
        target = run["target"]
        repo = run["repo"]
        vocab = VOCAB_A if target == "A" else VOCAB_B
        dest = agent_a if target == "A" else agent_b
        for site in run["proposed_sites"]:
            key = (target, repo, site["file"], site["line"])
            snippet = site.get("snippet", "")
            dest[key] = {"tags": tags_for(snippet, vocab), "snippet": snippet,
                         "reason": site.get("reason", "")}
    return agent_a, agent_b

AGENT_A_REAL, AGENT_B_REAL = load_agent_runs()

# Primary names used by the scoring/report section below point at the REAL
# data. The reconstructed dicts remain defined above for anyone auditing the
# earlier (circular) analysis.
AGENT_A = AGENT_A_REAL
AGENT_B = AGENT_B_REAL

# ---------------------------------------------------------------------------
# THE RULE: "definition/import site" vs "usage site of a name that came from
# a broken import". Implemented as TWO versions:
#
#  STRICT  -- correctly scoped. Requires knowing, per symbol, whether the
#             identifier text itself was renamed (FastMCP->MCPServer: usage
#             sites DO need a separate edit, keep) vs only the import PATH
#             moved while the bound name stayed identical (Context: usage
#             sites resolve automatically once the import is fixed, filter).
#             This is exactly the mechanism results.md documents.
#
#  NAIVE   -- the literal blanket reading of the sentence in results.md:
#             "usage sites of a name that came from a broken import ...
#             resolves automatically once the import is fixed" applied to
#             ANY name reached through a migration-relevant import, without
#             checking whether that identifier's text changed. This is the
#             version that "threatens the product": it cannot tell FastMCP
#             (must change at every call site) from Context (only the import
#             needs to change) from `openai` (must change at every call site,
#             and never even has an import-statement candidate to anchor on).
# ---------------------------------------------------------------------------

RENAMED_SYMBOLS_B = {"FastMCP_token"}      # identifier text itself changes -> keep usage sites
MOVED_ONLY_SYMBOLS_B = {"Context_token"}   # identifier text unchanged -> filter usage sites
IMPORT_TAGS_B = {"import_fastmcp", "import_fastmcp2"}
# strict rule also treats a literal reference to the broken module-path
# STRING (e.g. `sys.modules['mcp.server.fastmcp']`) as an anchor, since the
# string itself IS the stale path, not a downstream usage of an imported
# name. The naive rule below deliberately does NOT special-case this --
# a sloppy "import line vs everything else" implementation has no reason to.
ANCHOR_TAGS_B = IMPORT_TAGS_B | {"fastmcp_path_str"}

IMPORT_TAGS_A = {"import_openai", "import_openai2"}
# every other Target-A tag (openai_create/openai_error/openai_attr) is a
# *usage* of the name `openai`, which is imported by a plain `import openai`
# statement never itself flagged as a breaking site.

def is_import_line(snippet):
    return bool(re.match(r"^\s*(from|import)\s", snippet))

def apply_rule_strict(candidates, target):
    kept = {}
    for key, data in candidates.items():
        tags = data["tags"]
        if target == "B":
            if tags & ANCHOR_TAGS_B or is_import_line(data.get("snippet", "")):
                kept[key] = data; continue
            if tags & RENAMED_SYMBOLS_B:
                kept[key] = data; continue
            if tags & MOVED_ONLY_SYMBOLS_B and not (tags - MOVED_ONLY_SYMBOLS_B - {"GT"}):
                continue  # filtered: pure usage of an unchanged-name symbol
            if tags & MOVED_ONLY_SYMBOLS_B:
                # co-occurs with other relevant tags on the same line -> keep
                kept[key] = data; continue
            kept[key] = data
        else:  # target A -- strict rule has no renamed-vs-moved table for
               # `openai`, and no import-statement candidate other than the
               # plain `import openai` line ever appears as a proposed site
               # in practice, so it has nothing to act on: passthrough.
            kept[key] = data
    return kept

def apply_rule_naive(candidates, target):
    """Blanket version: filter EVERY non-import candidate that is a mere
    reference to a name belonging to the migrated package, regardless of
    whether that name's own text changed."""
    kept = {}
    for key, data in candidates.items():
        tags = data["tags"]
        if target == "B":
            if tags & IMPORT_TAGS_B or is_import_line(data.get("snippet", "")):
                kept[key] = data
            # everything else (FastMCP usage, Context usage, inputSchema,
            # ClientSession*, decorators, add_tool, httpx, ctx.*, mcp.types)
            # is treated as "just a usage site" and dropped.
        else:
            if tags & IMPORT_TAGS_A or is_import_line(data.get("snippet", "")):
                kept[key] = data
            # openai_create / openai_error / openai_attr are ALL usages of
            # the name `openai` -> dropped under the blanket reading.
    return kept

# ---------------------------------------------------------------------------
# HEURISTIC CLASS-BUCKETING FOR *PROPOSED* CANDIDATES (needed for per-class
# precision -- ground truth only tells us the class of real sites; a false
# positive still needs a bucket to compute "precision within literal", etc.
# Applies the same ordered rule ground_truth.md states for GT assignment:
# test/mock > client-side > decorator/registration > dynamic/reflection >
# literal/helper-wrapped (depth not recoverable from a single grep line, so
# collapsed to "literal" for FP bucketing -- noted in the report).
# ---------------------------------------------------------------------------

DECORATOR_TAGS = {"mcp_tool_decorator", "mcp_resource_decorator",
                   "mcp_prompt_decorator", "add_tool"}
CLIENT_DIR_MARKERS = ("mcp_client_bedrock",)

def classify_candidate(repo, file, tags, snippet):
    if "test" in file.lower():
        return "test/mock"
    if any(m in file for m in CLIENT_DIR_MARKERS):
        return "client-side"
    if tags & DECORATOR_TAGS:
        return "decorator/registration"
    if re.search(r"getattr\(|\bdir\(|importlib|globals\(\)|locals\(\)", snippet):
        return "dynamic/reflection"
    return "literal"

# ---------------------------------------------------------------------------
# SCORING
# ---------------------------------------------------------------------------

def score(candidates, gt_dict, target, label, verbose=True):
    gt_keys = set(gt_dict.keys())
    cand_keys = set(candidates.keys())
    tp = gt_keys & cand_keys
    fp = cand_keys - gt_keys
    fn = gt_keys - cand_keys

    all_classes = ["literal", "helper-wrapped", "decorator/registration",
                    "dynamic/reflection", "test/mock", "client-side"]

    # bucket every PROPOSED candidate (TP or FP) by heuristic class for precision
    cand_class = {}
    for k in cand_keys:
        _, repo, file, line = k
        if k in gt_dict:
            cand_class[k] = gt_dict[k]        # true positive: use real class
        else:
            tags = candidates[k].get("tags", set())
            snippet = candidates[k].get("snippet", "")
            cand_class[k] = classify_candidate(repo, file, tags, snippet)

    rows = []
    for cls in all_classes:
        gt_in_cls = {k for k in gt_keys if gt_dict[k] == cls}
        cand_in_cls = {k for k in cand_keys if cand_class[k] == cls}
        if not gt_in_cls and not cand_in_cls:
            continue
        tp_cls = gt_in_cls & cand_keys
        rows.append((cls, len(gt_in_cls), len(tp_cls), len(cand_in_cls)))

    if cand_keys:
        prec = len(tp) / len(cand_keys) * 100
    else:
        prec = float('nan')
    rec = len(tp) / len(gt_keys) * 100 if gt_keys else float('nan')

    if verbose:
        print(f"\n=== {label} | Target {target} ===")
        print(f"GT total={len(gt_keys)}  Proposed total={len(cand_keys)}  TP={len(tp)}  FP={len(fp)}  FN={len(fn)}")
        print(f"Overall recall = {len(tp)}/{len(gt_keys)} = {rec:.1f}%   "
              f"Overall precision = {len(tp)}/{len(cand_keys) if cand_keys else 0} = {prec:.1f}%")
        for cls, ngt, ntp, nprop in rows:
            r = f"{ntp}/{ngt} ({ntp/ngt*100:.0f}%)" if ngt else "N/A (0 GT)"
            p = f"{ntp}/{nprop} ({ntp/nprop*100:.0f}%)" if nprop else "N/A (0 proposed)"
            print(f"  class={cls:24s} recall={r:16s} precision={p}")
        if fn:
            print("  MISSED GT sites (false negatives):")
            for k in sorted(fn):
                print(f"    {k[1]}/{k[2]}:{k[3]}  [{gt_dict[k]}]")
    return {"tp": tp, "fp": fp, "fn": fn, "cand_keys": cand_keys, "gt_keys": gt_keys,
            "rows": rows, "recall": rec, "precision": prec}


print("#" * 70)
print("BASELINES (no rule) -- REAL agent output, loaded from agent_runs/*.json")
print("#" * 70)
score(GREP_A, GT_A, "A", "GREP raw")
score(GREP_B, GT_B, "B", "GREP raw")
score(AGENT_A, GT_A, "A", "AGENT raw (REAL, fresh run)")
score(AGENT_B, GT_B, "B", "AGENT raw (REAL, fresh run)")

print("\n" + "#" * 70)
print("RULE = STRICT (correctly scoped: renamed-identifier table)")
print("#" * 70)
score(apply_rule_strict(GREP_A, "A"), GT_A, "A", "GREP + rule(strict)")
score(apply_rule_strict(GREP_B, "B"), GT_B, "B", "GREP + rule(strict)")
score(apply_rule_strict(AGENT_A, "A"), GT_A, "A", "AGENT(REAL) + rule(strict)")
score(apply_rule_strict(AGENT_B, "B"), GT_B, "B", "AGENT(REAL) + rule(strict)")

print("\n" + "#" * 70)
print("RULE = NAIVE (blanket 'usage of a name from a migrated import' filter)")
print("#" * 70)
score(apply_rule_naive(GREP_A, "A"), GT_A, "A", "GREP + rule(naive)")
score(apply_rule_naive(GREP_B, "B"), GT_B, "B", "GREP + rule(naive)")
score(apply_rule_naive(AGENT_A, "A"), GT_A, "A", "AGENT(REAL) + rule(naive)")
score(apply_rule_naive(AGENT_B, "B"), GT_B, "B", "AGENT(REAL) + rule(naive)")

print("\n" + "#" * 70)
print("SUPERSEDED -- circular reconstruction from prior turn, kept for audit only")
print("#" * 70)
score(AGENT_A_RECONSTRUCTED, GT_A, "A", "AGENT raw (SUPERSEDED reconstruction)")
score(AGENT_B_RECONSTRUCTED, GT_B, "B", "AGENT raw (SUPERSEDED reconstruction)")
score(apply_rule_strict(AGENT_A_RECONSTRUCTED, "A"), GT_A, "A", "AGENT(SUPERSEDED) + rule(strict)")
score(apply_rule_strict(AGENT_B_RECONSTRUCTED, "B"), GT_B, "B", "AGENT(SUPERSEDED) + rule(strict)")

# Determinism check: grep is a pure function of the repo tree + vocabulary,
# re-run it a second time in-process and diff against the first pass.
grep_hits_A2 = []
for r in TARGET_A_REPOS:
    grep_hits_A2 += scan_repo(r, VOCAB_A)
grep_hits_B2 = []
for r in TARGET_B_REPOS:
    grep_hits_B2 += scan_repo(r, VOCAB_B)
GREP_A2 = to_candidates(grep_hits_A2, "A")
GREP_B2 = to_candidates(grep_hits_B2, "B")
print("\n" + "#" * 70)
print("DETERMINISM CHECK: re-running my own grep script a second time")
print("#" * 70)
print(f"Target A: identical candidate set to first pass? {set(GREP_A.keys()) == set(GREP_A2.keys())}")
print(f"Target B: identical candidate set to first pass? {set(GREP_B.keys()) == set(GREP_B2.keys())}")
