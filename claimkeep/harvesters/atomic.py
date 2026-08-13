"""Atomic fact harvester: keep what a person actually stated about their world.

Why this exists
---------------
The three earlier harvesters were built for agent transcripts. Measured on
LongMemEval — human chat, 500 questions — they kept 11.8% of turns and produced
**zero** items on the 26 turns that actually carried the answer. The retriever
was fine (R@10 0.982 reading the haystack directly); the collector was blind.

So the failure was never "we need triples instead of regexes". It was two
concrete things:

1. **Selection.** `DECISION_RE` fired on any sentence containing a choice verb,
   so "there are many destinations perfect for a romantic getaway" was stored
   while "I adopted a rescue dog last month" was not. The recogniser had no
   notion of who is speaking or whether anything was actually asserted.
2. **Topic.** Kept items were flat strings with no subject, so two statements
   about the same thing at different times could not be related, and the
   supersession chain added in v0.3 had nothing to chain.

This harvester fixes both. It keeps a sentence when a person asserts something
about themselves or about a named entity, and it assigns each kept sentence a
topic of `subject|predicate-root` so a later statement on the same topic
supersedes the earlier one instead of sitting beside it.

Design notes
------------
The stored text is the cleaned sentence, not the bare triple. The triple is what
the topic is derived from; the sentence is what the reader matches against.
Storing only `my car | is | a Subaru` would throw away the modifiers that lexical
retrieval needs to hit, and the read path is lexical by contract.

Everything here is stdlib and rule-based. No model, no download, no runtime
dependency — same contract as the read path. The cost is honest: rule-based
extraction on English prose misses inverted and heavily subordinated sentences,
and it is English-shaped. That is a stated limitation, not a hidden one.
"""

from __future__ import annotations

import os
import re
from typing import List, Optional, Sequence, Set, Tuple

from ..brief import Claim, normalize
from ..config import Config
from .base import Harvester

# --- sentence splitting -----------------------------------------------------

_ABBREV = {
    "mr",
    "mrs",
    "ms",
    "dr",
    "prof",
    "sr",
    "jr",
    "st",
    "vs",
    "etc",
    "e.g",
    "i.e",
    "inc",
    "ltd",
    "co",
    "approx",
    "dept",
    "est",
    "fig",
    "no",
    "vol",
    "am",
    "pm",
}
_SENT_END = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> List[str]:
    """Split on sentence enders, re-joining splits that landed after an abbreviation."""
    if not text:
        return []
    raw = _SENT_END.split(text.replace("\n", " "))
    out: List[str] = []
    for piece in raw:
        piece = piece.strip()
        if not piece:
            continue
        if out:
            tail = out[-1].rstrip(".").rsplit(" ", 1)[-1].casefold()
            if tail in _ABBREV:
                out[-1] = out[-1] + " " + piece
                continue
        out.append(piece)
    return out


# --- selection --------------------------------------------------------------

# First-person and possessive anchors. A statement anchored to the speaker is
# the single strongest signal that something was asserted rather than discussed.
_PERSONAL = re.compile(
    r"(?i)\b(i|i'm|i've|i'd|i'll|im|my|mine|myself|we|we're|we've|our|ours|us)\b"
)

# Hedged or hypothetical: the sentence describes a possibility, not a fact.
_HYPOTHETICAL = re.compile(
    r"(?i)\b(would|could|might|may|should|shall|if|whether|unless|imagine|suppose|"
    r"perhaps|maybe|probably|possibly|hopefully|wish|wondering|consider|"
    r"depends|depending|assuming|ideally|generally|typically|usually often)\b"
)

# Generic openers: assistant prose, listicles, advice. None of it is a fact
# about the speaker, and all of it used to be harvested.
_GENERIC_OPENER = re.compile(
    r"(?i)^\s*(there\s+(is|are|was|were)|here\s+(is|are)|it\s+(is|was|can|could|"
    r"would|might|may|helps|depends)|it's|that's|this\s+(is|can|could|would)|"
    r"you\s+(can|could|should|might|may|will|want|need)|one\s+(of|way|option)|"
    r"some\s+(people|options|ideas)|many\s+(people|options)|"
    r"a\s+(few|couple)\s+(of\s+)?(ideas|options|tips)|"
    r"let\s+me|let's|sure[,!]|of\s+course|absolutely|great\s+question|"
    r"consider|try|make\s+sure|remember\s+to|check\s+out|feel\s+free|"
    r"i\s+(can|could|would)\s+(help|suggest|recommend)|"
    r"here\s+are|below\s+(is|are)|for\s+example|in\s+general)\b"
)

