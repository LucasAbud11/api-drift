# Blind fact-block derivation — run 1

Agent: fresh `general-purpose` subagent, zero conversation context, no tool
use (no Read/Grep/Glob/Bash), given only the guide text embedded in its
prompt. No access to this repo, `ground_truth_factblock.md`, or any other
migration spec in this project.

---

Fact block extracted from the redis-py "Unified Responses" migration guide. No files were read or tools used — this is derived purely from the provided text.

**Activation / configuration facts**

1. Unified response mode is opt-in via the constructor/URL parameter `legacy_responses=False` (default is legacy, i.e. `legacy_responses` defaults to enabling legacy shapes).
2. `legacy_responses=False` is supported on: `redis.Redis(...)`, `redis.asyncio.Redis(...)`, `redis.cluster.RedisCluster(...)`, and via URL as a query parameter `redis://...?legacy_responses=false` (using `redis.from_url`).
3. Unified mode is independent of wire protocol: it can be combined with default protocol, `protocol=2` (RESP2), or `protocol=3` (RESP3).
4. Response Mode Matrix (exact combinations stated):
   - `Redis()` (no args) → default RESP3 wire → Python response shape is "Legacy RESP2-compatible shape".
   - `Redis(protocol=2)` → RESP2 wire → "Legacy RESP2 shape".
   - `Redis(protocol=3)` → RESP3 wire → "Native RESP3 shape".
   - `Redis(legacy_responses=False)` → default RESP3 wire → "Unified shape".
   - `Redis(protocol=2, legacy_responses=False)` → RESP2 wire → "Unified shape".
   - `Redis(protocol=3, legacy_responses=False)` → RESP3 wire → "Unified shape".
   - Note: with default client construction (no `protocol` arg) and legacy responses, the *wire* protocol is RESP3 by default even though the *Python shape* returned is the RESP2-legacy-compatible shape — these are distinct axes.
5. `decode_responses` is stated to be independent of `legacy_responses`/unified mode: it continues to control bulk-string decoding only where the parser does not otherwise normalize structural keys or values. Unified mode changes response *structure*; `decode_responses` changes whether bulk string *data* is decoded to str vs left as bytes. This distinction/non-overlap is stated twice (in the matrix section and in the Migration Checklist item 5).

**Migration checklist facts (process/scope statements, not per-command behavior)**

6. Enabling `legacy_responses=False` can be done per environment/service path without changing the server wire protocol — pinning `protocol=2` or `protocol=3` is optional and separate from enabling unified responses.
7. The guide explicitly calls out that code needing review includes: code that indexes into tuples, code that expects flat lists, code that compares exact response containers, and code that serializes command responses directly.
8. The guide explicitly calls out that JSON, TimeSeries, RediSearch, and probabilistic module commands should be reviewed separately, since "several of them return richer objects or nested containers in unified mode."

**RESP2 Legacy → Unified table facts**

