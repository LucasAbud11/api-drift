# Blind fact-block derivation — run 2

Agent: fresh `general-purpose` subagent, zero conversation context, no tool
use (no Read/Grep/Glob/Bash), given only the guide text embedded in its
prompt. No access to this repo, `ground_truth_factblock.md`, or any other
migration spec in this project.

---

Analyzed the guide text only (no tools used, per instructions). Below is the complete fact block.

## FACT BLOCK: redis-py Unified Responses Migration

### A. Scope / activation / conditions (apply to all facts below unless noted)

1. Unified response mode is opt-in and is enabled per-client via the constructor/URL parameter `legacy_responses=False`. It is not the default.
2. Unified responses are designed so that affected commands return the *same* Python structure regardless of whether the connection's wire protocol is RESP2 or RESP3.
3. Response Mode Matrix (defines exactly when each shape applies):
   - `Redis()` (no args) → wire protocol defaults to RESP3, but Python response shape is the **legacy RESP2-compatible shape** (i.e., default behavior is NOT unified and NOT native RESP3-shaped).
   - `Redis(protocol=2)` → RESP2 wire → **legacy RESP2 shape**.
   - `Redis(protocol=3)` → RESP3 wire → **native RESP3 shape** (a third, distinct shape from both legacy-RESP2 and unified).
   - `Redis(legacy_responses=False)` → RESP3 wire (default) → **unified shape**.
   - `Redis(protocol=2, legacy_responses=False)` → RESP2 wire → **unified shape**.
   - `Redis(protocol=3, legacy_responses=False)` → RESP3 wire → **unified shape**.
4. `legacy_responses=False` is supported on: `redis.Redis`, `redis.asyncio.Redis` (async client), `redis.cluster.RedisCluster`, and via `redis.from_url(...)` using the query parameter `legacy_responses=false`.
5. `decode_responses` is an independent setting from `legacy_responses`/unified mode. It only controls bulk-string decoding; it does NOT control structural normalization of response containers/keys — that normalization is unified responses' job. (Non-scope fact: do not conflate the two when judging whether code needs to change.)
6. Enabling `legacy_responses=False` does not require changing the wire protocol — server/wire protocol can stay unchanged unless the caller also explicitly pins `protocol=2` or `protocol=3`.
7. Module command responses (JSON, TimeSeries, RediSearch, probabilistic-data-structure commands) are called out as a separate, higher-risk category: several return richer objects or nested containers under unified mode and should be reviewed separately from core data-type commands.
8. `FT.HYBRID` is explicitly marked experimental.

### B. RESP2 legacy shape → Unified shape (i.e., changes triggered by going from `Redis(protocol=2)` default to `Redis(protocol=2, legacy_responses=False)`, or from default `Redis()` to `Redis(legacy_responses=False)`)