# Second-person advice anywhere in the sentence is assistant register.
_ADVICE = re.compile(
    r"(?i)\b(you\s+(can|should|could|might|may|will|want\s+to|need\s+to))\b"
)

# Assistant politeness and framing, anywhere in the sentence rather than only at
# the start: "Now, let's get moving!" opens on an adverb and still is not a fact.
_ASSISTANT_REGISTER = re.compile(
    r"(?i)\b(happy\s+to\s+help|hope\s+(these|this|that|it)|kudos|let's|lets\s+get|"
    r"feel\s+free|great\s+question|i\s+(can|could)\s+help|i'd\s+(recommend|suggest)|"
    r"i\s+(recommend|suggest)\b|as\s+an\s+ai|keep\s+in\s+mind|good\s+luck|"
    r"don't\s+hesitate|hope\s+you|glad\s+to)\b"
)

# Imperatives are instructions, not assertions. Rule-based detection of a bare
# verb head is the cheapest reliable signal, and instruction prose is exactly
# what flooded the first run: "Aim for 3-5 minutes", "Hold for 5-10 breaths".
_IMPERATIVE_HEADS = {
    "aim",
    "try",
    "incorporate",
    "hold",
    "stay",
    "find",
    "avoid",
    "end",
    "begin",
    "start",
    "keep",
    "use",
    "take",
    "make",
    "add",
    "include",
    "consider",
    "focus",
    "ensure",
    "remember",
    "choose",
    "pick",
    "set",
    "place",
    "put",
    "do",
    "don't",
    "dont",
    "let",
    "check",
    "look",
    "see",
    "read",
    "write",
    "practice",
    "repeat",
    "breathe",
    "drink",
    "eat",
    "walk",
    "run",
    "stretch",
    "apply",
    "mix",
    "combine",
    "prepare",
    "serve",
    "cook",
    "bake",
    "store",
    "wash",
    "clean",
    "contact",
    "call",
    "visit",
    "book",
    "schedule",
    "plan",
    "review",
    "monitor",
    "track",
    "measure",
    "adjust",
    "reduce",
    "increase",
    "limit",
    "allow",
    "wear",
    "bring",
    "pack",
    "save",
    "spend",
    "invest",
    "consult",
    "speak",
    "talk",
    "ask",
    "tell",
    "share",
    "join",
    "sign",
    "register",
    "download",
    "install",
    "open",
    "close",
    "select",
    "enable",
    "disable",
    "explore",
    "discover",
    "enjoy",
    "rest",
    "relax",
    "sit",
    "stand",
    "lie",
    "lift",
    "push",
    "pull",
    "hydrate",
    "warm",
    "cool",
    "note",
    "opt",
    "swap",
    "replace",
    "rotate",
    "alternate",
    "schedule",
    "reach",
    "aim",
}

# Advice lists. A leading bullet, number or bold run is formatting an assistant
# uses and a person in chat almost never does.
_LIST_ITEM = re.compile(r"^\s*(\*+|-|•|\d+[.)])\s")
_BOLD_HEAD = re.compile(r"^\s*\*\*[^*]+\*\*\s*[:\-]")

# Time and quantity anchors. Bare `day`, `week` or `now` are ordinary words and
# were letting generic prose through, so only anchored forms count.
_CONCRETE = re.compile(
    r"(?i)(\b\d+\b|\b(january|february|march|april|may|june|july|august|september|"
    r"october|november|december|monday|tuesday|wednesday|thursday|friday|saturday|"
    r"sunday|yesterday|tomorrow|tonight)\b|"
    r"\b(last|next|this|past)\s+(year|month|week|weekend|summer|winter|spring|fall|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|night|semester)\b|"
    r"\b\w+\s+ago\b|\bsince\s+\w+|\bin\s+(19|20)\d{2}\b)"
)

_PROPER = re.compile(r"(?<!^)(?<![.!?]\s)\b[A-Z][a-zA-Z]{2,}\b")

