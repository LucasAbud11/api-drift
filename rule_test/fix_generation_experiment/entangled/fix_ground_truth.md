# Fix ground truth — entangled host (OpsMesh), 10 sites

Built by direct source read of `rule_test/entanglement_experiment/host/` +
`spec_9fact.md` (the same 9-fact spec `entanglement_experiment/report.md`
used to derive detection GT for this host). **Per this task's instruction,
every claim below that a fix is correct/complete, or that a naive fix is
wrong, was checked by actually applying it to a scratch copy of the host
and running its real pytest suite (`pytest tests/ -v`, via a from-scratch
v1 and v2 `mcp` stub package — real deps `pytest`/`pytest-asyncio`/`PyYAML`/
`click` installed for this) — not by reading alone.**

**Fresh baseline, this session** (unmodified host, v1 stub):
`PYTHONPATH=src:mcp_v1_stub python3 -m pytest tests/ -v` → **16 passed, 0
failed**, 16 collected, 0 errors.

## The 6 single-line sites (empirically confirmed together, see below)

| id | file:line | original | v2 (required) | spec fact |
|---|---|---|---|---|
| E1 | server/base.py:16 | `from mcp.server.fastmcp import FastMCP` | `from mcp.server.mcpserver import MCPServer` | 1 |
| E2 | server/base.py:24 | `class OpsMeshServer(FastMCP):` | `class OpsMeshServer(MCPServer):` | 1 |
| E3 | server/context.py:12 | `from mcp.server.fastmcp import Context` | `from mcp.server.mcpserver import Context` | 1 |
| E7 | orchestrator/tool_catalog.py:46 | `input_schema=getattr(tool, "inputSchema", {}) or {},` | `input_schema=getattr(tool, "input_schema", {}) or {},` | 2 |
| E8 | tests/test_server_base.py:31 | `with patch("mcp.server.fastmcp.FastMCP.run") as fastmcp_run:` | `with patch("mcp.server.mcpserver.MCPServer.run") as fastmcp_run:` | 1 |
| E10 | tests/test_orchestrator_agent.py:18 | `return SimpleNamespace(name=name, description=description, inputSchema=schema)` | `return SimpleNamespace(name=name, description=description, input_schema=schema)` | 2 |

**Verified**: applied all 6 to a scratch copy (`entangled_correct_fix`),
plus the (separately-verified) E4/E5 refactor below, against a from-scratch
v2 stub with no `mcp.server.fastmcp` module at all → **16 passed, 0 failed
— identical to baseline, same test names.**

E8 is worth a specific note: it patches the PARENT class's `run` method
(`OpsMeshServer.run()` calls `super().run(...)`), so the correct dotted
path is the migrated base class's own new location
(`mcp.server.mcpserver.MCPServer.run`), which only resolves correctly
*after* E1/E2 are also applied (`OpsMeshServer` must actually subclass
`MCPServer` for `super().run` to dispatch there). Confirmed by the same
pytest run — if E1/E2 were reverted while E8 stayed migrated, `super().run`
would still resolve to the *old* `FastMCP.run`, and the patch would target
a class nothing in the MRO actually uses, silently not intercepting the
call. Not a two-way ambiguity — a same-file/near-file ordering dependency,
noted for completeness.

## E4 / E5 — no single-line fix exists (FLAG-FOR-HUMAN, verified two ways)

`server/context.py:13` (`from mcp.server.fastmcp import get_context as
_mcp_get_context`) and `:20` (`ctx = _mcp_get_context()`, inside
`current_context()`) both reference `mcp.get_context()` — per spec fact 3,
**removed entirely in v2**, not renamed or moved. `current_context()` is
imported and called in 4 files across the host
(`server/tools/deployments.py` x2 call sites, `runbooks.py`, `service_catalog.py`,
`incidents.py`) and monkeypatched directly in 5 tests in `tests/test_tools.py`.

**Negative check — the naive, locally-plausible fix**: swap only the
import path (`from mcp.server.mcpserver import get_context as
_mcp_get_context`), leave everything else untouched. Applied to a scratch
copy (`entangled_naive_fix`) alongside the 6 confirmed single-line fixes
above:
```
ImportError: cannot import name 'get_context' from 'mcp.server.mcpserver'
```
raised at collection, killing `tests/test_tools.py` outright. This is not
a hypothetical failure mode — it's what a fix generator that pattern-matches
"import path moved, swap the path" produces here, and it breaks immediately.

**Positive check — the actual correct fix**: not a line edit. Requires,
verified together in one scratch copy (`entangled_correct_fix`):
- `context.py`: delete the `get_context` import and the entire
  `current_context()` function (its only reason to exist no longer has a
  target to call).
