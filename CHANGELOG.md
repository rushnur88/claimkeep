# Changelog

## Unreleased

- **Fixed: a noun that looks like a verb decided where the subject ended.**
  `extract_triple` split at the first verb-shaped token, which engineering prose
  breaks in both directions. "The pinned version is 1.2.3" opens with a
  participle, was read as an imperative, and parsed to nothing at all — so the
  statement got no topic and supersession could never apply to it. "The retry
  ceiling is 5" gave `("retry", "ceiling is", "5")`, because `-ing` looks
  verbal, putting half the subject in the predicate. A copula now settles the
  split before word shape is consulted: whatever stands in front of "is" is the
  subject. On twenty English statements of the kind these transcripts are full
  of, parsing went from 7 to 19, with nothing lost and one topic corrected.
  Tests: `tests/test_triple_copula.py`.
- **Fixed: a topic made of punctuation grouped everything it touched.** The slug
  pattern accepted runs of pure punctuation, so sentences opening with a stray
  period or dash landed under topics like `.` and `.-.` — on a corpus of 271
  briefs, 39 unrelated statements under one and 26 under another. Slug tokens
  now need at least one alphanumeric character, and a statement with nothing to
  key on gets a topic derived from its own text rather than a shared fallback.
- **Changed: only the parsed `subject|predicate` key settles claims across
  briefs.** The fallback slug is a sentence's opening words, which groups by
  phrasing rather than subject. Applying cross-brief supersession to it marked
  18.4% of a production corpus superseded against 1.0% before, nearly all of it
  statements that merely started alike. Restricted to the atomic key, the same
  corpus reads 1.1% — the corrections the mechanism was built for. Within a
  single brief the slug still groups, where the claims share one session.

- **Fixed: a corrected value stayed current in two places.** Supersession by
  topic is the mechanism `docs/BRIEF_SCHEMA.md` names for keeping a superseded
  fact from being restated, and it was failing on the case it exists for, for
  two separate reasons.

  The topic key carried the value: "the dashboard port is 3333" and "...is 4444"
  hashed to `dashboard port|be|3333` and `dashboard port|be|4444`, two unrelated
  subjects, so neither superseded the other even inside a single brief. Keying
  by the object head is right for descriptions — "my dog is friendly" and "my
  dog is brown" are both true at once — and wrong for measurements, where a
  subject holds one value at a time. Objects that state a value (a number, a
  path, a hash) now key on subject and predicate alone; descriptions are
  unchanged. Checked against 12 real transcripts: of 35 value statements, 4
  topics merged, and each was the same fact restated, not two facts colliding.

  Supersession also stopped at the file boundary. Each brief resolved its own
  claims and knew nothing of earlier ones, so a value corrected in a later
  session left the earlier reading live in the corpus and `recall` offered both
  with nothing to tell them apart. The corpus now settles each topic across
  every brief, newest wins. Nothing is deleted — a superseded claim still
  answers what used to be true, it just stops competing with the value that
  replaced it. Tests: `tests/test_cross_brief_supersession.py`.

- **Fixed: a marker still covered its neighbour on the same line.** Scoping a
  marker to the last line left the case where two sentences share one:
  `This is explicitly unmarked. Port is 3333 [C:90%]` was stored whole, so the
  unmarked sentence carried 90%. A marker now takes its own sentence — the last
  one before a trailing marker, the first one after a leading marker. The
  boundary requires whitespace after terminal punctuation, so `version 1.2.3`
  stays in one piece. Tests: `tests/test_marker_scope.py`.
- **Fixed: external corrections were lost.** Filtering the transcript to
  assistant rows fixed attribution and silently broke the other half of the
  contract: `retraction` is documented to keep corrections "from the agent and
  from anyone else", and never saw a user turn again. A user answering
  "correction: the port is 4444" vanished while the superseded 3333 stayed in
  memory unchallenged — memory that keeps the corrected value and discards the
  correction is worse than memory that keeps neither. Role is now provenance
  carried to each harvester rather than a filter at the door: `calibration`,
  `atomic`, `regex_floor` and `lessons` see the agent's own words;
  `retraction` also sees corrections; system and tool rows are claims for
  nobody. Tests: `tests/test_external_corrections.py`.
