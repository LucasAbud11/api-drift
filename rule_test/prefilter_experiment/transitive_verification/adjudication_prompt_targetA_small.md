TASK: You are adjudicating a fixed, pre-generated candidate list of lines from a codebase, checking each one against the openai Python SDK's v0.x -> v1.x migration (a real, well-documented breaking change). Do NOT fix anything.

IMPORTANT — READ BEFORE STARTING: The candidate list below was produced by an exhaustive vocabulary search (grep) tuned for coverage, not precision. It is a closed, finite, complete set. **Your job is adjudication only, not search.** Do not use Grep or Glob to look for additional candidates beyond this list; the list is final. You MAY use Read on files that already appear in the list below, to see surrounding context needed to apply the counting convention -- but every verdict you produce must be about one of the 9 candidates given below, and every one of those 9 candidates must receive exactly one verdict. Do not skip any.

THE BREAKING CHANGE (official migration facts):
1. All module-level namespaced API calls move onto a client instance:
   openai.ChatCompletion.create(...)  -> client.chat.completions.create(...)
   openai.Completion.create(...)      -> client.completions.create(...)
   openai.Embedding.create(...)       -> client.embeddings.create(...)
   openai.Image.create(...)           -> client.images.generate(...)
   openai.Audio.transcribe(...)       -> client.audio.transcriptions.create(...)
   openai.Moderation.create(...)      -> client.moderations.create(...)
   openai.File.*, openai.FineTune.*, openai.Model.*, openai.Engine.* all move similarly.
   ANY `openai.<Namespace>.<method>(...)` call, anywhere, at any call depth (including inside helper functions that wrap the call), is broken.
2. Exceptions move from a submodule to the top level:
   openai.error.RateLimitError -> openai.RateLimitError (and similarly for every other exception under openai.error.*). ANY `openai.error.<X>` reference (import or usage, e.g. in an except clause) is broken.
3. Authentication moves from module-level global attribute assignment to explicit client construction:
   openai.api_key = "..."      -> client = OpenAI(api_key="...")
   openai.api_base = "..."     -> client = OpenAI(base_url="...")
   openai.organization = "..." -> client = OpenAI(organization="...")
   ANY direct assignment to openai.api_key / api_base / organization / api_version / proxy is broken.

COUNTING CONVENTION (applies to every pattern above): A site is a line that must itself be edited to fix the migration. If fixing one line (e.g. an import statement, or a module-level assignment) automatically repairs another line's behavior without that other line's own text needing to change, the other line is NOT a separate site — do not report it. Only report a line if its own text has to change.

OUTPUT CONTRACT — three buckets. For every one of the 9 candidates below, sort it into exactly one of:

- **PROPOSE**: confident this line's own text must change. Report with pattern number and reason.
- **REJECT**: confident this line does NOT need to change, and you can cite the specific fact above that settles it.
- **FLAG-UNCERTAIN**: the default when the two MANDATORY rules below apply, or when the facts above genuinely don't settle the question.

TWO MANDATORY, MECHANICAL ROUTING RULES — these override your own confidence. If a candidate matches either rule, you may NOT put it in REJECT (PROPOSE is still allowed if you are confident it IS a required site; otherwise it must go to FLAG-UNCERTAIN):

**RULE 1 (name-impersonation):** the candidate line is part of machinery that makes some OTHER piece of code's import/reference of an SDK symbol resolve to a locally-built stand-in, rather than the real installed package (e.g. a `sys.modules[...]` assignment, a `types.ModuleType(...)` construction representing an `openai.*` path, or an attribute assignment exposing a class/function under an SDK name on such a constructed object). Does NOT apply merely because a local class/function happens to share a name with an SDK symbol with no impersonation machinery involved.

**RULE 2 (test/mock path floor):** the candidate's file path contains `/tests/`, starts with `tests/`, matches `test_*.py` or `*_test.py`, or contains "mock" or "fixture" in the path/filename. Any such candidate you would otherwise REJECT must go to FLAG-UNCERTAIN instead.

CANDIDATE LIST (9 items, root: /Users/lucasabud/Projects/api-drift/repos):

```json
[
  {
    "file": "TomaszRewak_MAGI/ai.py",
    "line": 6,
    "snippet": "    openai.api_key = key",
    "duplicate_count": 3,
    "duplicate_lines": [
      6,
      51,
      64
    ]
  },
  {
    "file": "TomaszRewak_MAGI/ai.py",
    "line": 7,
    "snippet": "    response = openai.ChatCompletion.create(",
    "duplicate_count": 3,
    "duplicate_lines": [
      7,
      52,
      65
    ]
  },
  {
    "file": "g0ldencybersec_sus_params/PoC.py",
    "line": 7,
    "snippet": "openai.api_key = os.getenv(\"OPENAI_API_KEY\")"
  },
  {
    "file": "g0ldencybersec_sus_params/PoC.py",
    "line": 11,
    "snippet": "    response = openai.ChatCompletion.create("
  },
  {
    "file": "g0ldencybersec_sus_params/PoC.py",
    "line": 192,
    "snippet": "        except openai.error.RateLimitError as e:"
  },
  {
    "file": "g0ldencybersec_sus_params/PoC.py",
    "line": 201,
    "snippet": "        except openai.error.ServiceUnavailableError as e:"
  },
  {
    "file": "franalgaba_chatgpt-telegram-bot-serverless/app.py",
    "line": 41,
    "snippet": "    message = openai.ChatCompletion.create("
  },
  {
    "file": "batuhantoker_Flask-OpenAI-Chatbot/app.py",
    "line": 8,
    "snippet": "openai.api_key = \"OPENAI_API\""
  },
  {
    "file": "batuhantoker_Flask-OpenAI-Chatbot/app.py",
    "line": 48,
    "snippet": "    output = openai.ChatCompletion.create("
  }
]
```

OUTPUT FORMAT — your final response must end with a fenced ```json code block, and every one of the 9 candidates above must appear in exactly one of the three arrays below (matched by file+line):

{
  "proposed_sites": [
    {"file": "relative/path.py", "line": 12, "snippet": "exact line text", "pattern": "1|2|3", "reason": "why this needs to change"}
  ],
  "flag_uncertain": [
    {"file": "relative/path.py", "line": 20, "snippet": "exact line text", "reason": "which mandatory rule applies, or the specific ambiguity"}
  ],
  "considered_and_rejected": [
    {"file": "relative/path.py", "line": 34, "snippet": "exact line text", "reason": "why this does NOT need to change, citing the specific fact that settles it"}
  ]
}

Every one of the three top-level keys must be present in the JSON block even if a bucket is empty (use `[]`).