9. `ZDIFF`, `ZINTER`, `ZRANGE`, `ZRANGEBYSCORE`, `ZREVRANGE`, `ZREVRANGEBYSCORE`, `ZUNION` (when returning scores): legacy = flat or tuple score pairs, scores often bytes → unified = list score pairs, scores as floats.
10. `ZPOPMAX`, `ZPOPMIN`: legacy = `[(member, score)]` (list of tuples) → unified = `[[member, float_score]]` (list of lists, score is float).
11. `BZPOPMAX`, `BZPOPMIN`: legacy = `(key, member, score)` (tuple) → unified = `[key, member, float_score]` (list, float score).
12. `ZRANK`, `ZREVRANK` (with score/WITHSCORE): legacy = `[rank, score]` where score can be bytes/int → unified = `[rank, float_score]`.
13. `ZSCAN`: legacy = `(cursor, [(member, score)])`, and any user-supplied score-cast function receives raw bytes → unified = `(cursor, [[member, score]])`, and score-cast function receives a float.
14. `ZRANDMEMBER` (with scores) and `HRANDFIELD` (with values): legacy = flat interleaved list → unified = nested `[[item, value], ...]` pairs.
15. `BLPOP`, `BRPOP`: legacy = `(key, value)` tuple → unified = `[key, value]` list.
16. `ZMPOP`, `BZMPOP`: legacy = nested tuple pairs with raw scores → unified = nested list pairs with float scores.
17. `XREAD`, `XREADGROUP`: legacy = `[[stream, entries], ...]` (list of pairs) → unified = `{stream: entries}` (dict).
18. `LCS` with `IDX`: legacy = flat key/value list → unified = dict with string keys.
19. `STRALGO ... IDX`: legacy = tuple ranges → unified = list ranges.
20. `CLIENT TRACKINGINFO`: legacy = flat list → unified = dict with string keys and decoded string lists.
21. `COMMAND`: legacy = `flags` as a list → unified = `flags` and `acl_categories` as sets of strings.
22. `ACL GETUSER`: legacy = selector flat lists → unified = selector dicts.
23. `ACL LOG`: legacy = string/bytes scalar values → unified = `age-seconds` becomes float, `client-info` becomes a dict.
24. `SENTINEL MASTER`, `SENTINEL MASTERS`, `SENTINEL SLAVES`, `SENTINEL SENTINELS`: legacy = `flags` as comma-separated string → unified = `flags` as a set, plus additional derived boolean fields.
25. `CLUSTER LINKS`, `CLUSTER SHARDS`: legacy = raw byte structural keys → unified = string structural keys.
26. `GEOPOS`: legacy = coordinate tuples → unified = coordinate lists.
27. `GEOSEARCH`, `GEORADIUS`, `GEORADIUSBYMEMBER` (with coordinates/WITHCOORD), under RESP2: legacy = tuple coordinates → unified = tuple coordinates (guide states this explicitly matches/equals the legacy shape — i.e., no actual shape change for this RESP2 case, unlike the RESP3 case, see fact 55).
28. `FUNCTION LIST`: legacy = flat sublists → unified = nested dictionaries.
29. `MEMORY STATS`: legacy = raw string-like values → unified = structural keys decoded, numeric values are native numeric types.
30. `JSON.NUMINCRBY`, `JSON.NUMMULTBY`: legacy = legacy scalar-path return behavior → unified = JSONPath-compatible array return behavior.
31. `JSON.RESP`: legacy = float values can appear as string leaves → unified = float leaves become Python floats.
32. `JSON.OBJKEYS`: legacy = keys forced to strings regardless of settings → unified = keys respect the `decode_responses` setting.
33. `TS.GET`, `TS.RANGE`, `TS.REVRANGE`: legacy = tuples → unified = lists.
34. `TS.MGET`: legacy = sorted list of dicts → unified = dict keyed by series name.
35. `TS.MRANGE`, `TS.MREVRANGE`: legacy = dict/list response without a metadata slot → unified = dict values include a `[labels, metadata, samples]` triple.
36. `TS.QUERYINDEX`: legacy = numeric-looking keys can be coerced (e.g., to numbers) → unified = keys are preserved as-is (as strings).
37. `FT.INFO`: legacy = attribute flat sublists → unified = attribute dicts including a `flags` key.
38. `FT.CONFIG GET`: legacy = bytes keys/values → unified = string keys/values.
39. `FT.SEARCH`: legacy = `Result` object without a unified `warnings` surface → unified = `Result` object with `warnings`.
40. `FT.AGGREGATE`: legacy = `AggregateResult` object without unified `total`/`warnings` surface → unified = `AggregateResult` object with `total` and `warnings`.
41. `FT.PROFILE`: legacy = parsed tuple containing legacy-shaped profile data → unified = parsed tuple containing unified-shaped profile data (still a tuple in both cases; internal shape of profile data differs).
42. `FT.HYBRID` under RESP2: legacy = `HybridResult` with bytes field values by default → unified = `HybridResult` with bytes field values preserved by default (guide phrasing indicates no behavioral change here — bytes-by-default is retained).
43. `TOPK.ADD`, `TOPK.INCRBY`, `TOPK.LIST`: legacy = numeric-looking item names can be coerced → unified = item names are preserved as-is.

### C. RESP3 legacy (native) shape → Unified shape (i.e., changes triggered by going from `Redis(protocol=3)` to `Redis(protocol=3, legacy_responses=False)`)