- **Fixed: a correction never marked what it refuted.** `refutes()` shipped in
  the retraction harvester and was never called from anywhere, so a brief could
  carry "the port is 3333" at 0.90 and "correction: the port is 4444" side by
  side, both under Claims as live. After compaction the agent restates whichever
  it reads first — confidently repeating something the transcript had already
  overturned, which is the failure the harvester was written to prevent.
  Corrections now mark every wording they refute (one fact usually reaches the
  brief through both `atomic` and `calibration`, and leaving the second copy
  live puts the stale value back in front of the agent). Topic-based
  supersession also stopped clearing a mark that came from outside its own
  topic, which was silently undoing the link.
- **Changed: the Codex bridge states the author of the rows it writes**
  (`{"role": "assistant", "text": ...}`). Roleless rows are still read as the
  agent's, so transcripts from older builds keep working, but a producer that
  knows the answer should not lean on the reader's default.
- **Fixed: the budget was advisory.** It counted `len(text) + 1` per item, but
  an item reaches the agent wrapped in a heading, a confidence, a topic and an
  id — and at SessionStart the marker instruction rides along too. A brief
  reporting 2,870 used characters produced 7,799 characters of context, 2.7x the
  accounting. The cap is now settled against the rendered payload, by binary
  search over the same deterministic priority order, and the report carries
  `rendered_chars`: the size the brief actually costs, not a smaller number it
  could not stand behind. Tests: `tests/test_budget_is_a_hard_cap.py`.
- **Fixed: the Codex bridge called a failed harvest a success.**
  `claimkeep precompact` is fail-open by design and exits 0 even when it wrote
  nothing, explaining itself on stderr. The bridge read that exit code as
  success, reported a `brief_path` for a file that did not exist, and — because
  rotation is gated on the same flag — archived the live transcript on the
  strength of it, losing the only unharvested copy. Success now requires a file
  that exists, is non-empty, parses as JSON and carries the schema's required
  keys, and rotation happens only after those checks. Non-empty stdout that
  decodes to no events returns an explicit `parse_error` instead of a silent
  zero. Tests: `integrations/codex/test_codex_adapter.py`.
- **Fixed: briefs were world-readable and written in place.** Under a 022 umask
  the store landed as 0755 directories and 0644 files, and the brief was written
  with a plain truncating open, so a crash mid-write replaced the previous brief
  with a truncated one. New `claimkeep/storage.py`: directories 0700, files
  0600, atomic write via a temporary file beside the target, fsync and rename,
  and appends to the lesson store and probe log take an advisory lock where the
  platform has one. Tests: `tests/test_storage_privacy.py`.

- **Fixed: a confidence marker applied to the entire message.** `calibration`
  searched for the first marker, stripped every marker, and stored the whole
  message as one claim at that first confidence. On 40 real transcripts, 45% of
  marked assistant messages carry two or more markers, so nearly half of all
  claims fused unrelated facts under one confidence and one topic — and any
  unmarked aside in the same message inherited it, which is how a sentence
  saying "this is explicitly not a fact" was stored at 90%. The fused topic slug
  also made unrelated statements look like restatements of each other, so
  supersession fired on facts that had nothing to do with one another. A marker
  is now scoped to the statement it annotates: one claim per marker, text after
  the final marker dropped because it carries none. Tests:
  `tests/test_marker_scope.py`.