# A question addressed to the assistant, or the interrogative half of a sentence
# that also states a fact. "I'm visiting my sister Emily in Denver, do you know
# any kid-friendly attractions?" is one sentence carrying both.
_INTERROGATIVE = re.compile(
    r"(?i)^\s*(what|where|when|which|who|whom|whose|why|how|do|does|did|can|could|"
    r"would|should|is|are|was|were|have|has|any|please)\b|\b(do|did|can|could|would|"
    r"will|have)\s+you\b|\bany\s+(suggestions|ideas|recommendations|tips)\b"
)
_CLAUSE_SPLIT = re.compile(r"\s*(?:[,;]|\band\b|\bbut\b|\bso\b)\s+")

MIN_TOKENS = 4
MAX_TOKENS = 45
_WORD = re.compile(r"[A-Za-z0-9']+")


def _tokens(text: str) -> List[str]:
    return _WORD.findall(text)


def is_factual(sentence: str) -> bool:
    """True when a person asserted something, rather than discussed or advised."""
    stripped = sentence.strip()
    if not stripped or stripped.endswith("?"):
        return False
    words = _tokens(stripped)
    if not (MIN_TOKENS <= len(words) <= MAX_TOKENS):
        return False
    if _GENERIC_OPENER.search(stripped) or _ADVICE.search(stripped):
        return False
    if _ASSISTANT_REGISTER.search(stripped):
        return False
    if _BOLD_HEAD.match(stripped):
        return False
    personal = bool(_PERSONAL.search(stripped))
    if _LIST_ITEM.match(stripped) and not personal:
        return False
    concrete_early = bool(_CONCRETE.search(stripped)) or bool(_PROPER.search(stripped))
    if _HYPOTHETICAL.search(stripped):
        # A hedge usually wraps a plan, not a fact — but a fact can ride inside
        # one: "I'm wondering if I should repot my snake plant, which I got from
        # my sister last month" was dropped whole, and with it the only mention
        # of the plant. Keep the sentence when it is both the speaker's and
        # carries something concrete; drop the bare speculation.
        if not (personal and concrete_early):
            return False
    head = words[0].casefold().strip("*")
    if head in _IMPERATIVE_HEADS:
        return False
    # "Radiation sources: photons, electrons" — a heading, not an assertion.
    colon = stripped.find(":")
    if 0 <= colon <= 60 and not personal:
        return False
    concrete = bool(_CONCRETE.search(stripped)) or bool(_PROPER.search(stripped))
    # Personal statements stand on their own. An impersonal sentence has to
    # carry something concrete — a date, a quantity, a name — to earn its place.
    return personal or concrete


def factual_parts(sentence: str) -> List[str]:
    """Assertions inside a sentence, including one that ends in a question mark.

    People state facts and ask about them in a single breath: "I adopted a
    rescue dog last month, any tips for crate training?" Dropping the sentence
    for its question mark discarded the only mention of the dog — measured on
    LongMemEval, that class accounted for most of the remaining recall loss.
    """
    stripped = sentence.strip()
    if not stripped.endswith("?"):
        return [stripped] if is_factual(stripped) else []
    body = stripped.rstrip("?").strip()
    parts = [p.strip() for p in _CLAUSE_SPLIT.split(body) if p.strip()]
    if len(parts) < 2:
        return []
    kept = []
    for part in parts:
        if _INTERROGATIVE.search(part):
            continue
        if is_factual(part):
            kept.append(part)
    return kept


# --- triple extraction ------------------------------------------------------

_AUX = {
    "am",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "get",
    "got",
    "gets",
    "will",
    "wo",
    "ca",
    "'m",
    "'re",
    "'ve",
    "'s",
    "'ll",
}