9. `ZDIFF`, `ZINTER`, `ZRANGE`, `ZRANGEBYSCORE`, `ZREVRANGE`, `ZREVRANGEBYSCORE`, `ZUNION` (all "with scores" variant): legacy RESP2 shape is flat or tuple score pairs, with scores often as bytes; unified shape is list score pairs, with scores as floats. Applies to RESP2 legacy vs unified comparison.
10. `ZPOPMAX`, `ZPOPMIN`: legacy shape `[(member, score)]` (list of tuples) → unified shape `[[member, float_score]]` (list of lists, score is float).
11. `BZPOPMAX`, `BZPOPMIN`: legacy shape `(key, member, score)` (a tuple) → unified shape `[key, member, float_score]` (a list, score is float).
12. `ZRANK`, `ZREVRANK` (with score option): legacy shape `[rank, score]` where score can be bytes or int → unified shape `[rank, float_score]` (score is float).
13. `ZSCAN`: legacy shape `(cursor, [(member, score)])` where the score cast function receives raw bytes → unified shape `(cursor, [[member, score]])` where the score cast function receives a float.
14. `ZRANDMEMBER` (with scores option), `HRANDFIELD` (with values option): legacy shape is a flat interleaved list → unified shape is nested pairs `[[item, value], ...]`.
15. `BLPOP`, `BRPOP`: legacy shape `(key, value)` (tuple) → unified shape `[key, value]` (list).
16. `ZMPOP`, `BZMPOP`: legacy shape is nested tuple pairs with raw (non-float) scores → unified shape is nested list pairs with float scores.
17. `XREAD`, `XREADGROUP`: legacy shape `[[stream, entries], ...]` (list of lists) → unified shape `{stream: entries}` (dict keyed by stream).
18. `LCS` (with `IDX` option): legacy shape is a flat key/value list → unified shape is a dict with string keys.
19. `STRALGO ... IDX`: legacy shape is tuple ranges → unified shape is list ranges.
20. `CLIENT TRACKINGINFO`: legacy (RESP2) shape is a flat list → unified shape is a dict with string keys and decoded string lists.
21. `COMMAND`: legacy shape has `flags` as a list → unified shape has `flags` and `acl_categories` both as sets of strings (note: `acl_categories` as a set is new/changed in unified; legacy row only mentions `flags` as list).
22. `ACL GETUSER`: legacy shape has selectors as flat lists → unified shape has selectors as dicts.
23. `ACL LOG`: legacy shape has string/bytes scalar values → unified shape has `age-seconds` as a float and `client-info` as a dict.
24. `SENTINEL MASTER`, `SENTINEL MASTERS`, `SENTINEL SLAVES`, `SENTINEL SENTINELS`: legacy shape has `flags` as a comma-separated string → unified shape has `flags` as a set, plus derived boolean fields.
25. `CLUSTER LINKS`, `CLUSTER SHARDS`: legacy (RESP2) shape has raw byte structural keys → unified shape has string structural keys.
26. `GEOPOS`: legacy (RESP2) shape is coordinate tuples → unified shape is coordinate lists.
27. `GEOSEARCH`, `GEORADIUS`, `GEORADIUSBYMEMBER` (with coordinates option, RESP2 context): legacy shape is tuple coordinates → unified shape is also tuple coordinates ("matching the approved unified shape") — i.e., stated explicitly as NOT changing in shape-type for the RESP2→unified direction (tuple stays tuple).
28. `FUNCTION LIST`: legacy shape is flat sublists → unified shape is nested dictionaries.
29. `MEMORY STATS`: legacy shape has raw string-like values → unified shape has structural keys decoded and numeric values as native numeric types.
30. `JSON.NUMINCRBY`, `JSON.NUMMULTBY`: legacy shape is "legacy scalar path" → unified shape is "JSONPath-compatible array behavior."
31. `JSON.RESP`: legacy shape allows float values to appear as string leaves → unified shape converts float leaves to Python floats.
32. `JSON.OBJKEYS`: legacy shape forces keys to strings (regardless of `decode_responses`) → unified shape makes keys respect `decode_responses` setting.
33. `TS.GET`, `TS.RANGE`, `TS.REVRANGE`: legacy shape is tuples → unified shape is lists.
34. `TS.MGET`: legacy shape is a sorted list of dicts → unified shape is a dict keyed by series.
35. `TS.MRANGE`, `TS.MREVRANGE` (RESP2 context): legacy shape is dict/list without a metadata slot → unified shape is a dict whose values include `[labels, metadata, samples]`.
36. `TS.QUERYINDEX`: legacy shape can have numeric-looking keys coerced (e.g., to numbers) → unified shape preserves keys as-is (no coercion).
37. `FT.INFO` (RESP2 context): legacy shape has attribute flat sublists → unified shape has attribute dicts including `flags`.
38. `FT.CONFIG GET` (RESP2 context): legacy shape has bytes keys/values → unified shape has string keys/values.
39. `FT.SEARCH` (RESP2 context): legacy shape returns a `Result` object without a unified `warnings` surface → unified shape returns a `Result` object that includes `warnings`.
40. `FT.AGGREGATE` (RESP2 context): legacy shape returns an `AggregateResult` without unified `total`/`warnings` surface → unified shape returns an `AggregateResult` with `total` and `warnings`.
41. `FT.PROFILE` (RESP2 context): legacy shape is a parsed tuple with legacy profile data → unified shape is a parsed tuple with unified profile data (same tuple container, different internal data format).
42. `FT.HYBRID` (RESP2 context): legacy shape is `HybridResult` with bytes by default → unified shape is `HybridResult` with bytes preserved by default — i.e., explicitly stated as unchanged (bytes-by-default behavior preserved) in this RESP2 comparison.
43. `TOPK.ADD`, `TOPK.INCRBY`, `TOPK.LIST`: legacy shape can have numeric-looking item names coerced → unified shape preserves item names as-is.

