from __future__ import annotations

from dataclasses import dataclass
from typing import List

from backend.document_store import DocumentStore
from backend.models import Chunk


@dataclass
class RetrievedChunk:
    chunk: Chunk
    score: float
    source_document_id: str
    page_number: int


def lexical_search(
    store: DocumentStore,
    query: str,
    *,
    document_ids: List[str] | None = None,
    top_k: int = 12,
    min_chunk_length: int = 60,
) -> List[RetrievedChunk]:
    candidates = store.search_chunks(
        query,
        document_ids=document_ids,
        limit=top_k * 3,
        min_length=min_chunk_length,
    )
    scored: List[RetrievedChunk] = []
    for c in candidates:
        score = _lexical_score(query, c.text)
        scored.append(
            RetrievedChunk(
                chunk=c,
                score=score,
                source_document_id=c.document_id,
                page_number=c.page_number,
            )
        )
    scored.sort(key=lambda x: x.score, reverse=True)
    return scored[:top_k]


def _lexical_score(query: str, text: str) -> float:
    terms = [t for t in query.split() if len(t) > 1]
    if not terms:
        return 0.0
    text_lower = text.lower()
    document_length = max(1, len(text_lower.split()))
    score = 0.0
    for term in terms:
        count = text_lower.count(term.lower())
        if count:
            tf = count / document_length
            idf = 1.0 + (1.0 / (1.0 + document_length / 200.0))
            score += tf * idf
    return float(score)


def assemble_context(
    retrieved: List[RetrievedChunk],
    *,
    max_chunks: int = 10,
    deduplicate: bool = True,
) -> List[dict]:
    selected: List[RetrievedChunk] = []
    seen: set[str] = set()
    for item in retrieved:
        if deduplicate:
            key = item.chunk.text.strip().lower()
            if key in seen:
                continue
            seen.add(key)
        selected.append(item)
        if len(selected) >= max_chunks:
            break
    context = []
    for item in selected:
        context.append(
            {
                "chunk_id": item.chunk.id,
                "document_id": item.source_document_id,
                "page_number": item.page_number,
                "text": item.chunk.text,
                "heading_hint": item.chunk.heading_hint,
                "score": item.score,
            }
        )
    return context