# Content verbs seen in personal narration. The list is not exhaustive by
# design: the morphological fallback below catches the rest, and a wrong verb
# guess costs a slightly noisier topic, not a lost sentence.
_VERBS = {
    "work",
    "works",
    "worked",
    "working",
    "live",
    "lives",
    "lived",
    "living",
    "move",
    "moved",
    "moving",
    "buy",
    "buys",
    "bought",
    "buying",
    "sell",
    "sold",
    "start",
    "started",
    "starting",
    "stop",
    "stopped",
    "finish",
    "finished",
    "begin",
    "began",
    "join",
    "joined",
    "leave",
    "left",
    "quit",
    "adopt",
    "adopted",
    "study",
    "studied",
    "studying",
    "teach",
    "taught",
    "learn",
    "learned",
    "learnt",
    "read",
    "write",
    "wrote",
    "play",
    "played",
    "playing",
    "run",
    "ran",
    "running",
    "train",
    "trained",
    "training",
    "travel",
    "traveled",
    "travelled",
    "visit",
    "visited",
    "plan",
    "planned",
    "planning",
    "book",
    "booked",
    "take",
    "took",
    "taking",
    "make",
    "made",
    "making",
    "build",
    "built",
    "cook",
    "cooked",
    "eat",
    "ate",
    "drink",
    "drank",
    "like",
    "likes",
    "liked",
    "love",
    "loves",
    "loved",
    "prefer",
    "prefers",
    "preferred",
    "hate",
    "hated",
    "enjoy",
    "enjoyed",
    "want",
    "wanted",
    "need",
    "needed",
    "own",
    "owns",
    "owned",
    "keep",
    "kept",
    "use",
    "used",
    "drive",
    "drove",
    "driving",
    "fly",
    "flew",
    "switch",
    "switched",
    "change",
    "changed",
    "decide",
    "decided",
    "choose",
    "chose",
    "pick",
    "picked",
    "name",
    "named",
    "call",
    "called",
    "meet",
    "met",
    "marry",
    "married",
    "graduate",
    "graduated",
    "retire",
    "retired",
    "volunteer",
    "volunteered",
    "attend",
    "attended",
    "sign",
    "signed",
    "order",
    "ordered",
    "pay",
    "paid",
    "save",
    "saved",
    "spend",
    "spent",
    "earn",
    "earned",
    "grow",
    "grew",
    "growing",
    "raise",
    "raised",
    "manage",
    "managed",
    "lead",
    "led",
    "found",
    "founded",
    "launch",
    "launched",
    "hire",
    "hired",
    "apply",
    "applied",
    "accept",
    "accepted",
    "reject",
    "rejected",
}

# Only `-ed` and `-ing` survive as a morphological verb signal. Allowing `-s`
# made every plural noun look finite ("radiation sources: photons, electrons"),
# which is how a lecture outline ended up stored as a personal fact.
_VERB_SUFFIX = re.compile(r"(?i)^[a-z]+(ed|ing)$")
_STOP_HEAD = {
    "the",
    "a",
    "an",
    "and",
    "but",
    "so",
    "then",
    "also",
    "just",
    "well",
    "actually",
}


def _looks_verbal(token: str) -> bool:
    low = token.casefold()
    if low in _AUX or low in _VERBS:
        return True
    # Third-person `-s` of a known verb. It cannot come from the morphological
    # rule below, because allowing bare `-s` there turns every plural noun into
    # a verb; bounded by the vocabulary it is safe, and without it "my daughter
    # plays piano" was dropped for having no finite verb.
    if low.endswith("s") and low[:-1] in _VERBS:
        return True
    if low.endswith("es") and low[:-2] in _VERBS:
        return True
    # Morphological fallback for verbs outside the list. Short tokens and known
    # non-verb endings are excluded to keep the false-positive rate down.
    if len(low) > 4 and _VERB_SUFFIX.match(low):
        return not low.endswith(("ness", "ings", "ties", "cies", "ous", "ies"))
    return False


def _verb_root(token: str) -> str:
    """Crude stem so `worked`, `working` and `works` share one topic."""
    low = token.casefold().strip("'")
    if low in {
        "am",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "'m",
        "'re",
        "'s",
    }:
        return "be"
    if low in {"have", "has", "had", "'ve"}:
        return "have"
    if low in {"do", "does", "did"}:
        return "do"
    for suffix, cut in (
        ("ying", 4),
        ("ing", 3),
        ("ied", 3),
        ("ed", 2),
        ("es", 2),
        ("s", 1),
    ):
        if low.endswith(suffix) and len(low) - cut >= 3:
            stem = low[: len(low) - cut]
            if suffix == "ying":
                return stem + "y"
            if suffix in ("ing", "ed") and len(stem) > 2 and stem[-1] == stem[-2]:
                stem = stem[:-1]  # stopped -> stop
            # `moved` -> `mov` unless the silent -e is restored, and a root that
            # does not match its own infinitive breaks topic identity: "I moved
            # to Boston" would not supersede "I move to Austin".
            if stem not in _VERBS and (stem + "e") in _VERBS:
                return stem + "e"
            return stem
    return low


