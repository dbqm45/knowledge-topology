"""Rule-based entity extraction + conservative entity resolution.

Detection finds surface forms (systems, processes, identifiers, acronyms, concepts). Resolution
only auto-merges forms with the same *normalised key*; forms that merely share a *core key*
("Payment API" vs "Payment Service") become ``candidate`` alias pairs for human review —
the engine never silently fuses two possibly different systems. An LLM extractor can be plugged
in behind the same :func:`extract_mentions` contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from kt.semantic.text import STOPWORDS, stem

_ID = re.compile(r"\b[A-Z][A-Z0-9]{1,}(?:[-_][A-Z0-9]+){1,}\b")
_ACRONYM = re.compile(r"\b[A-Z]{2,6}[0-9]?\b")
_TITLE_SEQ = re.compile(r"\b(?:[A-Z][a-zA-Z0-9]+|[A-Z]{2,6})(?:[ \-](?:[A-Z][a-zA-Z0-9]+|[A-Z]{2,6})){1,3}\b")
_LOWER_TERMS = re.compile(r"\b([a-z]+(?:[ \-][a-z]+)?) (service|gateway|api|queue|database|policy|process|pipeline|"
                          r"workflow|procedure|runbook|platform)\b")

SYSTEM_SUFFIXES = ("service", "api", "gateway", "queue", "database", "db", "platform", "backend", "cluster", "bus")
PROCESS_SUFFIXES = ("process", "procedure", "flow", "workflow", "policy", "runbook", "pipeline", "reconciliation")
TEAM_SUFFIXES = ("team", "squad", "guild", "department")
GENERIC_ACRONYMS = {"API", "URL", "HTTP", "HTTPS", "JSON", "TODO", "FAQ", "OK", "ID", "UI", "PDF", "NOTE", "TBD",
                    "IT", "AND", "OR", "THE", "FOR", "NOT", "SLA", "ETA", "PR", "CSV", "XML", "YAML"}
SENTENCE_START_STOP = {"The", "This", "That", "These", "Those", "When", "If", "All", "Each", "Our", "We", "It", "An",
                       "A", "In", "On", "For", "To", "See", "Use", "Note", "After", "Before", "Then", "Also",
                       "Every", "Only", "Both", "Do", "Does", "Is", "Are", "With", "From", "By", "As", "At"}
CORE_DROP = {"service", "api", "backend", "system", "platform", "module", "component", "app", "application"}


@dataclass(frozen=True)
class Mention:
    surface: str
    normalized_key: str
    core_key: str
    entity_type: str


def normalize_key(surface: str) -> str:
    words = re.split(r"[\s\-_]+", surface.lower())
    return " ".join(stem(w) for w in words if w)


def core_key(surface: str) -> str:
    words = [w for w in normalize_key(surface).split() if w not in CORE_DROP]
    return " ".join(words) or normalize_key(surface)


def classify(surface: str) -> str:
    low = surface.lower()
    if _ID.fullmatch(surface):
        return "identifier"
    last = low.split()[-1] if low.split() else low
    if last in SYSTEM_SUFFIXES or low.endswith(SYSTEM_SUFFIXES):
        return "system"
    if last in PROCESS_SUFFIXES:
        return "process"
    if last in TEAM_SUFFIXES:
        return "team"
    if surface.isupper():
        return "acronym"
    return "concept"


def _mk(surface: str) -> Mention | None:
    surface = surface.strip(" -_.")
    if len(surface) < 2:
        return None
    words = surface.split()
    while words and words[0] in SENTENCE_START_STOP:
        words = words[1:]
    if not words:
        return None
    surface = " ".join(words)
    if len(words) == 1 and surface.upper() in GENERIC_ACRONYMS:
        return None
    if all(w.lower() in STOPWORDS for w in words):
        return None
    if len(words) == 1 and not surface.isupper() and not _ID.fullmatch(surface):
        return None  # single capitalised words are too noisy (sentence starts)
    return Mention(surface, normalize_key(surface), core_key(surface), classify(surface))


def extract_mentions(text: str) -> list[Mention]:
    found: dict[str, Mention] = {}
    spans: list[tuple[int, int]] = []

    def add(m: re.Match, surface: str | None = None):
        mention = _mk(surface or m.group(0))
        if mention and mention.normalized_key not in found:
            found[mention.normalized_key] = mention
        spans.append(m.span())

    for m in _ID.finditer(text):
        add(m)
    for m in _TITLE_SEQ.finditer(text):
        if not any(a <= m.start() < b for a, b in spans):
            add(m)
    for m in _ACRONYM.finditer(text):
        if not any(a <= m.start() < b for a, b in spans):
            add(m)
    for m in _LOWER_TERMS.finditer(text):
        add(m, f"{m.group(1)} {m.group(2)}".title())
    return list(found.values())


# ---------------------------------------------------------------------------------------------------------------
# Claims — numeric assertions used for consistency analysis ("retried up to 3 times" vs "5 attempts").
# ---------------------------------------------------------------------------------------------------------------

WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "sixty": 60, "hundred": 100}
UNIT_CANON = {
    "times": "count", "time": "count", "attempts": "count", "attempt": "count", "retries": "count",
    "retry": "count", "tries": "count",
    "ms": "ms", "millisecond": "ms", "milliseconds": "ms",
    "s": "s", "sec": "s", "secs": "s", "second": "s", "seconds": "s",
    "min": "min", "mins": "min", "minute": "min", "minutes": "min",
    "h": "h", "hour": "h", "hours": "h", "day": "d", "days": "d", "week": "w", "weeks": "w",
    "%": "%", "percent": "%", "mb": "mb", "gb": "gb", "kb": "kb",
    "requests": "requests", "rps": "rps", "users": "users", "nodes": "nodes", "replicas": "replicas",
    "characters": "chars", "chars": "chars", "versions": "versions", "eur": "eur", "usd": "usd", "pln": "pln",
}
_NUM_UNIT = re.compile(
    r"\b(\d+(?:[.,]\d+)?|" + "|".join(WORD_NUMBERS) + r")\s*(" + "|".join(sorted(map(re.escape, UNIT_CANON),
                                                                                key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Claim:
    key_terms: frozenset[str]
    value: float
    unit: str
    sentence: str


def extract_claims(text: str) -> list[Claim]:
    from kt.semantic.text import content_terms, sentences

    claims: list[Claim] = []
    for sent in sentences(text):
        for m in _NUM_UNIT.finditer(sent):
            raw, unit = m.group(1).lower(), m.group(2).lower()
            value = float(WORD_NUMBERS.get(raw, raw.replace(",", "."))) if raw in WORD_NUMBERS or raw[0].isdigit() \
                else None
            if value is None:
                continue
            terms = frozenset(stem(t) for t in content_terms(sent) if not any(ch.isdigit() for ch in t)
                              and t not in UNIT_CANON and t not in WORD_NUMBERS)
            if len(terms) >= 2:
                claims.append(Claim(terms, value, UNIT_CANON[unit], sent.strip()[:400]))
    return claims


def claims_conflict(a: Claim, b: Claim, min_jaccard: float = 0.34, min_shared: int = 3) -> bool:
    if a.unit != b.unit or a.value == b.value:
        return False
    shared = len(a.key_terms & b.key_terms)
    jaccard = shared / max(1, len(a.key_terms | b.key_terms))
    return shared >= min_shared and jaccard >= min_jaccard
