# Blind fact-block derivation — run 3

Agent: fresh `general-purpose` subagent, zero conversation context, no tool
use (no Read/Grep/Glob/Bash), given only the guide text embedded in its
prompt. No access to this repo, `ground_truth_factblock.md`, or any other
migration spec in this project.

---

This was a pure text-reasoning task — no files, tools, or repo exploration were used, per the instructions. Below is the complete fact block extracted directly from the guide text.

## FACT BLOCK

### A. Scope / Activation Facts

1. Unified responses are an **opt-in** feature, enabled by constructing the client with `legacy_responses=False`. Without this flag, legacy shapes are used.
2. Unified responses are designed so that **affected commands** return the same Python structure regardless of whether the connection uses RESP2 or RESP3 wire protocol. (Implication: unaffected commands are out of scope — the guide only documents commands listed in its tables as changing.)
3. `legacy_responses=False` can be set independently of the `protocol` argument. Per the guide: "The server protocol can stay unchanged unless you also want to pin `protocol=2` or `protocol=3`."
4. `legacy_responses=False` is supported across: sync `redis.Redis`, `redis.asyncio.Redis`, `redis.cluster.RedisCluster`, and via URL as a query parameter (`redis://...?legacy_responses=false`) with `redis.from_url`.
5. **Response Mode Matrix** (exact stated mapping of client construction → wire protocol → Python response shape):
   - `Redis()` → wire: Default RESP3 wire → shape: **Legacy RESP2-compatible shape**
   - `Redis(protocol=2)` → wire: RESP2 → shape: **Legacy RESP2 shape**
   - `Redis(protocol=3)` → wire: RESP3 → shape: **Native RESP3 shape**
   - `Redis(legacy_responses=False)` → wire: Default RESP3 wire → shape: **Unified shape**
   - `Redis(protocol=2, legacy_responses=False)` → wire: RESP2 → shape: **Unified shape**
   - `Redis(protocol=3, legacy_responses=False)` → wire: RESP3 → shape: **Unified shape**
   - Note: plain `Redis(protocol=3)` (no `legacy_responses=False`) yields "Native RESP3 shape", which the guide treats as a *distinct* shape from both "Legacy RESP2-compatible shape" (default `Redis()`) and "Unified shape". The guide does not further define "Native RESP3 shape" beyond this matrix row and the RESP3 delta table's "RESP3 legacy shape" column.
   - The guide does not explicitly state which of its two delta tables ("RESP2 Legacy to Unified" vs "RESP3 Legacy to Unified") governs the diff for the default `Redis()`/`Redis(legacy_responses=False)` case (RESP3 wire, no `protocol` pinned) — only that these are separate delta tables keyed by wire protocol.
6. `decode_responses` is **independent** of `legacy_responses`/unified-response mode. It still controls bulk-string decoding only "where the parser does not otherwise normalize structural keys or values." (i.e., unified mode may already normalize some keys/values regardless of `decode_responses`.)
7. Migration checklist states (general, non-command-specific facts):
   a. Client construction points to check include background workers, admin scripts, asyncio clients, and cluster clients.
   b. Recommended rollout: enable `legacy_responses=False` for one environment/service path first.
   c. Code patterns to check/update: code that indexes into tuples, expects flat lists, compares exact response containers, or serializes command responses directly.
   d. JSON, TimeSeries, RediSearch, and probabilistic module commands should be reviewed separately, since "several of them return richer objects or nested containers in unified mode."
   e. `decode_responses` decisions should be kept conceptually separate from unified-response decisions (restates fact 6).
   f. Recommended to roll out gradually and monitor code paths that parse Redis responses manually.

### B. RESP2 wire — Legacy shape vs Unified shape (applies when connection uses RESP2, i.e. `protocol=2`)

