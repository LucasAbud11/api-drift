# Recovered original session artifacts

The original session that built `ground_truth/ground_truth.md`, `methodology_notes.md`,
and `results.md` was located on disk: `~/.claude/projects/-Users-lucasabud-Projects-api-drift/
804c3d31-60cd-454c-9433-1a6065725f24.jsonl` (436 lines). Identity confirmed by:
- Its first user message is the literal project kickoff ("I'm building a tool that
  detects breaking changes...").
- The 9 detection-agent findings recorded in it reproduce `results.md`'s exact
  aggregate numbers (m0xai: 19 raw findings = 5 real + 14 `ctx: Context` FPs;
  danilop: 6 raw findings = 3 real + 3 `ctx: Context` FPs; both exactly match
  the "14 instances" / "3 instances" results.md reports).
- Its final commands are `git add ... && git commit -m "Add ground truth,
  methodology notes, and results..."` — the exact commit at `a940505`.

Files here are extracted verbatim from that transcript for the record — this is
the actual input the original 9 agents received, not a reconstruction.

- `target_b_original_spec.txt` — the exact MCP v1→v2 spec text given to all 5
  Target B agents (extracted from the m0xai and danilop `Agent` tool calls,
  byte-identical between them). 9 numbered items, far more detailed than the
  6-item spec this session reconstructed from `ground_truth.md`.
- `m0xai_original_result.txt`, `danilop_original_result.txt` — the original
  agents' full raw output, including their own stated reasoning for flagging
  each `ctx: Context` site.
- `grep_baseline_command.sh` — the exact grep command the original session ran
  as its "naive baseline," extracted verbatim (not reconstructed).

See `../ablation_and_root_cause.md` for what this evidence establishes.