- **Fixed: text the agent never wrote was harvested as the agent's claims.** The
  transcript reader kept any row containing text, so user turns, pasted
  documents, tool results and injected system blocks became claims attributed to
  the agent. On the same transcripts, rows carrying `[C:NN%]` split 1318 user to
  584 assistant: most "agent claims" had another author. In that deployment the
  user rows were an injected system prompt whose instructions *demonstrate* the
  marker syntax, so the plugin was harvesting "write [C:XX%]" as an established
  fact, at roughly 46 KB per row. Rows are now kept only when they state no
  author (the Codex bridge's `{"text": ...}`, already filtered upstream) or
  state the assistant. Tests: `tests/test_author_role.py`.
- **Changed: the measured numbers, because both defects were inside the
  measurement too.** Re-run over the same 68 compactions with the harness now
  calling the shipped author filter instead of a copy: excluding the `claim`
  family, 21.4% -> 39.7% (was 21.4% -> 37.0%), and the marker-free arm 21.4% ->
  47.5% (was 24.1%). The marker-free arm went from losing to the marked arm to
  beating it, because a brief no longer fills with injected system prompt. The
  `claim` family is now excluded from the headline: with markers scoped
  correctly, the harvester extracts almost exactly the string the probe
  extractor freezes (95% overlap measured), so that family scores regex
  agreement rather than retention. `path` retention fell, 80.2% -> 62.5%, since
  short scoped claims are packed before the supplement and crowd floor items
  out at equal budget.
- **Fixed: `parse_run` returned empty on a stdout blob.** It accepted only a
  sequence of lines, so handing it the same string `on_run_complete` takes
  iterated characters, parsed none, and returned `units=0, thread_id=None,
  usage={}` with no error — a run that simply looked empty. It now accepts
  either. Found against a live Codex CLI 0.147.0 stream, where the event schema
  itself was confirmed unchanged from 0.145.0.
- **Fixed: two tests left files open** (`test_smoke.py`, `test_empty_diagnosis.py`).

- **Fixed: the read path was partially blind in Russian.** The tokenizer matched
  `[a-z0-9]+`, so Cyrillic text contributed no tokens at all. Measured on 300
  real lesson records (74% Cyrillic): R@1 0.513 -> 0.893, R@10 0.757 -> 0.980,
  and the share of queries returning nothing went 15.3% -> 0. The "before"
  column is not zero because an engineering corpus carries hashes, versions and
  English terms — the retriever found documents through those fragments while
  missing everything phrased purely in Russian. `benchmark/russian_recall.py`
  reproduces both arms over the same corpus.
- **Added: the retraction / external-correction harvester.** Keeps lines that
  overturn something, from the agent and from anyone else, and ranks them above
  marked claims — after compaction an agent restates whatever survived with
  undiminished confidence, so a refuted claim outliving its refutation is the one
  failure a memory layer must not produce. Harvesters now accept `(role, text)`
  pairs as well as plain strings, because in a multi-agent setup a correction
  from another agent arrives as a *user* turn and an assistant-only pass loses it.

Atomic fact harvesting. Measured on LongMemEval, all 500 questions.

- **Added: the `atomic` harvester.** Selection now asks whether a person asserted
  something, instead of whether a regex matched. First-person and named-entity
  anchors keep the sentence; questions, hedges, imperatives, advice lists and
  headings are dropped. Each kept sentence carries a `subject|predicate-root`
  topic, so the supersession chain added in 0.3 finally has something to chain.
- **Added: parent boost in the read path.** Each item inherits part of its own
  brief's match, because BM25 length-normalisation made a session stored as
  eighty one-sentence documents compete very differently from the same text as
  one block. R@1 0.734 -> 0.800 with identical stored volume; retrieval still
  returns items. Strength is `CLAIMKEEP_PARENT_BOOST`, default 1.0, picked by
  measurement (0.5 scored 0.812/0.956, 1.0 scores 0.824/0.958).
- **Added: the context anchor.** 44% of long assistant turns harvested nothing
  at all, and the questions whose answer lives in an assistant turn were the
  worst-scoring category. One opening line per otherwise-empty long turn took
  that category from 0.821 to 0.929 R@10, for 2.4 points of volume. Anchoring
  every long turn instead of only empty ones cost 2 more points of volume and
  bought nothing — available as `CLAIMKEEP_CONTEXT_ANCHOR=always`, off by default.
- **Fixed: a fact stated alongside a question was thrown away with it.** "I'm
  visiting my sister Emily in Denver, do you know any kid-friendly attractions?"
  was dropped whole for its question mark. Sentences ending in a question are now
  split into clauses and the assertions kept, the interrogative parts discarded.
- **Added: `diag_misses.py` and `diag_one.py`.** The first splits remaining
  misses into lexical loss versus ranking loss — 14 of 16 were lexical, which is
  what pointed at the two fixes above. The second opens a single question and
  prints its evidence session turn by turn.
- **Measured: R@10 0.936 -> 0.958, R@1 0.734 -> 0.824** at 15.3% of the haystack.
- **Added, off by default: timestamp indexing** (`CLAIMKEEP_DATE_TOKENS`). A date
  lives in metadata, never in text, so a "last March" question cannot match it.
  Spelling it out lifted temporal-reasoning 0.955 -> 0.962 and cost multi-session
  0.977 -> 0.962, netting 0.954 against 0.958. LongMemEval spans one year, so the
  year token is shared by every document — dilution rather than signal. Kept
  behind the flag with its numbers, for corpora that span more.
- **Added, off by default: entity names in the anchor** (`CLAIMKEEP_ANCHOR_NAMES`).
  R@5 0.934 -> 0.942 but R@10 0.958 -> 0.956 and preference 0.800 -> 0.767, for
  1.1 points more volume. Sharper head, blunter tail — the wrong trade here.

- **Measured: R@10 0.456 → 0.936, R@1 0.216 → 0.734**, at 12.9% of the haystack
  stored. The previous score was not retrieval working: of the 26 turns holding
  the answer, the old harvesters produced items for **zero** of them, so the
  number came from lexical overlap with noise. Evidence coverage is now 25/26.
- **Fixed: a hedge swallowed the fact riding inside it.** "I'm wondering if I
  should repot my snake plant, which I got from my sister last month" was dropped
  whole. A hedged sentence is now kept when it is the speaker's own and carries
  something concrete; bare speculation is still dropped. Worth 1.0 point of R@10
  and 1.6 of R@1 for 0.4 points of volume.
- **Fixed: the verb root dropped a silent `-e`.** `moved` stemmed to `mov`, which
  never matched its own infinitive, so "I moved to Boston" could not supersede
  "I move to Austin".
- **Fixed: a marked sentence was harvested twice.** A sentence carrying a
  `[C:NN%]` marker now belongs to the calibration harvester alone — collecting it
  in both spent brief budget on one fact and dropped the stated confidence from
  the copy.
- **Changed: rule-extracted claims rank below marked ones in the budget.** The
  atomic harvester is far more prolific than the others; at equal weight it
  would crowd paths, ids and decisions out of a 12k brief on agent transcripts.
- **Fixed: supersession fired on non-functional relations.** "I'm interested in
  the French Resistance" and "I'm interested in astronomy" share a subject and a
  verb but are two facts, not a correction; a quarter of harvested claims were
  being flagged superseded on first contact with real data. Only relations where
  a person has one value at a time (work, live, own, drive, attend, …) supersede
  on a new object.
- **Added: kept-volume reporting in the benchmark.** `run_recall.py` now prints
  harvested characters as a share of the haystack, because a recall figure with
  no compression figure next to it can always be gamed by keeping everything.
- **Added: `diag_evidence.py`.** Scores the thing R@k hides — what fraction of
  the turns that carry the answer survive collection at all.
- `atomic` runs first in the default harvester list; the other three stay for
  agent transcripts, where markers, paths and ids are the substance.

## 0.2.0 — 2026-08-10

Installation fix. `claude plugin install claimkeep` now actually works on its own.

- **Fixed: plugin install was a silent no-op.** The plugin was declared as the `plugins/claimkeep`
  subdirectory while the Python package lived at the repository root, so the installed plugin had
  nothing to run. The hooks printed `No module named claimkeep`, exited `0`, and wrote no brief —
  a green install that did nothing. The repository root is now the plugin itself: manifest at
  `.claude-plugin/plugin.json`, hooks at `hooks/hooks.json`, scripts at `scripts/`.
- **Fixed: hooks required a separate `pip install`.** They now export `PYTHONPATH` from
  `CLAUDE_PLUGIN_ROOT` and run the bundled package in place. An installed `claimkeep` binary is
  still preferred when present.
- Removed the `plugins/` tree; `package.json` `files` updated accordingly.
- README rewritten to three blocks — what it is, how to install, how to verify — with production
  numbers and a copy-paste verification that exercises both hooks.

## 0.1.0 — 2026-06-21

Initial release: brief schema, calibration and regex-floor harvesters, redaction, rehydration,
CLI, benchmark scorer, and control/treatment probe logging.
