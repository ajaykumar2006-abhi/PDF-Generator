from __future__ import annotations

import re
from typing import List, Tuple

from backend.models import Chunk, Page, new_id


def chunk_pages(
    pages: List[Page],
    *,
    max_chunk_tokens: int = 280,
    overlap_tokens: int = 40,
    min_chunk_tokens: int = 60,
) -> List[Chunk]:
    chunks: List[Chunk] = []
    for page in pages:
        if not page.text.strip():
            continue
        page_chunks = _chunk_page(
            page,
            max_tokens=max_chunk_tokens,
            overlap=overlap_tokens,
            min_tokens=min_chunk_tokens,
        )
        for idx, text in enumerate(page_chunks):
            chunks.append(
                Chunk(
                    id=new_id("chunk"),
                    document_id=page.document_id,
                    page_number=page.page_number,
                    index_in_page=idx,
                    text=text,
                    heading_hint=page.heading_hint,
                    doc_section=page.heading_hint,
                    position=(page.page_number * 1000 + idx),
                )
            )
    return chunks


def _chunk_page(
    page: Page,
    *,
    max_tokens: int,
    overlap: int,
    min_tokens: int,
) -> List[str]:
    text = _clean_text(page.text)
    if not text:
        return []
    sentences = _split_sentences(text)
    if not sentences:
        return [text]
    chunks: List[str] = []
    current: List[str] = []
    current_len = 0
    start = 0
    for i, sentence in enumerate(sentences):
        sent_len = _token_count(sentence)
        if current_len + sent_len > max_tokens and current:
            chunk_text = _join_sentences(current)
            if _token_count(chunk_text) >= min_tokens:
                chunks.append(chunk_text)
            # overlap: keep tail of current window
            keep_from = max(0, len(current) - overlap)
            current = current[keep_from:]
            current_len = _token_count(_join_sentences(current))
        current.append(sentence)
        current_len += sent_len
    if current:
        chunk_text = _join_sentences(current)
        if _token_count(chunk_text) >= min_tokens or not chunks:
            chunks.append(chunk_text)
    if not chunks:
        chunks = [text]
    return chunks


def _clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_sentences(text: str) -> List[str]:
    # Keep simple sentence-like splits using punctuation + newlines
    parts: List[str] = []
    for raw in re.split(r"(?<=[\.\!\?])\s+|\n\s*\n", text):
        raw = raw.strip()
        if raw:
            parts.append(raw)
    if not parts and text:
        parts = [text]
    return parts


def _join_sentences(parts: List[str]) -> str:
    return " ".join(p.strip() for p in parts if p.strip())


def _token_count(text: str) -> int:
    # rough whitespace-based token proxy
    return max(1, len(text.split()))
