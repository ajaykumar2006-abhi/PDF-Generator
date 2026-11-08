from __future__ import annotations

from backend.document_store import DocumentStore
from backend.models import Chunk, Document, new_id
from backend.retrieval import assemble_context, lexical_search


def make_chunk(text: str, doc_id: str, page: int = 1, idx: int = 0) -> Chunk:
    return Chunk(
        id=new_id("chunk"),
        document_id=doc_id,
        page_number=page,
        index_in_page=idx,
        text=text,
        heading_hint=None,
        doc_section=None,
        position=page * 1000 + idx,
    )


def test_lexical_search_scores_relevant_chunks_higher(store: DocumentStore):
    doc_id = new_id("doc")
    store.add_document(
        Document(
            id=doc_id,
            title="Doc",
            filename="doc.pdf",
            content_type="application/pdf",
            size_bytes=100,
            page_count=1,
            status="ready",
        )
    )
    chunks = [
        make_chunk("Artificial intelligence is the simulation of human intelligence processes by machines.", doc_id, page=1, idx=0),
        make_chunk("Civil engineering concerns the design and construction of infrastructure.", doc_id, page=2, idx=0),
    ]
    store.add_chunks(chunks)
    results = lexical_search(store, "artificial intelligence", document_ids=[doc_id], top_k=5)
    assert len(results) >= 1
    texts = [r.chunk.text for r in results]
    assert any("artificial intelligence" in t.lower() for t in texts)


def test_lexical_search_respects_document_filter(store: DocumentStore):
    doc_a = new_id("docA")
    doc_b = new_id("docB")
    store.add_document(Document(id=doc_a, title="A", filename="a.pdf", content_type="application/pdf", size_bytes=100, page_count=1, status="ready"))
    store.add_document(Document(id=doc_b, title="B", filename="b.pdf", content_type="application/pdf", size_bytes=100, page_count=1, status="ready"))
    store.add_chunks([
        make_chunk("Quantum computing uses quantum bits.", doc_a, page=1, idx=0),
        make_chunk("Databases store structured data.", doc_b, page=1, idx=0),
    ])
    results = lexical_search(store, "quantum", document_ids=[doc_b], top_k=5)
    assert all(r.source_document_id == doc_b for r in results)


def test_assemble_context_limits_and_deduplicates(store: DocumentStore):
    doc_id = new_id("doc")
    store.add_document(Document(id=doc_id, title="Doc", filename="doc.pdf", content_type="application/pdf", size_bytes=100, page_count=1, status="ready"))
    same_text = "Same chunk text repeated for dedup test. " * 5
    store.add_chunks([
        make_chunk(same_text, doc_id, page=1, idx=0),
        make_chunk(same_text, doc_id, page=2, idx=0),
        make_chunk("Different chunk text for variety and coverage.", doc_id, page=3, idx=0),
    ])
    # assemble_context expects RetrievedChunk list; build from chunks directly
    from backend.retrieval import RetrievedChunk

    def _wrap(chunk):
        return RetrievedChunk(chunk=chunk, score=1.0, source_document_id=chunk.document_id, page_number=chunk.page_number)

    retrieved = store.search_chunks("chunk", document_ids=[doc_id], limit=20)
    wrapped = [_wrap(c) for c in retrieved[:2]]
    context = assemble_context(wrapped, max_chunks=2, deduplicate=True)
    assert len(context) <= 2


def test_store_search_chunks_returns_only_long_enough_chunks(store: DocumentStore):
    doc_id = new_id("doc")
    store.add_document(Document(id=doc_id, title="Doc", filename="doc.pdf", content_type="application/pdf", size_bytes=100, page_count=1, status="ready"))
    store.add_chunks([make_chunk("Short.", doc_id, page=1, idx=0)])
    results = store.search_chunks("Short", document_ids=[doc_id], min_length=10)
    assert len(results) == 0