8. **ZDIFF, ZINTER, ZRANGE, ZRANGEBYSCORE, ZREVRANGE, ZREVRANGEBYSCORE, ZUNION** (with scores): legacy = flat or tuple score pairs, scores often bytes → unified = list score pairs, scores as floats.
9. **ZPOPMAX, ZPOPMIN**: legacy = `[(member, score)]` → unified = `[[member, float_score]]`.
10. **BZPOPMAX, BZPOPMIN**: legacy = `(key, member, score)` (tuple) → unified = `[key, member, float_score]` (list).
11. **ZRANK, ZREVRANK** (with score option): legacy = `[rank, score]` where score can be bytes/int → unified = `[rank, float_score]`.
12. **ZSCAN**: legacy = `(cursor, [(member, score)])`, score cast function receives raw bytes → unified = `(cursor, [[member, score]])`, score cast function receives float.
13. **ZRANDMEMBER** (with scores), **HRANDFIELD** (with values): legacy = flat interleaved list → unified = nested `[[item, value], ...]` pairs.
14. **BLPOP, BRPOP**: legacy = `(key, value)` (tuple) → unified = `[key, value]` (list).
15. **ZMPOP, BZMPOP**: legacy = nested tuple pairs with raw scores → unified = nested list pairs with float scores.
16. **XREAD, XREADGROUP**: legacy = `[[stream, entries], ...]` (list of pairs) → unified = `{stream: entries}` (dict).
17. **LCS** with `IDX` option: legacy = flat key/value list → unified = dict with string keys.
18. **STRALGO ... IDX**: legacy = tuple ranges → unified = list ranges.
19. **CLIENT TRACKINGINFO**: legacy = flat list → unified = dict with string keys and decoded string lists.
20. **COMMAND**: legacy = `flags` returned as a list → unified = `flags` and `acl_categories` returned as sets of strings.
21. **ACL GETUSER**: legacy = selector data as flat lists → unified = selector data as dicts.
22. **ACL LOG**: legacy = string/bytes scalar values → unified = `age-seconds` as float, `client-info` as dict.
23. **SENTINEL MASTER, MASTERS, SLAVES, SENTINELS**: legacy = `flags` as comma-separated string → unified = `flags` as a set, plus derived boolean fields.
24. **CLUSTER LINKS, CLUSTER SHARDS**: legacy = raw byte structural keys → unified = string structural keys.
25. **GEOPOS**: legacy = coordinate tuples → unified = coordinate lists.
26. **GEOSEARCH, GEORADIUS, GEORADIUSBYMEMBER** (with coordinates): legacy = tuple coordinates → unified = tuple coordinates ("matching the approved unified shape") — i.e., no shape change on the RESP2 wire for this case (both legacy and unified return tuple coordinates).
27. **FUNCTION LIST**: legacy = flat sublists → unified = nested dictionaries.
28. **MEMORY STATS**: legacy = raw string-like values → unified = structural keys decoded, numeric values native (not string-like).
29. **JSON.NUMINCRBY, JSON.NUMMULTBY**: legacy = legacy scalar path behavior → unified = JSONPath-compatible array behavior.
30. **JSON.RESP**: legacy = float values can appear as string leaves → unified = float leaves become Python floats.
31. **JSON.OBJKEYS**: legacy = keys forced to strings (regardless of `decode_responses`) → unified = keys respect `decode_responses`.
32. **TS.GET, TS.RANGE, TS.REVRANGE**: legacy = tuples → unified = lists.
33. **TS.MGET**: legacy = sorted list of dicts → unified = dict keyed by series (name).
34. **TS.MRANGE, TS.MREVRANGE**: legacy = dict/list response without a metadata slot → unified = dict values include `[labels, metadata, samples]` (adds a metadata element).
35. **TS.QUERYINDEX**: legacy = numeric-looking keys can be coerced (e.g., to numeric types) → unified = keys are preserved as-is (e.g., as strings).
36. **FT.INFO**: legacy = attribute data as flat sublists → unified = attribute data as dicts with a `flags` field.
37. **FT.CONFIG GET**: legacy = bytes keys/values → unified = string keys/values.
38. **FT.SEARCH**: legacy = `Result` object without a unified `warnings` surface → unified = `Result` object with `warnings`.
39. **FT.AGGREGATE**: legacy = `AggregateResult` without unified `total`/`warnings` surface → unified = `AggregateResult` with `total` and `warnings`.
40. **FT.PROFILE**: legacy = parsed tuple containing legacy-format profile data → unified = parsed tuple containing unified-format profile data (structure/type not otherwise detailed).
41. **FT.HYBRID**: legacy = `HybridResult`, bytes by default → unified = `HybridResult`, bytes preserved by default — i.e., no behavioral change stated for RESP2 wire (both legacy and unified keep field values as bytes by default). Note: `FT.HYBRID` is explicitly marked experimental (see fact 47).
42. **TOPK.ADD, TOPK.INCRBY, TOPK.LIST**: legacy = numeric-looking item names can be coerced → unified = item names are preserved as-is.

### C. RESP3 wire — Legacy shape vs Unified shape (applies when connection uses RESP3, e.g. `protocol=3` or default RESP3 wire)

