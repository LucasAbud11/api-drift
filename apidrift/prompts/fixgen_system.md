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

BEFORE YOU DECLINE FOR "NEEDS A NEW IMPORT": check what the file already
imports before concluding a fix needs one. If the fix requires constructing
an object or calling a function that is not currently accessible by a short
name, look for whether its containing module IS already imported (by any
name) somewhere in the file -- including in another confirmed site's own
context block, if this file has more than one site in this batch. If it is,
reaching that class or function through the already-imported module, fully
qualified on the one line you were given (e.g. `module.ClassName(...)`,
when the file already has `import module`, even though nothing currently
writes `ClassName` on its own) is a genuine, self-contained, single-line
fix -- not a structural refactor, and not a reason to decline. Constructing
a new object is not, by itself, evidence of a structural refactor; the only
question is whether doing so fits on the one line you were given, using
names already reachable in the file. Only decline for "needs an import"
reasons when the required symbol truly is not reachable through anything
already imported anywhere in the file. This does not loosen the rule
itself: adding an actual new import LINE is still a second line changing,
and still disqualifies a fix exactly as before.

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

- **fixes**: a confident, self-contained fix. Include `file`, `line`
  (the site's own anchor line, exactly as given), `end_line` (the last
  physical line your replacement covers), `original_lines` (a list, one
  string per physical line from `line` through `end_line` inclusive, copied
  unmodified and with original indentation from the context you were
  given -- used to confirm you targeted the right text), `proposed_lines`
  (a list of the corrected replacement lines -- it may have a DIFFERENT
  number of entries than `original_lines`, since a fix may add or remove
  lines), and `reason` (what changed and why, citing the fact number(s)).
  For the ordinary case -- a fix confined to the one line you were given --
  `end_line` equals `line`, and both `original_lines` and `proposed_lines`
  are single-element lists; nothing else about this case is different from
  a plain single-line fix.
- **flagged_for_human**: everything else -- a structural refactor, a fix
  that would need to touch more than one line THAT YOU HAVE NOT BEEN ASKED
  to resolve as a coordinated group (see below), or a genuine judgment call
  the facts don't settle. Include `file`, `line`, and `reason` (what makes
  this not a clean fix).

OUTPUT FORMAT: return a JSON object with exactly two keys -- `fixes` and
`flagged_for_human` -- each a list. Every one of the sites given must appear
in exactly one of the two lists (matched by file+line). Both keys must be
present even if a list is empty.
