# Ground truth fact block — redis-py "Unified Responses" migration

**Source**: `specs/unified_responses_migration_guide.md` in `redis/redis-py`,
fetched fresh via `gh api` (not from memory) at commit `0ed4b69ccc14f081bfbbb6232b04b9d113db02c5`
on the `master` branch, 2026-08-20. Verbatim text preserved at
`guide_redis_unified_responses.md` in this directory. This is the *third
migration* for the fact-block-derivation experiment — different library
(redis-py, not MCP/OpenAI), real, published, and structurally unlike either
prior guide: a table-driven per-command response-shape enumeration rather
than narrated prose, and materially less polished than the OpenAI/MCP docs
(no framing prose, no worked examples, an internal "spec companion" doc
rather than a docs-site page). Built by direct reading, before any blind
agent ran — never reconstructed from a derived agent's own output.

Built at "Area" granularity (redis-py's own grouping column), each fact
covering both wire-protocol paths (RESP2-wire-legacy and RESP3-wire-legacy)
where the guide states both, since a Python-level caller doesn't choose the
wire protocol structurally — only whether unified mode is on.

1. **Activation is opt-in and orthogonal to wire protocol.**
   `legacy_responses=False` on `redis.Redis`, `redis.asyncio.Redis`,
   `redis.cluster.RedisCluster`, or via `?legacy_responses=false` in
   `redis.from_url(...)`. Can be combined independently with `protocol=2`
   or `protocol=3`. **Scope-limiting**: omitting `legacy_responses`
   (default `True`) keeps the legacy RESP2-compatible Python shape even
   when the wire protocol defaults to RESP3 — a plain `redis.Redis()` with
   no extra kwargs is NOT affected by any shape change below.
2. **`decode_responses` is orthogonal.** Continues to control bulk-string
   decoding only; does not by itself produce any of the structural
   (list/tuple/dict) changes below.
3. **Sorted sets, score-pair commands** (`ZDIFF`, `ZINTER`, `ZRANGE`,
   `ZRANGEBYSCORE`, `ZREVRANGE`, `ZREVRANGEBYSCORE`, `ZUNION` w/
   `WITHSCORES`): RESP2-legacy flat/tuple pairs, scores often bytes →
   unified list pairs, scores as float. RESP3-legacy native arrays/scores →
   unified normalizes to the same public pair shape as RESP2-unified.
4. **`ZPOPMAX`/`ZPOPMIN`**: legacy `[(member, score)]` → unified
   `[[member, float_score]]`.
5. **`BZPOPMAX`/`BZPOPMIN`**: legacy `(key, member, score)` tuple → unified
   `[key, member, float_score]` list.
6. **`ZRANK`/`ZREVRANK` with score**: legacy `[rank, score]` (score maybe
   bytes/int) → unified `[rank, float_score]`.
7. **`ZSCAN`**: RESP2-legacy `(cursor, [(member, score)])`, raw-byte score
   cast input → unified `(cursor, [[member, score]])`, float score cast
   input. RESP3-legacy already native score pairs → unified applies same
   list-pair + float-cast normalization.
8. **`ZMPOP`/`BZMPOP`**: legacy nested tuple pairs, raw scores → unified
   nested list pairs, float scores.
9. **Random fields** (`ZRANDMEMBER` w/ scores, `HRANDFIELD` w/ values):
   legacy flat interleaved list → unified nested `[[item, value], ...]`.
10. **Blocking list pops** (`BLPOP`, `BRPOP`): legacy `(key, value)` tuple
    → unified `[key, value]` list.
11. **Streams** (`XREAD`, `XREADGROUP`): legacy `[[stream, entries], ...]`
    list → unified `{stream: entries}` dict.
12. **String algorithms** (`LCS` w/ `IDX`, `STRALGO ... IDX`): RESP2-legacy
    flat key/value list or tuple ranges → unified dict w/ string keys /
    list ranges. RESP3-legacy native RESP3 maps → unified dict w/ string
    keys and unified match-range lists.
13. **Client metadata**: `CLIENT TRACKINGINFO` — RESP2-legacy flat list →
    unified dict w/ string keys + decoded string lists; RESP3-legacy
    native RESP3 map → same unified target. `CLIENT GETNAME` (RESP3 row
    only) — legacy bytes scalar → unified string scalar.
14. **Command metadata** (`COMMAND`): RESP2-legacy `flags` as list →
    unified `flags` **and** `acl_categories` as sets of strings.
    RESP3-legacy native metadata → same unified target.
15. **ACL**: `ACL GETUSER` (RESP2 row only) — legacy selector flat lists →
    unified selector dicts. `ACL LOG` — RESP2-legacy string/bytes scalars →
    unified `age-seconds` as float + `client-info` as dict; RESP3-legacy
    map w/ string-like scalars → same unified target. `ACL CAT`/`HELP`/
    `LIST`/`USERS` (RESP3 row only) — legacy lists of bytes → unified lists
    of strings. `ACL GENPASS`/`WHOAMI` (RESP3 row only) — legacy bytes
    scalar → unified string scalar.
16. **Sentinel** (`SENTINEL MASTER`/`MASTERS`/`SLAVES`/`SENTINELS`):
    RESP2-legacy `flags` as comma-string → unified `flags` as a set plus
    derived booleans. RESP3-legacy native state maps → same unified
    target.
17. **Cluster** (`CLUSTER LINKS`, `CLUSTER SHARDS`): RESP2-legacy raw byte
    structural keys → unified string structural keys. RESP3-legacy native
    maps w/ raw structural keys → same unified target.
18. **Geo — asymmetric, watch closely.** `GEOPOS`: RESP2-legacy coordinate
    tuples → unified coordinate **lists** (a real shape change); RESP3-legacy
    already list coordinates → unified list coordinates — **NOT a shape
    change on the RESP3 path**. `GEOSEARCH`/`GEORADIUS`/
    `GEORADIUSBYMEMBER` with coordinates: RESP2-legacy tuple coordinates →
    unified tuple coordinates — **explicitly NOT a shape change on RESP2**;
    RESP3-legacy list coordinates → unified **tuple** coordinates — this
    direction IS a shape change, and it's the *opposite* transformation
    from `GEOPOS`'s RESP2 case (tuple→list there, list→tuple here).
    `GEOHASH` (RESP3 row only): legacy list of bytes → unified list of
    strings.
19. **Functions** (`FUNCTION LIST`, RESP2 row only): legacy flat sublists →
    unified nested dictionaries.
20. **Memory** (`MEMORY STATS`, RESP2 row only): legacy raw string-like
    values → unified structural keys decoded, numeric values native.
21. **JSON**: `JSON.NUMINCRBY`/`JSON.NUMMULTBY` (RESP2 row only) — legacy
    scalar path → unified JSONPath-compatible array behavior. `JSON.RESP` —
    RESP2-legacy float values can be string leaves → unified float leaves
    become Python floats; RESP3-legacy numeric float leaves can be
    string/bytes → same unified target. `JSON.OBJKEYS` (RESP2 row only) —
    legacy keys forced to strings → unified keys respect `decode_responses`.
    `JSON.TYPE` for missing keys (RESP3 row only) — legacy `[None]` →
    unified `None`.
22. **TimeSeries**: `TS.GET`/`TS.RANGE`/`TS.REVRANGE` (RESP2 row only) —
    legacy tuples → unified lists. `TS.MGET` (RESP2 row only) — legacy
    sorted list of dicts → unified dict keyed by series. `TS.MRANGE`/
    `TS.MREVRANGE` — RESP2-legacy dict/list w/o metadata slot → unified
    dict values include `[labels, metadata, samples]`; RESP3-legacy native
    response w/o metadata slot → same unified target. `TS.QUERYINDEX`
    (RESP2 row only) — legacy numeric-looking keys can be coerced →
    unified keys preserved. `TS.INFO` (RESP3 row only) — legacy raw map →
    unified `TSInfo` object.
23. **RediSearch**: `FT.INFO` — RESP2-legacy attribute flat sublists →
    unified attribute dicts w/ `flags`; also grouped in a RESP3 row with
    `FT.CONFIG GET`/`FT.SYNDUMP` — legacy raw structural keys → unified
    string structural keys. `FT.CONFIG GET` (RESP2 row) — legacy bytes
    keys/values → unified string keys/values. `FT.SEARCH` — RESP2-legacy
    `Result` w/o unified warnings surface → unified `Result` w/ `warnings`;
    RESP3-legacy raw RESP3 result map → unified `Result` object.
    `FT.AGGREGATE` — RESP2-legacy `AggregateResult` w/o unified
    total/warnings → unified `AggregateResult` w/ `total` + `warnings`;
    RESP3-legacy raw aggregate map → unified `AggregateResult` object.
    `FT.PROFILE` — RESP2-legacy "parsed tuple, legacy profile data" →
    unified "parsed tuple, unified profile data"; RESP3-legacy
    `ProfileInformation(raw_response)` → unified
    `(Result | AggregateResult, ProfileInformation)`. `FT.SPELLCHECK`
    (RESP3 row only) — legacy native nested spellcheck map → unified
    normalized term-suggestion dict. `FT.HYBRID` — RESP2-legacy
    `HybridResult`, bytes by default → unified `HybridResult`, bytes
    preserved by default (**explicitly stated as matching — NOT a shape
    change on RESP2**); RESP3-legacy raw native response → unified
    `HybridResult`, field values remain bytes by default.
24. **Probabilistic**: `TOPK.ADD`/`TOPK.INCRBY`/`TOPK.LIST` (RESP2 row
    only) — legacy numeric-looking item names can be coerced → unified
    item names preserved. `BF.INFO`/`CF.INFO`/`CMS.INFO`/`TOPK.INFO`/
    `TDIGEST.INFO` (RESP3 row only) — legacy raw maps → unified rich info
    objects. `TDIGEST.BYRANK`/`BYREVRANK`/`CDF`/`QUANTILE` (RESP3 row
    only) — legacy raw lists → unified parsed lists w/ numeric and
    special-value handling.
25. **`FT.HYBRID` field-decoding caveat (explicit scope-limiting note).**
    `FT.HYBRID` is experimental. Unified responses preserve result field
    values and warnings as bytes **by default** (protects binary payloads
    like vector embeddings) — not overridden by `decode_responses`; opt in
    per-field via `decode_field=True` on
    `HybridPostProcessingConfig.load(...)`.

**Not counted as a "fact" for scoring** (procedural, not a breaking-change
statement): the six-item "Migration Checklist" section — it's rollout
guidance, not a per-symbol change description, and has no equivalent in
either prior migration's fact block. Noted here so its absence from a
derived fact block is not miscounted as a miss.
