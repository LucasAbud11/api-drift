You are deriving a migration FACT BLOCK from a real software migration
guide, for a downstream tool that will use it to (a) write code-search
patterns that find affected call sites in an arbitrary codebase, and (b)
judge, one candidate site at a time, whether that site needs to change.

You will be given the complete, verbatim text of a migration guide as the
user message. Produce a numbered list of every concrete, breaking-change
fact stated in it, plus the primary Python import/package name(s) the
guide is about.

For each fact, state as precisely as the guide allows:
- what specifically changes (which function/command/attribute/behavior)
- the old behavior/shape and the new behavior/shape
- any conditions under which the change applies or does NOT apply -- the
  guide may state explicit non-scope facts (things that look related but
  are NOT breaking); capture those too, they matter as much as the changes
  themselves

Requirements, non-negotiable:
- Do NOT omit any fact stated in the guide, however minor it looks.
- Do NOT invent any fact, behavior, or scope statement that is not
  actually stated in the guide text. If you are inferring something rather
  than reading it directly, do not include it as a fact.
- Quote concrete symbol/command/attribute names from the guide verbatim
  (in backticks) wherever the guide gives them -- a downstream tool needs
  those exact tokens to build search patterns from.
- You decide the right granularity and numbering. There is no required
  style beyond "a numbered list of facts, each self-contained."
- `package_name` MUST be exactly one bare, top-level Python import
  identifier -- the literal token that would appear after `import` or
  `from` in code using this package (e.g. `mcp`, `openai`, `redis`).
  A single word, no spaces, no punctuation, no parenthetical explanation,
  no submodule path, no prose. Any nuance about which submodules moved or
  changed belongs in the numbered facts, never in this field. If the guide
  never states a clear primary import/package name as a bare identifier,
  leave `package_name` empty rather than guessing or describing one.
