# Target A spec — reinstated original (verbatim) + counting convention

The breaking-change facts (items 1-3) and the surrounding TASK/CONSTRAINTS
language below are extracted verbatim from the original session
(`rule_test/original_session_recovered/`), not reconstructed. Only the
COUNTING CONVENTION paragraph is new (added per instruction) and the JSON
output-format block replaces the original's "numbered list" instruction so
this run's output can be scored programmatically the same way as every
other run in this study — that substitution is infrastructure, not spec
content.

---

TASK: You are auditing a Python codebase for lines of code broken by the openai Python SDK's v0.x -> v1.x migration (a real, well-documented breaking change). Do NOT fix anything. Only report every line you find that is broken.

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

COUNTING CONVENTION (applies to every pattern above): A site is a line that
must itself be edited to fix the migration. If fixing one line (e.g. an
import statement, or a module-level assignment) automatically repairs
another line's behavior without that other line's own text needing to
change, the other line is NOT a separate site — do not report it. Only
report a line if its own text has to change.

YOUR TASK: search the ENTIRE codebase at {REPO_PATH} (every .py file, not just the first one you find) and report every single line affected by any of the three patterns above. Include sites reached only through helper functions or wrapper functions -- do not stop at the first occurrence in a file. For each finding, report: file path (relative to the repo root), line number, the exact line of code, and which of the 3 patterns it matches.

CONSTRAINTS:
- Restrict ALL reads, greps, and file listings to exactly this directory: {REPO_PATH} -- do not read, list, or reference any path outside it, including parent or sibling directories.
- Do not modify any files. Do not run the code. This is a read-only audit.
- Report your findings as a numbered list. Be exhaustive -- err toward reporting a borderline case rather than omitting it, but do not report something as affected if it clearly has nothing to do with any of the 3 patterns above.
- End your report with a total count of findings.

OUTPUT FORMAT (added for this study, not part of the original spec) — your
final response must end with a fenced ```json code block containing exactly
this structure, and nothing else inside that fence:

{
  "proposed_sites": [
    {"file": "relative/path.py", "line": 12, "snippet": "exact line text", "pattern": "1|2|3", "reason": "why this needs to change"}
  ],
  "considered_and_rejected": [
    {"file": "relative/path.py", "line": 34, "snippet": "exact line text", "reason": "why you decided this does NOT need to change"}
  ]
}