**RESP3 Legacy → Unified table facts**

44. Sorted-set score commands (general, RESP3 context — not itemized by name beyond "Sorted-set score commands"): legacy RESP3 shape is native RESP3 arrays and scores → unified shape uses the same public score-pair normalization as the RESP2 unified shape (i.e., RESP3 unified converges to the same shape as RESP2 unified for these commands).
45. `ZSCAN` (RESP3 context): legacy shape is native score pairs → unified shape is list score pairs with unified score casting.
46. `ACL CAT`, `ACL HELP`, `ACL LIST`, `ACL USERS` (RESP3 context): legacy shape is lists of bytes → unified shape is lists of strings.
47. `ACL GENPASS`, `ACL WHOAMI` (RESP3 context): legacy shape is a bytes scalar → unified shape is a string scalar.
48. `ACL LOG` (RESP3 context): legacy shape is a RESP3 map with string-like scalars → unified shape is a normalized map with `age-seconds` as float and parsed `client-info` (as a dict, consistent with the RESP2 table row).
49. `CLIENT GETNAME` (RESP3 context): legacy shape is a bytes scalar → unified shape is a string scalar.
50. `CLIENT TRACKINGINFO` (RESP3 context): legacy shape is a native RESP3 map → unified shape is a dict with string keys and decoded string lists.
51. `COMMAND` (RESP3 context): legacy shape is native RESP3 command metadata → unified shape is unified command metadata with set fields (consistent with `flags`/`acl_categories` as sets from the RESP2 row).
52. `CLUSTER LINKS`, `CLUSTER SHARDS` (RESP3 context): legacy shape is native maps with raw structural keys → unified shape has string structural keys.
53. `GEOHASH` (RESP3 context): legacy shape is a list of bytes → unified shape is a list of strings.
54. `GEOPOS` (RESP3 context): legacy shape is list coordinates → unified shape is list coordinates — explicitly stated as unchanged (no shape difference) in this RESP3 comparison.
55. `GEOSEARCH`, `GEORADIUS`, `GEORADIUSBYMEMBER` (with coordinates, RESP3 context): legacy shape is list coordinates → unified shape is tuple coordinates. (Note: this is the opposite direction of change from the RESP2 comparison — in RESP3, legacy list becomes unified tuple; in RESP2, legacy tuple stays unified tuple. Both converge to tuple coordinates in unified mode.)
56. `LCS`, `STRALGO ... IDX` (RESP3 context): legacy shape is RESP3 maps → unified shape is dicts with string keys and unified match range lists.
57. `SENTINEL MASTER`, `MASTERS`, `SLAVES`, `SENTINELS` (RESP3 context): legacy shape is native RESP3 state maps → unified shape is unified state dicts.
58. `BF.INFO`, `CF.INFO`, `CMS.INFO`, `TOPK.INFO`, `TDIGEST.INFO` (RESP3 context): legacy shape is raw maps → unified shape is rich info objects.
59. `TDIGEST.BYRANK`, `TDIGEST.BYREVRANK`, `TDIGEST.CDF`, `TDIGEST.QUANTILE` (RESP3 context): legacy shape is raw lists → unified shape is parsed lists with numeric and special-value handling.
60. `TS.INFO` (RESP3 context): legacy shape is a raw map → unified shape is a `TSInfo` object.
61. `TS.MRANGE`, `TS.MREVRANGE` (RESP3 context): legacy shape is native response without a unified metadata slot → unified shape is a dict whose values include `[labels, metadata, samples]` (consistent with RESP2 row).
62. `JSON.TYPE` for missing keys (RESP3 context, specifically the "missing keys" case): legacy shape is `[None]` (a list containing None) → unified shape is `None` (bare None, not wrapped in a list). This change is scoped specifically to the case of missing keys.
63. `JSON.RESP` (RESP3 context): legacy shape allows numeric float leaves to appear as string/bytes → unified shape converts float leaves to Python floats (consistent with RESP2 row).
64. `FT.SEARCH` (RESP3 context): legacy shape is a raw RESP3 result map → unified shape is a `Result` object.
65. `FT.AGGREGATE` (RESP3 context): legacy shape is a raw RESP3 aggregate map → unified shape is an `AggregateResult` object.
66. `FT.PROFILE` (RESP3 context): legacy shape is `ProfileInformation(raw_response)` → unified shape is a tuple `(Result | AggregateResult, ProfileInformation)`. Note: this is a different/more specific change than the RESP2 row for the same command (RESP2 row described tuple-to-tuple with different internal data; RESP3 row describes a container-type change).
67. `FT.SPELLCHECK` (RESP3 context; not mentioned in the RESP2 table at all): legacy shape is a native nested spellcheck map → unified shape is a normalized term suggestion dict.
68. `FT.INFO`, `FT.CONFIG GET`, `FT.SYNDUMP` (grouped together, RESP3 context): legacy shape has raw structural keys → unified shape has string structural keys. (Note: `FT.SYNDUMP` appears only in this RESP3 grouped row, not separately in the RESP2 table.)
69. `FT.HYBRID` (RESP3 context): legacy shape is a raw native response → unified shape is `HybridResult` with field values remaining bytes by default. (Note: unlike the RESP2 row where legacy was already `HybridResult`, here in RESP3 the legacy shape is a raw native response — i.e., the `HybridResult` wrapper itself is new for RESP3 unified, while bytes-by-default is preserved.)

