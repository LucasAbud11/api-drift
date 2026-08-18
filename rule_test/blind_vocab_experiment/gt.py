"""Ground truth for the blind-vocabulary experiment, both targets, both scales."""

GT_TARGET_A_SMALL = {
    ("TomaszRewak_MAGI/ai.py", 6), ("TomaszRewak_MAGI/ai.py", 7),
    ("TomaszRewak_MAGI/ai.py", 51), ("TomaszRewak_MAGI/ai.py", 52),
    ("TomaszRewak_MAGI/ai.py", 64), ("TomaszRewak_MAGI/ai.py", 65),
    ("franalgaba_chatgpt-telegram-bot-serverless/app.py", 41),
    ("batuhantoker_Flask-OpenAI-Chatbot/app.py", 8),
    ("batuhantoker_Flask-OpenAI-Chatbot/app.py", 48),
    ("g0ldencybersec_sus_params/PoC.py", 7),
    ("g0ldencybersec_sus_params/PoC.py", 11),
    ("g0ldencybersec_sus_params/PoC.py", 192),
    ("g0ldencybersec_sus_params/PoC.py", 201),
}
assert len(GT_TARGET_A_SMALL) == 13

GT_TARGET_A_DILUTED = {(f"integrations_openai/{f}", l) for f, l in GT_TARGET_A_SMALL}

GT_TARGET_B_SMALL = {
    ("tonyzorin_youtrack-mcp/main.py", 10), ("tonyzorin_youtrack-mcp/main.py", 25), ("tonyzorin_youtrack-mcp/main.py", 27),
    ("QAInsights_jmeter-mcp-server/main.py", 2), ("QAInsights_jmeter-mcp-server/main.py", 9),
    ("QAInsights_jmeter-mcp-server/jmeter_server.py", 4), ("QAInsights_jmeter-mcp-server/jmeter_server.py", 23),
    ("QAInsights_jmeter-mcp-server/tests/test_jmeter_server.py", 11),
    ("QAInsights_jmeter-mcp-server/tests/test_jmeter_server.py", 21),
    ("QAInsights_jmeter-mcp-server/tests/test_jmeter_server.py", 22),
    ("securityfortech_secops-mcp/main.py", 7), ("securityfortech_secops-mcp/main.py", 26),
    ("m0xai_trello-mcp-server/main.py", 6), ("m0xai_trello-mcp-server/main.py", 23),
    ("m0xai_trello-mcp-server/server/tools/board.py", 8),
    ("m0xai_trello-mcp-server/server/tools/card.py", 8),
    ("m0xai_trello-mcp-server/server/tools/list.py", 8),
    ("danilop_MCP2Lambda/main.py", 6), ("danilop_MCP2Lambda/main.py", 30),
    ("danilop_MCP2Lambda/mcp_client_bedrock/main.py", 44),
}
assert len(GT_TARGET_B_SMALL) == 20

GT_TARGET_B_DILUTED = {(f"integrations/{f}", l) for f, l in GT_TARGET_B_SMALL}
