TASK: You are adjudicating a fixed, pre-generated, PRE-FILTERED candidate
list of lines from a codebase, checking each one against a real migration.
Do NOT fix anything -- only judge whether each line's own text must
change.

IMPORTANT -- READ BEFORE STARTING: The candidate list in the user message
was produced by an exhaustive vocabulary search (grep), then passed
through a deterministic mechanical pre-filter (no LLM) that removed only
candidates whose file never references the migrating package at all
(directly or transitively through the codebase's own import graph), and
candidates whose match was entirely inside a comment or a real docstring.
It is a closed, finite, complete set for this run. Your job is adjudication
only, not search. Every one of the candidates given must receive exactly
one verdict. Do not skip any.

Some candidates have a `duplicate_count` and `duplicate_lines` field. This
means the pre-filter found that exact same line of text repeated verbatim,
byte-for-byte, at multiple line numbers within the same file. You only
need to give ONE verdict for that candidate -- it applies to every line
listed in `duplicate_lines`.

THE MIGRATION FACTS (verbatim, derived from the official migration guide):

{MIGRATION_FACTS}

COUNTING CONVENTION (applies to every fact above): A site is a line that
must itself be edited to fix the migration. If fixing one line (e.g. an
import statement) automatically repairs another line's behavior without
that other line's own text needing to change, the other line is NOT a
separate site -- do not report it. Only report a line if its own text has
to change. Example of the general shape this takes: if a symbol is
imported from a path that moved, fixing the import statement alone often
makes every downstream *usage* of that symbol (a type annotation, a
variable reference) resolve correctly again -- the usage site's own text
does not need to change, so it is not a separate site. Contrast that with
a *construction* or *class definition* referencing the old symbol name
directly (e.g. `OldName(...)` or `-> OldName:`) where the old identifier no
longer exists under that name at all after the rename -- fixing the import
does NOT make that resolve, so the construction/annotation site's own text
must change, and that IS a separate site. Apply this same reasoning to
whatever facts are listed above; do not assume every fact behaves like
this example -- read each fact's own text for whether it describes a pure
rename (usage sites often unaffected once the import is fixed) or a
behavioral/shape/removal change (every touching site is usually its own
site).

OUTPUT CONTRACT -- three buckets. For every candidate given, sort it into
exactly one of:

- **PROPOSE**: confident this line's own text must change. Report with the
  fact number(s) that justify it and a reason.
- **REJECT**: confident this line does NOT need to change, and you can
  cite the specific fact above that settles it.
- **FLAG-UNCERTAIN**: the default when either MANDATORY rule below
  applies, or when the facts above genuinely don't settle the question.

TWO MANDATORY, MECHANICAL ROUTING RULES -- these override your own
confidence. If a candidate matches either rule, you may NOT put it in
REJECT (PROPOSE is still allowed if you are confident it IS a required
site; otherwise it must go to FLAG-UNCERTAIN):

**RULE 1 (name-impersonation):** the candidate line is part of machinery
that makes some OTHER piece of code's import/reference of a migrating
symbol resolve to a locally-built stand-in, rather than the real installed
package (e.g. a `sys.modules[...]` assignment, a `types.ModuleType(...)`
construction representing a path under the migrating package, or an
attribute assignment exposing a class/function under the package's name on
such a constructed object).

**RULE 2 (test/mock path floor):** the candidate's file path contains
`/tests/`, starts with `tests/`, matches `test_*.py` or `*_test.py`, or
contains "mock" or "fixture" in the path/filename. Any such candidate you
would otherwise REJECT must go to FLAG-UNCERTAIN instead.

OUTPUT FORMAT: return a JSON object with exactly three keys --
`proposed_sites`, `flag_uncertain`, `considered_and_rejected` -- each a
list. Every one of the candidates given must appear in exactly one of the
three lists (matched by file+line; for a candidate with `duplicate_lines`,
use its first/representative line). Include `file`, `line`, `snippet`
(the exact candidate line text), and `reason` on every item; additionally
include `pattern` (the fact number(s), as a string) on every item in
`proposed_sites`. All three keys must be present even if a list is empty.
