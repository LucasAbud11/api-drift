COORDINATED GROUP -- ADDITIONAL INSTRUCTIONS FOR THIS CALL:

Every site in the user message below belongs to ONE coordinated migration
edit: the facts describe a value, parameter, or symbol that must move
between these exact sites, not just change at one of them independently.
Fixing only some of them, or fixing each one as if the others didn't exist,
is the exact failure this call exists to prevent: a confident, correct-
looking fix at one site that leaves the group as a whole broken (a value
removed from one call and never threaded into the other it moved to).

Each member is shown with its own FULL enclosing statement marked with
`>>` on every line that belongs to it -- not just its anchor line -- so a
member spanning several physical lines is never partially visible to you.

You must do ONE of the following for this call, for the group as a whole:

- **Resolve every member with a fix.** Every site listed must appear in
  `fixes`, using the block shape described in the main output contract
  (`line`, `end_line`, `original_lines`, `proposed_lines`, `reason`).
  A value that leaves one member's block must actually appear, as a real
  expression (the same variable, not a made-up literal standing in for
  it), in whichever other member's block is where the facts say it goes.
  Do not invent a plausible-looking placeholder value for something you
  cannot actually see the right expression for in the context given --
  flag the group instead in that case.
- **Decline the whole group.** If you cannot produce a fix for every
  member that you are confident is jointly consistent with every other
  member, put ALL of them in `flagged_for_human`, each with its own
  `reason`. Do not resolve some members and decline others -- a torn
  group (some fixed, some flagged) is rejected outright by this pipeline
  regardless of how confident any individual member's fix looks.

There is no third option and no partial credit: this call's `fixes` and
`flagged_for_human` lists, together, must name every member exactly once,
and one of the two lists must be empty.
