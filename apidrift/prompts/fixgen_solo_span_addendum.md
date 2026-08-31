COORDINATED GROUP -- ADDITIONAL INSTRUCTIONS FOR THIS CALL:

The site in the user message below is a multi-line statement -- fixgen
normally evaluates and rewrites exactly one physical line at a time,
which would leave the rest of a multi-line statement unseen. This call
exists so you see the FULL enclosing statement instead, marked with `>>`
on every line that belongs to it.

Unlike a coordinated group, there is no companion site in this call: no
other line is shown to you, and adjudication did not identify one this
value could move to or from. If a correct fix would need to remove a
value (e.g. a keyword argument) that the migration facts say must be
supplied somewhere else, but you cannot see that somewhere-else in this
call, do NOT invent a plausible-looking destination and do NOT drop the
value silently -- decline instead. A fix that only touches this
statement's own shape (a rename, a reordering, a value added or removed
with nothing else needing to receive or supply it) is exactly what this
call is for.

You must do ONE of the following for this call:

- **Resolve with a fix.** Report it in `fixes`, using the block shape
  described in the main output contract (`line`, `end_line`,
  `original_lines`, `proposed_lines`, `reason`).
- **Decline.** If you cannot produce a fix you are confident is complete
  and correct without seeing a site that isn't shown to you, put it in
  `flagged_for_human` with a `reason` explaining what's missing.

There is no third option: this call's `fixes` and `flagged_for_human`
lists, together, must name this one site exactly once, and one of the
two lists must be empty.
