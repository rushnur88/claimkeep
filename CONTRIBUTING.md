# Contributing

## Setup

```bash
git clone https://github.com/rushnur88/claimkeep
cd claimkeep
python3 -m unittest discover -s tests
```

That is the whole setup. The package has no dependencies and the tests use only
the standard library, so there is nothing to install and no virtualenv to
create. CI asserts both on every push — if a third-party import ever reaches
`claimkeep/`, the build fails.

Python 3.9 is the floor. CI runs 3.9, 3.11 and 3.13.

## Before opening a pull request

```bash
python3 -m unittest discover -s tests          # the suite

# Set CLAIMKEEP_BRIEF_DIR, or the hook writes into the briefs your own sessions
# use and you will be reading test output as real memory later.
CLAIMKEEP_BRIEF_DIR=/tmp/ck-dev ./scripts/precompact.sh <<< \
  '{"transcript_path": "examples/sample_transcript.jsonl"}'
```

The second line is worth running by hand at least once. Both hooks are fail-open
by construction — they exit `0` no matter what goes wrong, so a broken change
looks exactly like a working one from the exit code alone. Errors go to stderr;
read them.

## What a good change looks like here

**Bring a failing input, not a description.** Every bug fixed in this repository
so far was found by feeding a transcript through the plugin and reading what
reached the brief — not by reading the code. Secrets leaked past a regex that
looked correct, corrections failed to chain for reasons invisible in the
function that built the key, and a report printed a confident `0` where it could
not measure anything. A test that fails before your fix and passes after is the
argument; the explanation is context.

**A test that passes on the unfixed code is not a test.** Check it: revert your
change, run the suite, confirm your test fails, then restore. Several tests here
were written that way and caught real regressions later.

**Do not let a metric invent a number.** If something cannot be measured — no
data, no instrumentation, a brief from a different collector — the report says
`not measurable` and the JSON says `null`. Never `0`. A zero a reader cannot
distinguish from "never happened" is the failure this package exists to avoid,
and it has appeared inside the package more than once.

**Do not assume English.** The harvesters, the tokenizer and the redaction cues
all handle non-Latin text, and each of those was a bug before it was a feature:
a Latin-only tokenizer made an entire corpus invisible to search, and a
Latin-only topic slug made unrelated Russian claims mark each other retracted.
If you add a rule that keys on a word, add it in more than one language, or key
on shape instead.

**Keep the brief contract honest.** `docs/BRIEF_SCHEMA.md` is the contract
between the producer and anything downstream. If you change what a brief
contains, change that document in the same commit. A contract that does not
describe its own output is not a contract — it drifted once already.

## Commit messages

Say what was wrong and how you know it is fixed. The history here is meant to be
readable a year from now by someone deciding whether to trust a claim in the
README, so a message that names the failing input and the verification is worth
more than one that names the function.

## Scope

ClaimKeep is deliberately narrow: harvest an agent's own high-signal statements
before compaction, put them back after. It is not a general memory store, not a
retrieval framework, and not a replacement for native compaction — it augments
it, which is why it cannot end up worse than the default.

Ideas that widen that scope are welcome as issues, but expect the first question
to be whether the narrow thing still does its job better with the change.

## Reporting security issues

Not here — see [SECURITY.md](SECURITY.md).
