# ClaimKeep — Brief Schema (v1)

`schema_version: 1`. This document is the **frozen contract** between the
ClaimKeep *producer* (the PreCompact hook + harvesters) and any *consumer*
(the benchmark harness, or a downstream memory store).

The producer emits a **brief**: a compact, verbatim-grounded snapshot of a
session's high-signal claims, written *before* context compaction and
re-injected *after*. The benchmark scores how much of the brief survives a
compaction round.

> Status: **FROZEN 2026-06-21**, additively amended 2026-08-11.
> Changing the `id` rule or `normalize()` is breaking — both are load-bearing
> for the consumer's cross-run dedup; do not alter silently.
>
> The amendment adds `superseded_by` / `supersedes` on `Claim` and documents
> `source.budget`. Both were already produced; the document had not caught up,
> and a contract that does not describe its own output is not a contract.
> Nothing was removed and no meaning changed, so `schema_version` stays `1`:
> a consumer written against the original still reads these briefs correctly,
> it simply ignores two fields.

---

## 1. Top-level object

```json
{
  "schema_version": 1,
  "created_utc": "<ISO-8601 string, supplied by the caller>",
  "source": { "agent": "<str>", "session": "<str|null>", "budget": "<Budget|absent>" },
  "claims":        [ "<Claim>", "..." ],
  "supplement":    [ "<Supplement>", "..." ],
  "open_threads":  [ "<verbatim str>", "..." ],   // reserved, see below
  "last_user_ask": "<str|null>",                  // reserved, see below
  "narrative":     [ "<str>", "..." ]             // reserved, see below
}
```

**Required keys:** `schema_version`, `claims`, `supplement`.
All others are optional and default to `[]` / `null`.

`source.budget` is written when a budget was applied and records what the brief
cost and what did not fit: `budget_chars`, `used_chars`, `harvested_claims`,
`kept_claims`, `harvested_supplement`, `kept_supplement`, `dropped_items`. It is
diagnostic — a consumer never needs it to read a brief — but `dropped_items > 0`
is how you learn the budget, not the transcript, decided what survived.

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
  "source_span": "<verbatim matched line/span | null>",
  "superseded_by": "<id of the claim that replaced this one | null>",
  "supersedes": "<id of the claim this one replaced | null>"
}
```

- Claims are deduped by `id` and **superseded by `topic`**: within a topic the
  **last-added (newest) claim wins**. Earlier same-topic claims are **kept**,
  each carrying `superseded_by` pointing at the winner, and the winner carries
  `supersedes` pointing back. A consumer that only wants current state filters
  on `superseded_by is None`.
- Dropping the earlier claim instead would make a retraction indistinguishable
  from a fact that was never stated — the one thing this format is built to
  avoid. That is why the two fields exist rather than a delete.
- `topic` is the identity a claim is corrected under, so it must survive a
  restatement. It is derived from subject and predicate, not from the value
  being asserted: "the retry ceiling is 5" and "the retry ceiling is 4" share
  one topic and chain. Sentences that will not parse fall back to a slug of the
  leading words, which does not chain — a stable-looking key that is wrong
  would merge unrelated facts into a false correction.
- **Non-Latin text takes that fallback.** The subject/predicate parser is
  English-only, so a claim in Russian, Greek, Hebrew or Chinese gets the slug.
  The slug is Unicode-aware, so each statement keeps a topic of its own and
  unrelated facts stay unrelated — but because the slug contains the asserted
  value, a correction in those languages does **not** chain: "порог равен 5" and
  "порог равен 4" are two live claims, not one superseding the other. That is
  the safe half of the trade. A false retraction tells the agent a true fact was
  overturned; a missing link only withholds a hint, and the confidences still
  differ. Chaining outside English needs a morphological parser and is not in v1.
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
- `open_threads`, `last_user_ask`, `narrative` are **reserved and not produced**.
  They are part of the shape so a later version can fill them without a schema
  bump, and a consumer that reads them will get `[]` / `null` from every brief
  this version writes — not because the session had no open threads, but because
  no harvester populates the field yet. Do not build a display that implies
  otherwise; a reader who sees an empty "open threads" section concludes the
  session had none, which is a claim this format is not making. They are carried
  for rehydration UX and are **not** scored.
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

*Contract frozen 2026-06-21. Additively amended 2026-08-11: supersession fields and `source.budget` documented; `schema_version` unchanged.*