- `deployments.py`, `runbooks.py`, `service_catalog.py`, `incidents.py`:
  drop the `current_context` import, add `ctx: Context` as a parameter on
  each of the 5 affected handler functions (`get_deployment_status`,
  `trigger_rollback`, `search_runbooks`, `get_service_owner`,
  `list_recent_incidents`), remove the internal `ctx = current_context()` /
  bare `current_context()` calls now that `ctx` arrives via the parameter
  instead — this is exactly the SDK's stated v2 replacement ("inject
  `ctx: Context` as a handler parameter instead").
- `tests/test_tools.py`: 5 tests' `monkeypatch.setattr(".../current_context",
  ...)` calls removed; each now passes `mock_context` as an explicit
  argument to the handler call instead.

6 files, ~15 lines, touched by what detection reported as 2 sites. Run
against the same v2 stub: **16 passed, 0 failed — identical to baseline.**

**Conclusion for scoring**: E4 and E5 have no defensible single "proposed_line"
answer. A FIX verdict on either — any single-line text — is scored WRONG
regardless of its content, because no single-line edit is correct here by
construction. FLAG-FOR-HUMAN, citing that the fix requires touching code
outside the detected line, is the only verdict that scores as correct.

## E6 / E9 — genuinely two valid fixes, and the host's own tests can't tell them apart (FLAG-FOR-HUMAN, verified two ways)

`client/session_group.py:38` (`return await self._group.call_tool(tool_name,
arguments)`) calls the method spec fact 5 says "lost its `args` parameter" —
the fact doesn't say what, if anything, replaced it. Two structurally
different, individually self-consistent edits were each applied (with E9,
`tests/test_client_session_group.py:23`'s assertion, updated to match) and
independently run to green:

- **Keyword variant**: `self._group.call_tool(tool_name, arguments=arguments)`
  + `mock_session_group.call_tool.assert_awaited_once_with("search_docs",
  arguments={"query": "rollback"})` → 3/3 passed.
- **Dropped variant**: `self._group.call_tool(tool_name)` (arguments no
  longer passed at all) + `mock_session_group.call_tool.assert_awaited_once_with("search_docs")`
  → 3/3 passed.

Both pass. **This is the load-bearing empirical result for this pair**: the
host's own test suite cannot discriminate which interpretation is real,
because it tests the wrapper against a `MagicMock`, not the actual v2
`ClientSessionGroup` — the mock accepts whatever shape it's called with.
Mechanical verification is *not* a substitute for the authoritative v2 API
reference here; it can only prove self-consistency between E6 and its
dependent test, never correctness against the real SDK contract. This
matches `entanglement_experiment/report.md`'s independent finding (2 of 3
detection runs also hedged on this exact site) — not a new failure mode,
a confirmation of it from the fix-generation side.

**E9's correct form is entirely contingent on E6's.** Whichever
interpretation is chosen for E6, E9 must be updated to match it — E9 has no
independently-correct answer; scoring it in isolation from E6 doesn't make
sense. Both are FLAG-FOR-HUMAN for fix-generation purposes; a fix-generation
agent that confidently emits ONE specific `proposed_line` for E6 (either
variant) without flagging the ambiguity is scored WRONG even if that variant
"passes," because passing here doesn't mean correct — see above.

## Scoring definitions (3 categories, per this task's request)

- **exact-match**: FIX verdict, proposed line byte-identical (after
  trailing-whitespace strip) to the required v2 line, for the 6
  single-line sites (E1/E2/E3/E7/E8/E10) only.
- **semantically-equivalent-but-different**: FIX verdict, not exact-match,
  but whitespace/quote-style normalized text matches, for the same 6 sites.
- **locally-plausible-but-globally-wrong**: a FIX verdict (any confident
  single-line proposal) on E4, E5, E6, or E9 — regardless of what text is
  proposed, since no single-line answer is correct for any of the four.
  This is the category the task asked to isolate: it is not "wrong" in the
  sense of a typo, it is wrong in the sense that ships a bug (E4/E5's naive
  form throws `ImportError` on import; E6's either single-line form may or
  may not match the real SDK and nothing in this host's own tests can tell
  you which before you find out in production).
- **legitimate hedge**: FLAG-FOR-HUMAN on E4, E5, E6, or E9, citing (in
  substance, not verbatim) that the correct edit isn't confined to the
  detected line, or that the target contract is genuinely underspecified.
- **wrong** (single-line sites only): FIX verdict with incorrect text, or
  FLAG-FOR-HUMAN/SKIP on any of the 6 sites that do have one confident
  correct answer.
