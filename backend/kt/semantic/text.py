"""Shared lightweight text utilities (tokenisation, stopwords, sentence split)."""

from __future__ import annotations

import re

STOPWORDS = frozenset(
    """a about above after again against all also am an and any are as at be because been before being below
    between both but by can could did do does doing down during each either else every few for from further had
    has have having he her here hers him his how i if in into is it its itself just may me might more most must
    my no nor not now of off on once only or other our ours out over own per same shall she should so some such
    than that the their theirs them then there these they this those through to too under until up upon us very
    via was we were what when where which while who whom why will with within without would you your yours
    using use used see also new one two etc e g i e eg ie get set via should each must""".split()
)
# Polish stopwords (documentation in this project is often bilingual).
STOPWORDS = STOPWORDS | frozenset(
    "i w z na do nie się jest to że o jak po dla od za przez lub oraz czy jego jej ich tak ale być są".split()
)

_TOKEN = re.compile(r"[A-Za-zÀ-ž0-9][A-Za-zÀ-ž0-9_\-\.]*[A-Za-zÀ-ž0-9]|[A-Za-zÀ-ž0-9]")
_SENT = re.compile(r"(?<!\be\.g)(?<!\bi\.e)(?<=[.!?])\s+|\n{2,}|\n(?=- )|\n(?=\d+\. )|\n(?=\S.*\|)")


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


def content_terms(text: str) -> list[str]:
    return [t for t in tokenize(text) if t not in STOPWORDS and len(t) > 1 and not t.isdigit()]


def stem(token: str) -> str:
    """Very small suffix stripper — good enough to align retry/retries, service/services."""
    for suffix in ("ies", "ing", "ed", "es", "s"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            return token[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return token


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(text) if s and s.strip()]


def estimate_tokens(text: str) -> int:
    return int(len(text.split()) * 1.3) + 1