**HYBRID command field decoding facts (standalone section, applies regardless of RESP2/RESP3 designation but specifically to `FT.HYBRID`)**

70. `FT.HYBRID` is explicitly marked as experimental.
71. In unified responses, `FT.HYBRID` result field values and warnings are bytes by default (not decoded), by design, in order to keep binary-loaded fields (e.g., vector embeddings) intact.
72. Per-field decoding of `FT.HYBRID` results can be controlled via `HybridPostProcessingConfig.load(field_name, decode_field=...)`, e.g. `post.load("@title", decode_field=True)` to decode a known text field, and `post.load("@embedding", decode_field=False)` to keep a binary field (e.g., embeddings) as bytes. The guide states this should be used "only for fields that are known text values" — i.e., `decode_field=True` is scoped/recommended only for known-text fields, not universally.

**Cross-cutting scope notes (apply to interpreting all facts above)**

73. All facts in the "RESP2 Legacy to Unified" table describe the change from RESP2-wire legacy shape to unified shape (unified shape is protocol-independent per the guide's stated design goal).
74. All facts in the "RESP3 Legacy to Unified" table describe the change from RESP3-wire legacy (native RESP3) shape to unified shape.
75. The guide's stated overall design goal: for affected commands, the unified shape returned is the same Python structure regardless of whether the underlying wire protocol is RESP2 or RESP3 — meaning the RESP2-unified and RESP3-unified shapes for the same command should be identical even though the two tables sometimes describe the change starting from different legacy baselines.
