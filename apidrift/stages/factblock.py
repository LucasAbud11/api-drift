import os

from .. import validate

_PROMPT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")

with open(os.path.join(_PROMPT_DIR, "factblock_system.md")) as _f:
    SYSTEM_PROMPT = _f.read()

SCHEMA = {
    "type": "object",
    "properties": {
        "package_name": {"type": "string"},
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "number": {"type": "integer"},
                    "text": {"type": "string"},
                },
                "required": ["number", "text"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["package_name", "facts"],
    "additionalProperties": False,
}


def derive(client, guide_text):
    """Returns a validated fact-block dict: {"package_name": str, "facts": [...]}.
    Raises ValueError (via validate.validate_factblock) on anything short
    of a well-formed, non-empty result -- never returns a partial one."""
    result = client.complete(
        stage="factblock",
        system_text=SYSTEM_PROMPT,
        user_text=guide_text,
        schema=SCHEMA,
        # Raised from 8000 after a real large guide (MCP v1->v2, ~76k input
        # tokens) hit the ceiling -- this stage's output scales with the
        # guide's own size (one fact per guide-stated change), so a big
        # guide can legitimately need more room than a small one ever
        # would. Same headroom rationale as vocabulary.py's 16000; llm.py's
        # stop_reason=="max_tokens" check still catches a guide that
        # outgrows even this, loudly, rather than truncating silently.
        max_tokens=32000,
        effort="high",
    )
    return validate.validate_factblock(result, what="derived fact block")


def render_facts_text(factblock):
    """The exact text that fills {MIGRATION_FACTS} in the adjudication
    prompt -- one line per fact, numbered."""
    lines = []
    for fact in factblock["facts"]:
        lines.append(f"{fact['number']}. {fact['text']}")
    return "\n\n".join(lines)
