# MIGRATION SPEC — OpenAI Python SDK v0.x → v1.x

(As given verbatim to each Target A detection agent on 2026-08-18. The
original session's spec text was never persisted anywhere on disk, so this
is a reconstruction — written by the orchestrator from the confirmed-changed
/ confirmed-out-of-scope facts already stated in `ground_truth.md`, which
the agents never saw. See `rule_test.md` for the disclosure of what that
implies for interpreting this run.)

The following are the ONLY confirmed breaking changes in this migration.
Anything not described below is unaffected.

1. Module-level client configuration is removed. Assigning `openai.api_key
   = ...`, `openai.api_base = ...`, or `openai.organization = ...` as bare
   module-level attribute assignments no longer configures the client in
   v1 — these must be replaced by constructing an explicit client object
   (e.g. `client = OpenAI(api_key=...)`).
2. All module-level namespaced call patterns of the form
   `openai.<Namespace>.create(...)` (and equivalent `.list(...)`/
   `.retrieve(...)` calls) — e.g. `openai.ChatCompletion.create(...)`,
   `openai.Completion.create(...)`, `openai.Embedding.create(...)`,
   `openai.Image.create(...)`, `openai.Moderation.create(...)` — are
   removed in v1. These must migrate to client-based calls (e.g.
   `client.chat.completions.create(...)`).
3. The `openai.error` submodule is removed. Exception classes that used to
   live there (`openai.error.RateLimitError`, `openai.error.
   ServiceUnavailableError`, `openai.error.InvalidRequestError`,
   `openai.error.AuthenticationError`, etc.) now live at the top level of
   the `openai` package instead (e.g. `openai.RateLimitError`). Any
   reference to `openai.error.*` needs to change.

EXPLICITLY OUT OF SCOPE for this migration (do not flag): response-object
access patterns, i.e. whether code reads a response via dict-style
(`response['choices']`) or attribute-style (`response.choices`) access.
Both remain valid; this migration does not touch that.

TASK: Find every call site in the assigned repository that needs to be
edited because of this migration. This includes sites reached indirectly
through the repo's own helper functions — trace call chains, don't just
grep the entry point file. For each site, report the file (relative to
repo root), line number, the exact code snippet, and why it needs to
change.
