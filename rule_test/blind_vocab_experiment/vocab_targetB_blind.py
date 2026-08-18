"""Blind vocabulary for Target B (MCP SDK v1 -> v2), derived by a fresh
agent with access ONLY to the official-migration-guide text block (items
1-9 from target_b_spec.md), zero repo/GT access. Verbatim from that
agent's output -- not tuned, not edited."""

PATTERNS = {
    "1_fastmcp": r"FastMCP|mcp\.server\.fastmcp|mcp/server/fastmcp|\bContext\b",
    "2_camelcase": r"\bisError\b|\bnextCursor\b|\binputSchema\b|\boutputSchema\b|\bmimeType\b|\bstructuredContent\b|\bserverInfo\b|\bprotocolVersion\b|\buriTemplate\b|\blistChanged\b|\bprogressToken\b",
    "3_context": r"\.log\(|\bmessage\s*=|\bdata\s*=|\bextra\s*=|\bclient_id\b|get_context\(|\.debug\(|\.info\(|\.warning\(|\.error\(",
    "4_lowlevel_server": r"from mcp\.server import Server|\bServer\(|@server\.\w+\(|list_tools\(\)|on_list_tools",
    "5_client_sdk": r"ClientSession|StdioServerParameters|stdio_client|\bcursor\s*=|ClientSessionGroup|\.call_tool\(|\bargs\s*=|timedelta|get_server_capabilities\(|sampling_capabilities|roots_list_supported",
    "6_http_transport": r"httpx\.AsyncClient|httpx\.Auth",
    "7_mcperror": r"\bMcpError\b|\bMCPError\b|\bErrorData\b",
    "9_nobackchannel": r"\.elicit\(|\.sample\(|\.list_roots\(|NoBackChannelError",
}