43. **Sorted-set score commands** (general, unnamed set): legacy(RESP3) = native RESP3 arrays and scores → unified = "same public score-pair normalization as RESP2 unified" (i.e., converges to the same shape as fact 8's unified column).
44. **ZSCAN**: legacy(RESP3) = native score pairs → unified = list score pairs with unified score casting (float casting, per fact 12's unified behavior).
45. **ACL CAT, ACL HELP, ACL LIST, ACL USERS**: legacy(RESP3) = lists of bytes → unified = lists of strings.
46. **ACL GENPASS, ACL WHOAMI**: legacy(RESP3) = bytes scalar → unified = string scalar.
47. **ACL LOG**: legacy(RESP3) = RESP3 map with string-like scalars → unified = normalized map with float `age-seconds` and parsed `client-info` (same net effect as fact 22 for RESP2 wire).
48. **CLIENT GETNAME**: legacy(RESP3) = bytes scalar → unified = string scalar.
49. **CLIENT TRACKINGINFO**: legacy(RESP3) = native RESP3 map → unified = dict with string keys and decoded string lists (same net unified shape as fact 19).
50. **COMMAND**: legacy(RESP3) = native RESP3 command metadata → unified = unified command metadata "with set fields" (consistent with fact 20's `flags`/`acl_categories` becoming sets).
51. **CLUSTER LINKS, CLUSTER SHARDS**: legacy(RESP3) = native maps with raw structural keys → unified = string structural keys (same net unified shape as fact 24).
52. **GEOHASH**: legacy(RESP3) = list of bytes → unified = list of strings.
53. **GEOPOS**: legacy(RESP3) = list coordinates → unified = list coordinates — no shape change stated on RESP3 wire for `GEOPOS`. (Contrast with fact 25: on RESP2 wire, `GEOPOS` *does* change, from tuples to lists.)
54. **GEOSEARCH, GEORADIUS, GEORADIUSBYMEMBER** (with coordinates): legacy(RESP3) = list coordinates → unified = tuple coordinates — this *is* a shape change on RESP3 wire (list → tuple), unlike the RESP2 wire case (fact 26) where legacy and unified both already used tuple coordinates.
55. **LCS, STRALGO ... IDX**: legacy(RESP3) = RESP3 maps → unified = dicts with string keys and unified match-range lists.
56. **SENTINEL MASTER, MASTERS, SLAVES, SENTINELS**: legacy(RESP3) = native RESP3 state maps → unified = unified state dicts (guide does not detail whether the RESP3 unified shape also adds derived booleans as stated for RESP2 in fact 23 — only "unified state dicts" is stated).
57. **BF.INFO, CF.INFO, CMS.INFO, TOPK.INFO, TDIGEST.INFO**: legacy(RESP3) = raw maps → unified = rich info objects (specific object types not named in the guide).
58. **TDIGEST.BYRANK, TDIGEST.BYREVRANK, TDIGEST.CDF, TDIGEST.QUANTILE**: legacy(RESP3) = raw lists → unified = parsed lists with numeric and special-value handling.
59. **TS.INFO**: legacy(RESP3) = raw map → unified = `TSInfo` object.
60. **TS.MRANGE, TS.MREVRANGE**: legacy(RESP3) = native response without a unified metadata slot → unified = dict values include `[labels, metadata, samples]` (same net effect as fact 34 for RESP2 wire).
61. **JSON.TYPE** for missing keys specifically: legacy(RESP3) = `[None]` (a one-element list containing None) → unified = `None` (bare None, not wrapped in a list). Note: this specific fact is stated only in the RESP3 table, scoped explicitly to "for missing keys."
62. **JSON.RESP**: legacy(RESP3) = numeric float leaves can appear as string/bytes → unified = float leaves become Python floats (same net effect as fact 30 for RESP2 wire).
63. **FT.SEARCH**: legacy(RESP3) = raw RESP3 result map → unified = `Result` object.
64. **FT.AGGREGATE**: legacy(RESP3) = raw RESP3 aggregate map → unified = `AggregateResult` object.
65. **FT.PROFILE**: legacy(RESP3) = `ProfileInformation(raw_response)` → unified = `(Result | AggregateResult, ProfileInformation)` (a tuple pairing the search/aggregate result with profile info, replacing the RESP3-legacy `ProfileInformation`-only return).
66. **FT.SPELLCHECK**: legacy(RESP3) = native nested spellcheck map → unified = normalized term-suggestion dict.
67. **FT.INFO, FT.CONFIG GET, FT.SYNDUMP**: legacy(RESP3) = raw structural keys → unified = string structural keys.
68. **FT.HYBRID**: legacy(RESP3) = raw native response → unified = `HybridResult`; field values remain bytes by default. (Unlike RESP2 wire where legacy already returned `HybridResult`, on RESP3 wire the legacy response is raw/unparsed and unified mode is what introduces the `HybridResult` object — but the "bytes by default" behavior for field values is consistent across both wire protocols.)

### D. FT.HYBRID-specific additional facts (from "HYBRID Command Field Decoding" section)

69. `FT.HYBRID` is explicitly described as **experimental**.
70. In unified-response mode, `FT.HYBRID` result field values and warnings are preserved as **bytes by default**, specifically to keep binary-loaded fields (example given: vector embeddings) intact.
71. To get decoded (string) field values for `FT.HYBRID`, the guide recommends setting `decode_field=True` on a per-field basis, and only for fields "known to be text values" — implying `decode_field=True` should not be used for binary/vector fields.
72. This per-field decoding is configured via `HybridPostProcessingConfig().load(field_path, decode_field=...)`, called once per field path (example shows `post.load("@title", decode_field=True)` and `post.load("@embedding", decode_field=False)`), i.e., decoding is opt-in per field rather than a single global switch for the command.
