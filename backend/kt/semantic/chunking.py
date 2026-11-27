"""Structure-aware chunking.

Sections never mix (a chunk never spans two headings); tables and code blocks are their own
chunks; long sections are split on paragraph/sentence boundaries with a small overlap.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from kt.domain.models import NormalizedDocument
from kt.semantic.text import estimate_tokens, sentences


@dataclass
class ChunkDraft:
    ordinal: int
    heading_path: list[str]
    kind: str
    content: str
    token_count: int
    content_hash: str = field(init=False)

    def __post_init__(self):
        self.content_hash = "sha256:" + hashlib.sha256(self.content.encode("utf-8")).hexdigest()

    def embedding_text(self, title: str) -> str:
        """Content enriched with title + heading path (improves retrieval of short sections)."""
        header = " > ".join([title, *self.heading_path])
        return f"{header}\n{self.content}"


def _split_long(text: str, target: int, max_tokens: int, overlap_ratio: float) -> list[str]:
    units: list[str] = []
    for para in [p for p in text.split("\n\n") if p.strip()]:
        if estimate_tokens(para) <= max_tokens:
            units.append(para.strip())
        else:
            units.extend(sentences(para))
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for unit in units:
        t = estimate_tokens(unit)
        if current and size + t > target:
            chunks.append("\n\n".join(current))
            # overlap: carry trailing units up to overlap budget
            budget = int(target * overlap_ratio)
            carry: list[str] = []
            for u in reversed(current):
                if sum(estimate_tokens(x) for x in carry) + estimate_tokens(u) > budget:
                    break
                carry.insert(0, u)
            current, size = carry, sum(estimate_tokens(x) for x in carry)
        current.append(unit)
        size += t
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def chunk_document(
    doc: NormalizedDocument, target_tokens: int = 450, max_tokens: int = 700, overlap_ratio: float = 0.12
) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    # Merge consecutive small text sections under the same heading path.
    merged: list[tuple[list[str], str, str]] = []
    for s in doc.sections:
        if merged and merged[-1][0] == s.heading_path and s.kind in ("text", "list") and merged[-1][1] in ("text", "list"):
            path, kind, text = merged[-1]
            merged[-1] = (path, "text", text + "\n\n" + s.text)
        else:
            merged.append((s.heading_path, s.kind, s.text))
    for path, kind, text in merged:
        pieces = [text] if kind in ("table", "code") and estimate_tokens(text) <= max_tokens * 2 else \
            _split_long(text, target_tokens, max_tokens, overlap_ratio)
        for piece in pieces:
            if piece.strip():
                drafts.append(ChunkDraft(len(drafts), list(path), kind, piece.strip(), estimate_tokens(piece)))
    if not drafts and doc.title:
        drafts.append(ChunkDraft(0, [], "text", doc.title, estimate_tokens(doc.title)))
    return drafts