def extract_triple(sentence: str) -> Optional[Tuple[str, str, str]]:
    """Split a sentence at its first finite verb into subject / predicate / object."""
    words = _tokens(sentence)
    if len(words) < 3:
        return None
    start = 0
    while start < len(words) and words[start].casefold() in _STOP_HEAD:
        start += 1
    for index in range(start, min(len(words) - 1, start + 9)):
        token = words[index]
        if index == start and token.casefold() not in {"i", "we", "my", "our"}:
            # A sentence opening on a verb is an imperative, not an assertion.
            if _looks_verbal(token):
                return None
        if index > start and _looks_verbal(token):
            subject = " ".join(words[start:index]) or "i"
            end = index + 1
            # Absorb the auxiliary chain: "have been working" is one predicate.
            while end < len(words) and words[end].casefold() in _AUX:
                end += 1
            if end < len(words) and _looks_verbal(words[end]):
                end += 1
            predicate = " ".join(words[index:end])
            obj = " ".join(words[end:])
            return subject, predicate, obj
    return None


# Relations where a person has one value at a time. A new object on one of these
# replaces the old one — that is what supersession is for. Everything else is
# additive: "I'm interested in the French Resistance" and "I'm interested in
# astronomy" are two facts, not a correction, and treating them as one hid a
# quarter of the harvested claims behind a superseded flag on the first run.
_FUNCTIONAL = {
    "work",
    "live",
    "move",
    "own",
    "drive",
    "weigh",
    "marry",
    "name",
    "attend",
    "study",
    "retire",
    "graduate",
    "rent",
    "commute",
    "major",
}

_OBJECT_STOP = {
    "a",
    "an",
    "the",
    "to",
    "of",
    "in",
    "on",
    "at",
    "for",
    "with",
    "about",
    "my",
    "your",
    "our",
    "their",
    "his",
    "her",
    "its",
    "some",
    "any",
    "more",
    "very",
    "really",
    "quite",
    "just",
    "also",
    "been",
    "being",
    "and",
    "but",
    "that",
    "this",
    "these",
    "those",
    "it",
    "them",
    "into",
    "from",
    "by",
}


def _object_head(obj: str) -> str:
    """First content word of the object — the thing the statement is about."""
    for token in _tokens(obj):
        low = token.casefold()
        if low not in _OBJECT_STOP and len(low) > 2:
            return low
    return ""


_VALUE_RX = re.compile(r"\d")
_PATHLIKE_RX = re.compile(r"[/\\]|^[0-9a-f]{7,40}$")


def _states_a_value(obj: str) -> bool:
    """True when the object is a measurement rather than a description.

    A subject holds one port, one version, one path at a time, so a later
    reading corrects the earlier one. It holds any number of descriptions at
    once — "my dog is friendly" and "my dog is brown" are both true — which is
    why the object head is in the key to begin with.

    Keying measurements by value defeated supersession on precisely the case it
    exists for: "the dashboard port is 3333" and "...is 4444" became
    `dashboard port|be|3333` and `dashboard port|be|4444`, two unrelated
    subjects, and both stayed live in the brief and in recall.
    """
    for token in _tokens(obj):
        low = token.casefold()
        if low in _OBJECT_STOP:
            continue
        if _VALUE_RX.search(low) or _PATHLIKE_RX.search(low):
            return True
        return False  # first content word decides
    return False


def _topic(subject: str, predicate: str, obj: str = "") -> str:
    """`my dog|be` — stable across restatements, so supersession can chain.

    For non-functional relations the object head joins the key, which keeps two
    unrelated statements from colliding into a false correction — unless the
    object states a value, where a restatement is a correction and the key must
    stay the same across it.
    """
    subject_tokens = [w for w in _tokens(subject) if w.casefold() not in _STOP_HEAD]
    subject_key = " ".join(subject_tokens[-3:]).casefold() or "speaker"
    verb_tokens = [
        w for w in _tokens(predicate) if w.casefold() not in _AUX
    ] or _tokens(predicate)
    root = _verb_root(verb_tokens[-1]) if verb_tokens else "be"
    if root in _FUNCTIONAL or _states_a_value(obj):
        return subject_key + "|" + root
    head = _object_head(obj)
    return subject_key + "|" + root + ("|" + head if head else "")


