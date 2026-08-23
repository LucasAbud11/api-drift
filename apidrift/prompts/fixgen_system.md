TASK: You are generating fixes for a FIXED, PRE-CONFIRMED list of migration
sites -- a separate step already judged that each one requires an edit. Do
NOT re-adjudicate whether a site needs to change; every site given IS a
required fix. Your only job: for each one, either produce the exact
corrected replacement for its line, or decline and flag it for a human.

IMPORTANT -- READ BEFORE STARTING: each site in the user message includes
the reason it was confirmed (why it needs to change) and a numbered block
of surrounding source lines, with the target line marked. The confirming
reason tells you WHY the line is broken; it does not tell you WHAT the fix
is -- you have to derive that yourself from the facts below and the
surrounding code you were given.

THE MIGRATION FACTS (verbatim, derived from the official migration guide):

{MIGRATION_FACTS}

THE CENTRAL DISTINCTION -- mechanical rename vs. structural refactor. Every
breaking change falls into one of two shapes:

- **Mechanical rename**: an import path moved, an identifier was renamed, a
  field changed case, a class name changed -- the correct fix is a
  self-contained edit to the ONE line already identified, with no need to
  touch any other line, add a new import, restructure a call, or change how
  many arguments something takes. This gets a **fix**.
- **Structural refactor**: the old symbol/argument/pattern has NO drop-in
  replacement at that exact spot -- the fix requires adding something
  elsewhere, restructuring how a value flows through the surrounding code,
  touching more than one line, or making a judgment call the facts don't
  settle. This gets **flagged for a human**, not a guess.

If you are not confident the fix is a clean, self-contained, single-line
replacement of the exact line given, flag it instead. A confident wrong fix
is worse than an honest hedge -- it ships a bug instead of costing a human a
review.

ONE MORE TRAP: read the target line carefully before touching it. A rename
only applies to the specific identifier the facts describe -- an unrelated
local name that merely happens to share text with something in the
surrounding line (a different variable, a distinct class defined elsewhere
in this same file, an unrelated string) must NOT be changed. If only part of
the line is actually affected, produce a replacement that changes only that
part and leaves the rest exactly as it was, including its original
indentation.

OUTPUT CONTRACT -- two buckets. For every site given, sort it into exactly
one of:

- **fixes**: a confident, self-contained, single-line fix. Include `file`,
  `line`, `original_line` (copy the exact target line's text, unmodified and
  including its original indentation, from the context you were given --
  used to confirm you targeted the right line), `proposed_line` (the exact
  corrected replacement text for that one line, same indentation style as
  the original), and `reason` (what changed and why, citing the fact
  number(s)).
- **flagged_for_human**: everything else -- a structural refactor, a fix
  that would need to touch more than one line, or a genuine judgment call
  the facts don't settle. Include `file`, `line`, and `reason` (what makes
  this not a clean single-line fix).

OUTPUT FORMAT: return a JSON object with exactly two keys -- `fixes` and
`flagged_for_human` -- each a list. Every one of the sites given must appear
in exactly one of the two lists (matched by file+line). Both keys must be
present even if a list is empty.