44. Sorted-set score-returning commands generally: RESP3-legacy = native RESP3 arrays and scores → unified = same public score-pair normalization applied as in the RESP2-unified case (converges to the same shape as facts under section B for these commands).
45. `ZSCAN`: RESP3-legacy = native score pairs → unified = list score pairs with unified score casting.
46. `ACL CAT`, `ACL HELP`, `ACL LIST`, `ACL USERS`: RESP3-legacy = lists of bytes → unified = lists of strings.
47. `ACL GENPASS`, `ACL WHOAMI`: RESP3-legacy = bytes scalar → unified = string scalar.
48. `ACL LOG`: RESP3-legacy = RESP3 map with string-like scalars → unified = normalized map with `age-seconds` as float and `client-info` parsed into a dict.
49. `CLIENT GETNAME`: RESP3-legacy = bytes scalar → unified = string scalar.
50. `CLIENT TRACKINGINFO`: RESP3-legacy = native RESP3 map → unified = dict with string keys and decoded string lists.
51. `COMMAND`: RESP3-legacy = native RESP3 command metadata → unified = unified command metadata with set-typed fields (e.g., flags as sets, mirroring fact 21).
52. `CLUSTER LINKS`, `CLUSTER SHARDS`: RESP3-legacy = native maps with raw structural keys → unified = string structural keys.
53. `GEOHASH`: RESP3-legacy = list of bytes → unified = list of strings.
54. `GEOPOS`: RESP3-legacy = list coordinates → unified = list coordinates (guide states both as "List coordinates" — no shape change stated for GEOPOS under RESP3).
55. `GEOSEARCH`, `GEORADIUS`, `GEORADIUSBYMEMBER` (with coordinates), under RESP3: RESP3-legacy = list coordinates → unified = tuple coordinates. (Note: this is the opposite direction of change from the RESP2 case in fact 27 — under RESP3, legacy uses lists and unified converts to tuples, converging with the RESP2/unified tuple shape.)
56. `LCS`, `STRALGO ... IDX` under RESP3: RESP3-legacy = RESP3 maps → unified = dicts with string keys and unified match-range lists.
57. `SENTINEL MASTER`, `SENTINEL MASTERS`, `SENTINEL SLAVES`, `SENTINEL SENTINELS` under RESP3: RESP3-legacy = native RESP3 state maps → unified = unified state dicts.
58. `BF.INFO`, `CF.INFO`, `CMS.INFO`, `TOPK.INFO`, `TDIGEST.INFO`: RESP3-legacy = raw maps → unified = rich info objects.
59. `TDIGEST.BYRANK`, `TDIGEST.BYREVRANK`, `TDIGEST.CDF`, `TDIGEST.QUANTILE`: RESP3-legacy = raw lists → unified = parsed lists with numeric and special-value handling.
60. `TS.INFO`: RESP3-legacy = raw map → unified = `TSInfo` object.
61. `TS.MRANGE`, `TS.MREVRANGE` under RESP3: RESP3-legacy = native response without a unified metadata slot → unified = dict values include `[labels, metadata, samples]` (mirrors fact 35 for RESP2).
62. `JSON.TYPE` specifically for missing keys: RESP3-legacy = `[None]` (a one-element list containing None) → unified = `None` (bare None, not wrapped in a list). Condition: applies specifically to the missing-key case.
63. `JSON.RESP` under RESP3: RESP3-legacy = numeric float leaves can appear as string/bytes → unified = float leaves become Python floats (mirrors fact 31 for RESP2).
64. `FT.SEARCH` under RESP3: RESP3-legacy = raw RESP3 result map → unified = `Result` object.
65. `FT.AGGREGATE` under RESP3: RESP3-legacy = raw RESP3 aggregate map → unified = `AggregateResult` object.
66. `FT.PROFILE` under RESP3: RESP3-legacy = `ProfileInformation(raw_response)` → unified = tuple of `(Result | AggregateResult, ProfileInformation)`. This is a return-type/shape change (single object → 2-tuple).
67. `FT.SPELLCHECK`: RESP3-legacy = native nested spellcheck map → unified = normalized term-suggestion dict.
68. `FT.INFO`, `FT.CONFIG GET`, `FT.SYNDUMP` under RESP3: RESP3-legacy = raw structural keys → unified = string structural keys.
69. `FT.HYBRID` under RESP3: RESP3-legacy = raw native response → unified = `HybridResult` object; field values remain bytes by default (shape changes from raw response to a `HybridResult` object, but byte-encoding of field values is unchanged/preserved).

### D. FT.HYBRID field-decoding behavior (general, not tied to RESP2 vs RESP3)

70. For `FT.HYBRID`, unified responses preserve result field values and warnings as bytes by default (applies across the unified mode generally, per facts 42 and 69), specifically to keep binary-loaded fields (e.g., vector embeddings) intact.
71. To get decoded (string) values for a specific field, the caller must opt in per-field using `decode_field=True` (e.g., via `HybridPostProcessingConfig().load("@fieldname", decode_field=True)`), and this should only be used for fields known to hold text values — not binary fields like embeddings, which should use `decode_field=False` (or be left at the default).