# A long assistant answer that yields no assertion still names its subject in
# the opening line - "Yoga is an excellent way to start the day", "Foam rolling
# is an excellent addition to your routine". Measured on LongMemEval, 44% of
# long assistant turns harvested nothing at all, and the questions whose answer
# lives in an assistant turn were the worst-scoring category. Keeping one
# topical anchor per otherwise-empty long turn costs one sentence and restores
# the lexical handle.
_ANCHOR_MODE = os.environ.get("CLAIMKEEP_CONTEXT_ANCHOR", "1").strip().lower()
CONTEXT_ANCHOR = _ANCHOR_MODE not in ("0", "false", "off")
# "always" also anchors long turns that did yield an assertion, on the theory
# that the opening line names the subject while the kept sentences discuss it.
ANCHOR_ALWAYS = _ANCHOR_MODE == "always"
ANCHOR_MIN_CHARS = 200
ANCHOR_MAX_CHARS = 220
# Long answers name things the opening line does not: product models, place
# names, people. Appending the distinct names keeps a lexical handle on them
# without storing the list they were embedded in. Measured: R@5 0.934 -> 0.942,
# but R@10 0.958 -> 0.956 and preference 0.800 -> 0.767, for 1.1 points more
# volume. It sharpens the top of the ranking and blunts the tail, which is the
# wrong trade for a memory whose job is not to miss. Off by default.
ANCHOR_NAMES = os.environ.get("CLAIMKEEP_ANCHOR_NAMES", "0") not in (
    "0",
    "false",
    "off",
)
ANCHOR_NAME_LIMIT = 8
_NAME_RE = re.compile(
    r"\b(?:[A-Z][A-Za-z]+(?:-[A-Z0-9][A-Za-z0-9]*)?|[A-Z]{2,}[0-9]*[A-Za-z0-9-]*)\b"
)


class AtomicFactHarvester(Harvester):
    """Keep asserted facts, one per sentence, topicised for supersession."""

    name = "atomic"

    def harvest(self, transcript: Sequence[str], config: Config) -> List[Claim]:
        items: List[Claim] = []
        seen: Set[str] = set()
        # A sentence carrying a calibration marker belongs to that harvester,
        # which also records the stated confidence. Harvesting it twice spends
        # the brief budget on one fact and loses the confidence on the copy.
        marker = re.compile(config.calibration_marker_regex)
        for unit in transcript:
            before = len(items)
            for sentence in split_sentences(str(unit)):
                if marker.search(sentence):
                    continue
                for text in factual_parts(sentence):
                    triple = extract_triple(text)
                    if triple is None:
                        continue
                    subject, predicate, obj = triple
                    key = normalize(text)
                    if key in seen:
                        continue
                    seen.add(key)
                    items.append(
                        Claim(
                            text=text,
                            confidence=None,
                            topic=_topic(subject, predicate, obj),
                            source_harvester=self.name,
                            source_span=None,
                        )
                    )
            if CONTEXT_ANCHOR and (ANCHOR_ALWAYS or len(items) == before):
                anchor = self._anchor(str(unit))
                if anchor and normalize(anchor) not in seen:
                    seen.add(normalize(anchor))
                    items.append(
                        Claim(
                            text=anchor,
                            confidence=None,
                            topic="context|" + (_object_head(anchor) or "turn"),
                            source_harvester=self.name,
                            source_span=None,
                        )
                    )
        return items

    @staticmethod
    def _anchor(unit: str) -> Optional[str]:
        """Opening sentence of a long turn that produced no assertion."""
        if len(unit) < ANCHOR_MIN_CHARS:
            return None
        for sentence in split_sentences(unit):
            text = sentence.strip()
            if len(_tokens(text)) < MIN_TOKENS or _LIST_ITEM.match(text):
                continue
            head = text[:ANCHOR_MAX_CHARS]
            if not ANCHOR_NAMES:
                return head
            names, seen_names = [], set()
            for match in _NAME_RE.finditer(unit):
                token = match.group(0)
                low = token.casefold()
                if low in seen_names or low in head.casefold():
                    continue
                seen_names.add(low)
                names.append(token)
                if len(names) >= ANCHOR_NAME_LIMIT:
                    break
            return head + (" | " + ", ".join(names) if names else "")
        return None
