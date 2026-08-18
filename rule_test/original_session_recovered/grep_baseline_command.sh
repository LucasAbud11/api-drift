#!/bin/bash
# Extracted verbatim from the original session (line 327 of
# 804c3d31-60cd-454c-9433-1a6065725f24.jsonl). Re-run against the live repos
# on 2026-08-18 in the current session: reproduces 21/21 recall, 21/100
# precision (21.0%) on Target B -- matches results.md's reported 21.9% almost
# exactly (the ~1pt gap is unexplained but immaterial; see
# ablation_and_root_cause.md). Note this vocabulary has NO bare "Context"
# token -- it cannot generate a ctx:Context-style false positive at all.

cd repos

echo "=========== GREP BASELINE: TARGET A ==========="
OPENAI_BASE='openai\.ChatCompletion|openai\.Completion|openai\.Embedding|openai\.Image|openai\.Audio|openai\.Moderation|openai\.File|openai\.FineTune|openai\.Model|openai\.Engine|openai\.error\.|openai\.api_key|openai\.api_base|openai\.organization|openai\.api_version|openai\.proxy'
for repo in TomaszRewak_MAGI franalgaba_chatgpt-telegram-bot-serverless batuhantoker_Flask-OpenAI-Chatbot g0ldencybersec_sus_params; do
  echo "--- $repo ---"
  grep -rnE "$OPENAI_BASE" "$repo" --include='*.py'
done

echo
echo "=========== GREP BASELINE: TARGET B ==========="
MCP_BASE='FastMCP|fastmcp|\.isError\b|\.inputSchema\b|\.outputSchema\b|\.mimeType\b|\.nextCursor\b|\.structuredContent\b|\.serverInfo\b|\.protocolVersion\b|\.uriTemplate\b|\.listChanged\b|\.progressToken\b|get_context\(|\bhttpx\b|McpError|@mcp\.tool\(|@mcp\.resource\(|@mcp\.prompt\(|\.add_tool\(|ClientSession|StdioServerParameters|stdio_client|AnyUrl|is_binary'
for repo in tonyzorin_youtrack-mcp QAInsights_jmeter-mcp-server securityfortech_secops-mcp m0xai_trello-mcp-server danilop_MCP2Lambda; do
  echo "--- $repo ---"
  grep -rnE "$MCP_BASE" "$repo" --include='*.py'
done
