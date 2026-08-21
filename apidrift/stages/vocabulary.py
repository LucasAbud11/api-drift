import json
import os

from .. import validate

_PROMPT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")

with open(os.path.join(_PROMPT_DIR, "vocabulary_system.md")) as _f:
    SYSTEM_PROMPT = _f.read()


# Structured-output schemas can't express an open-ended "object with
# arbitrary keys" (additionalProperties must be false) -- so the model
# returns a list of {name, regex} pairs instead of a name->regex mapping,
# and derive() converts that list into the dict every downstream consumer
# (grep.py, guards.py, pipeline.py, report.py) already expects.
SCHEMA = {
    "type": "object",
    "properties": {
        "patterns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "regex": {"type": "string"},
                },
                "required": ["name", "regex"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["patterns"],
    "additionalProperties": False,
}


def derive(client, guide_text, factblock):
    facts_text = "\n".join(f"{f['number']}. {f['text']}" for f in factblock["facts"])
    user_text = (
        f"Primary package: {factblock['package_name']}\n\n"
        f"FACT BLOCK:\n{facts_text}\n\n"
        f"ORIGINAL GUIDE TEXT (for reference/context only):\n{guide_text}"
    )
    result = client.complete(
        stage="vocabulary",
        system_text=SYSTEM_PROMPT,
        user_text=user_text,
        schema=SCHEMA,
        # Higher than the other stages' default: this stage's output scales
        # with (fact count x patterns-per-fact x escaped-regex length), not
        # with fact count alone, so it's the one most likely to need the
        # room. A large-guide truncation here fails loudly now (llm.py
        # checks stop_reason) rather than being misreported as bad JSON --
        # this raised ceiling buys headroom, it doesn't remove that check.
        max_tokens=16000,
        effort="high",
    )
    patterns_list = result.get("patterns") if isinstance(result, dict) else None
    if not isinstance(patterns_list, list):
        raise ValueError("derived vocabulary: 'patterns' was not a list of {name, regex} pairs")
    patterns = {}
    for item in patterns_list:
        if not isinstance(item, dict) or "name" not in item or "regex" not in item:
            raise ValueError(f"derived vocabulary: malformed pattern entry: {item!r}")
        patterns[item["name"]] = item["regex"]
    return validate.validate_vocabulary({"patterns": patterns}, what="derived vocabulary")
