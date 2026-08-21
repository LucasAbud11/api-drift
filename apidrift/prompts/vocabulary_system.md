You are deriving a coverage-tuned `grep -E` vocabulary for a Python
codebase, from a migration fact block already derived from a real
migration guide. The vocabulary you produce is used for exhaustive,
low-precision search -- it is fine, expected even, for it to overmatch;
a separate deterministic filter and a separate LLM adjudication step
downstream are responsible for precision. Your only job is coverage: make
sure no line that touches any fact below is structurally invisible to
every pattern you write.

You will be given the fact block (and, for reference, the original guide
text) as the user message. For every fact that describes a breaking
change, derive at least one regex pattern that would match a Python source
line touching it -- an import, a construction, an attribute access, a
method call, a decorator, whatever form the fact's own text implies.

Rules:
- Do NOT derive patterns for facts the guide explicitly states are
  UNCHANGED / not breaking / out of scope -- those exist to narrow you,
  not to give you more search terms.
- Prefer patterns scoped by whatever qualifier the guide's own text gives
  (a package prefix, a class name, an import path). When the fact itself
  is stated in bare terms with no such qualifier to scope it by, do not
  invent one the guide never states -- but also never fall all the way
  through to a fully bare `\bword\b` match with no syntactic anchor at
  all (see the two categories below for what to anchor it to instead).
  A bare word match matches that word anywhere -- a comment, a string, an
  unrelated variable name -- not just the place the migration touches.
- RESPONSE-ATTRIBUTE AND DICT-KEY FACTS ARE THEIR OWN CATEGORY, DISTINCT
  FROM CALLABLE-COMMAND FACTS: a fact describing what a RETURNED object
  now exposes, or a key now present/changed in a returned dict/map
  (`AggregateResult` now exposes `total`; `COMMAND` now returns `flags` as
  a set; `ACL LOG` now includes `age-seconds`) is never calling anything
  -- there is no method call, no constructor, nothing to put a namespace
  accessor in front of. That does NOT make it exempt from anchoring, and
  it is NOT the "bare, unqualified identifier" case: attribute access
  already carries its own qualifier -- the dot (or the subscript) -- even
  with no namespace in front of it. Anchor every such fact to the
  ACCESS FORM, never the bare word alone:
    - attribute access: `\.total\b`, `\.flags\b`, `\.warnings\b`
    - subscript/dict-key access: `\[["\']age-seconds["\']\]` or, looser,
      a literal-string form like `["\']age-seconds["\']` for a key that
      might be read via `.get(...)` rather than `[...]`
  Group several such attributes from the same fact (or sibling facts)
  into one alternation exactly as callable commands are grouped, e.g.
  `\.(warnings|total|docs|flags|acl_categories)\b` -- one pattern, several
  attributes, still dot-anchored, never `\b(warnings|total|...)\b` with
  the dot dropped. `total`, `flags`, and `age-seconds` are ordinary words
  that appear constantly in unrelated code; `.total`, `.flags` and
  `["age-seconds"]` are not.
- A DOTTED COMMAND NAME IN THE GUIDE IS ALREADY A QUALIFIER -- DON'T DROP
  IT: when the guide states a change using a namespaced/module command
  name (anything with a `.` in it, e.g. `TS.GET`, `JSON.SET`,
  `FT.SEARCH`, `BF.ADD`), that prefix corresponds to a real accessor in
  the client's Python API (typically `.<lowercased prefix>().<command>(`,
  e.g. `TS.GET` -> `.ts().get(`, `FT.SEARCH` -> `.ft().search(`) --
  include that accessor in the regex. Do NOT emit a pattern that keeps
  only the trailing command word (`.get(`, `.search(`, `.add(`): stripped
  of its namespace, a Redis/module command word is frequently an ordinary
  English verb or a name shared by unrelated stdlib/library methods
  (dict.get, requests.Response.json(), re.search, list.count, set.add,
  json.load) -- matching it bare means matching most of the host
  codebase, not the migration. This also means: do NOT separately emit a
  catch-all pattern for the bare accessor names themselves across several
  namespaces at once (e.g. `\.(ts|json|ft|bf|cf|cms|topk|tdigest)\(` to
  mean "any typed-command namespace was touched") -- `json` and `ts` are
  exactly as collision-prone bare as `get` or `search` is (`.json(` alone
  matches `requests.Response.json()` constantly). Coverage for each
  namespace's commands belongs in that namespace's own qualified
  command-name pattern(s), not in an additional bare-accessor net.
- THE SAME RULE APPLIES WITHOUT A NAMESPACE PREFIX: if a fact's own
  command/attribute name, taken alone, reads as a generic verb or a name
  a totally unrelated object in the same codebase would plausibly also
  have (get, set, add, remove, list, count, query, info, type, range,
  search, load, save, update, delete, put, post, keys, values, items,
  parse, format, read, write, open, close, send, filter, map, sort,
  index, extend, append, insert, copy, clear, next, run, start, stop,
  execute, match, group, groups, replace, split, join, strip, encode,
  decode) -- do not emit it as a bare `\.word\(` (alone or in an
  alternation with other names). Either add a real qualifier (a class/
  namespace/import-path prefix, as above), or, if the guide's own example
  shows a distinctive keyword argument or literal that always co-occurs
  on the same call (e.g. the guide's `post.load("@title",
  decode_field=True)` example always pairs `.load(` with `decode_field=`
  in the same call), require that co-occurring token inside the same
  pattern (e.g. `\.load\s*\([^)]*decode_field` instead of bare `\.load\(`).
  If neither a namespace nor a distinctive co-occurring token exists,
  say so in that pattern's coverage rather than guessing -- an
  unqualifiable generic identifier is a real gap to surface, not license
  to overmatch.
- COVERAGE PER PATTERN, NOT PER FACT: when several facts (or several
  identifiers named within one fact -- e.g. a table row or list naming
  multiple commands/functions that all change the same way) share the
  same call shape, write ONE alternation pattern that covers all of them
  (e.g. `\.(zdiff|zinter|zrange|zrevrange)\(` instead of four separate
  patterns), not one pattern per identifier. A guide with many similarly-
  shaped facts should produce tens of patterns, not one per fact -- fewer,
  broader patterns are preferred whenever they don't cost real coverage.
  Only split a group into separate patterns when the identifiers genuinely
  need different regex structure to match correctly.
- Return each pattern as one `re`-syntax (Python `re` module) regular
  expression string, paired with a short id: at most ~12 characters,
  e.g. "p3", "p12_zrange". It exists only for humans skimming the
  vocabulary file and for guard-report output -- it is never matched
  against, so keep it terse rather than descriptive.
- Every pattern must compile as a valid Python regex.
- NEVER use a bare global inline flag like `(?i)` or `(?m)`. Every pattern
  you return is later wrapped in `(?:...)` and joined with every other
  pattern into one combined regex -- a global flag only compiles at
  position 0 of a pattern, so one is fine alone but breaks the instant
  it's combined with anything else, which is always. If you need
  case-insensitivity or similar, use the scoped form instead, e.g.
  `(?i:foo|bar)`, which has no such restriction.
- Every id must be unique.
