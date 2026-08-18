"""Blind vocabulary for Target A (openai v0.x -> v1.x), derived by a fresh
agent with access ONLY to the official-migration-guide text block (items
1-3 from target_a_spec.md), zero repo/GT access. Verbatim from that
agent's output -- not tuned, not edited."""

PATTERNS = {
    "1_namespaced_calls": r"openai\.(ChatCompletion|Completion|Embedding|Image|Audio|Moderation|File|FineTune|Model|Engine)(\.\w+)?|openai\.[A-Z]\w*\.\w+",
    "2_exceptions": r"openai\.error(\.\w+)?",
    "3_auth": r"openai\.(api_key|api_base|api_version|organization|proxy)\b",
}
