GAP-FILL PASS -- ADDENDUM TO THE RULES ABOVE

You already have the rules above (the same system prompt vocabulary
derivation gets). Everything there still applies -- qualification,
anti-genericity, one-pattern-per-shared-shape grouping, id length and
uniqueness. This addendum changes what you're being asked to do and
adds constraints specific to this narrower task.

WHAT THIS PASS IS: the facts below already went through vocabulary
derivation once. A deterministic coverage check confirmed each one has
at least one identifier span with NO covering pattern in the CURRENT
VOCABULARY (given below, for context and so you don't collide pattern
ids or re-derive coverage that already exists). You are not being asked
to find gaps -- they are handed to you, per fact, exact, as the span
text itself. You are being asked to either close one or explicitly
decline it.

OUTPUT: two lists, `patterns` (same shape as before: {name, regex}) and
`declined` ({fact, span, reason}). A decline is a complete, legitimate
answer, not a failure -- use it whenever the honest answer is "no safe
pattern exists for this," exactly as the rules above already tell you
to do for an unqualifiable generic identifier. What is NOT acceptable is
leaving a target fact/span silently unaddressed by either list -- that
silence, repeated across hundreds of facts with nothing anywhere to
notice it, is the exact defect this pass exists to fix.

ANTI-GOODHART, PARTLY ENFORCED BY THE VALIDATOR, NOT JUST ASKED FOR: this
pass exists because a prior derivation call silently skipped these facts
-- do not "fix" that by writing one broad pattern that technically
matches every target fact's identifier without being a real, useful
pattern for any of them. Two rules apply; only the first is hard-
enforced:

  - No pattern may cover more than 3 distinct SYMBOLS -- this is
    mechanically checked and will fail the whole pass if violated.
    Matching the SAME symbol in several syntactic contexts is fine and
    doesn't add to the count (e.g. matching `certifi` both as
    `import certifi` and as a quoted `"certifi"` string is still one
    symbol, not two) -- what's capped is distinct target names, not `|`
    usage. Grouping IS still expected when several target identifiers
    genuinely share one call shape from the same fact or sibling facts
    (the "COVERAGE PER PATTERN" rule above), just never more than 3
    distinct symbols per pattern. If four or more target identifiers
    don't share a real call shape, write separate patterns, or decline
    the ones that don't fit -- never fold unrelated target facts into
    one pattern to shrink the decline count.
  - Every pattern's id should reference the specific symbol it targets
    (e.g. `gf_rootmodel` for a pattern about `RootModel`) OR, for a
    pattern covering several related symbols, name what they share
    (e.g. `gf_sslcertenv` for `SSL_CERT_FILE`/`SSL_CERT_DIR`, both SSL
    cert env vars). This is checked and flagged for human review when
    it doesn't hold, but does not fail the pass on its own -- still
    worth getting right, since a vague, category-style id (`gf_misc`)
    is exactly what a pattern optimizing for the checker rather than
    naming something real would look like.

ENGLISH-GENERIC-NOUN SPANS MUST BE QUALIFIED, NEVER BARE: the rules
above already forbid a bare `\.word\(` for a generic VERB
(get/set/add/list/...). The same restraint applies to a generic NOUN
used as an attribute or keyword argument -- `name`, `data`, `title`,
`description`, `headers`, `params` are ordinary words nearly any class
in any codebase might have. If a target span is one of these, anchor it
to the specific class/constructor/call the guide states it on (e.g.
`MCPServer\([^)]*\btitle\b`, or a keyword-shaped anchor like
`\btitle\s*=` scoped to the qualifying call) -- never a bare `\btitle\b`
of any kind, alone or inside a larger alternation. If the guide gives no
qualifying context for a generic-noun span, decline it and say so, the
same as an unqualifiable generic verb.

CURRENT VOCABULARY (for context/dedup -- do not re-derive coverage for
anything already listed here; if you believe a listed pattern already
covers a target span despite the coverage check saying otherwise,
decline that span and name which pattern you believe covers it, so a
human can check the coverage guard's own matching logic rather than
either side silently overriding the other):

{EXISTING_VOCABULARY}
