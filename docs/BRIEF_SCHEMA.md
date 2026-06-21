# ClaimKeep — Brief Schema (v1)

`schema_version: 1`. This document is the **frozen contract** between the
ClaimKeep *producer* (the PreCompact hook + harvesters) and any *consumer*
(the benchmark harness, or a downstream memory store).

The producer emits a **brief**: a compact, verbatim-grounded snapshot of a
session's high-signal claims, written *before* context compaction and
re-injected *after*. The benchmark scores how much of the brief survives a
compaction round.

> Status: **FROZEN 2026-06-21**.
> Changing the `id` rule or `normalize()` is breaking — both are load-bearing
> for the consumer's cross-run dedup; do not alter silently.

---

## 1. Top-level object

```json
{
  "schema_version": 1,
  "created_utc": "<ISO-8601 string, supplied by the caller>",
  "source": { "agent": "<str>", "session": "<str|null>" },
  "claims":        [ "<Claim>", "..." ],
  "supplement":    [ "<Supplement>", "..." ],
  "open_threads":  [ "<verbatim str>", "..." ],
  "last_user_ask": "<str|null>",
  "narrative":     [ "<str>", "..." ]
}
```

**Required keys:** `schema_version`, `claims`, `supplement`.
All others are optional and default to `[]` / `null`.

The producer **never reads the wall clock** — `created_utc` and any `ts` are
supplied by the caller so that a given (transcript, config) pair is fully
reproducible. In the bundled CLI, the `precompact` command is that caller and
stamps `created_utc` from the system clock unless `--now` is passed; the core
library (`brief.py`) and the harvesters stay clock-free. `created_utc` is never
hashed into an `id` and is never scored.

---

## 2. `Claim` — high-signal, harvested

```json
{
  "id": "<16-hex str>",
  "text": "<verbatim claim text>",
  "confidence": "<float 0.0..1.0 | null>",
  "topic": "<short str>",
  "source_harvester": "<harvester name, e.g. 'calibration'>",
  "ts": "<ISO-8601 | null>",
  "source_span": "<verbatim matched line/span | null>"
}
```

- Claims are deduped by `id` and **superseded by `topic`**: within a topic the
  **last-added (newest) claim wins** and earlier same-topic claims are dropped.
  An explicit retraction flag is out of scope for v1.
- `source_span` is **best-effort in v1** (`null` where a harvester cannot supply
  it) — it grounds blind-EXACT scoring.

---

## 3. `Supplement` — the floor (ids / paths / decisions caught WITHOUT markers)

```json
{
  "id": "<16-hex str>",
  "text": "<verbatim str>",
  "kind": "id | path | decision",
  "source_harvester": "<harvester name, e.g. 'regex_floor'>"
}
```

`source_harvester` is present on **both** `Claim` and `Supplement` so the
consumer can report retention split by harvester (see §5).

---

## 4. Deterministic `id`

```
id = sha1( source_harvester + "|" + middle + "|" + normalize(text) ).hexdigest()[:16]
```

- `middle` = `topic` for a `Claim`, `kind` for a `Supplement`.
- **Deterministic, not a uuid:** the same logical item yields the same id across
  runs. That is exactly what lets the benchmark map one frozen probe to one item
  across N runs, and what powers cross-run dedup.

### `normalize(text)` — id-hash input ONLY

The stored `text` keeps its original casing; `normalize()` is applied **only** to
the bytes fed into the hash.

1. Unicode **NFC**
2. **casefold()**  — unicode lowercase
3. **strip()**     — trim leading / trailing whitespace
4. **collapse** every run of whitespace (space / tab / newline) to a single `U+0020`
5. **punctuation is preserved** — so paths / ids in `supplement` never collide

*Why casefold:* an item should map to the same id across runs even when only
sentence-initial capitalisation drifts. The verbatim `text` field keeps the
original casing, so blind-EXACT grounding is unaffected.

---

## 5. Scoring scope (consumer contract)

- Retention is scored **only** against `claims[]` + `supplement[]`.
- `open_threads`, `last_user_ask`, `narrative` are carried for rehydration UX and
  are **not** scored.
- Retention SHOULD be reported **split by `source_harvester`** (calibration vs
  floor). That split is the headline result: it tests whether an agent's own
  calibration discipline doubles as memory, and quantifies the marker-free floor.

---

## 6. Producer invariants

- `claims == []` is a **valid brief** (an agent that emits no markers). The floor
  harvester still yields `supplement[]`. This is the floor / near-baseline arm,
  and is covered by the unit test `zero markers -> valid brief`.
- The producer is **non-blocking** and **stdlib-only** (no third-party deps).
- A **secret / PII redaction pass runs before harvesting** (`Config.redact`, on by
  default), so `claims[]`, `supplement[]`, and `source_span` never carry masked
  credentials or personal data. `created_utc` and scoring are unaffected.

---

*Contract frozen 2026-06-21. First version.*
