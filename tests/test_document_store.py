from __future__ import annotations

from backend.document_store import DocumentStore
from backend.models import Document, Page, Question, SavedAnswer, new_id, now


def test_add_and_retrieve_document(store: DocumentStore):
    doc = Document(
        id=new_id("doc"),
        title="Signals and Systems",
        filename="signals.pdf",
        content_type="application/pdf",
        size_bytes=12000,
        page_count=10,
        status="ready",
    )
    store.add_document(doc)
    found = store.get_document(doc.id)
    assert found is not None
    assert found.title == doc.title
    assert found.page_count == 10


def test_update_document_status(store: DocumentStore):
    doc = Document(
        id=new_id("doc"),
        title="Control Systems",
        filename="control.pdf",
        content_type="application/pdf",
        size_bytes=5000,
        page_count=1,
        status="pending",
    )
    store.add_document(doc)
    doc.status = "ready"
    store.update_document(doc)
    found = store.get_document(doc.id)
    assert found.status == "ready"


def test_upsert_pages_and_retrieve(store: DocumentStore):
    doc_id = new_id("doc")
    store.add_document(Document(id=doc_id, title="T", filename="t.pdf", content_type="application/pdf", size_bytes=100, page_count=1, status="ready"))
    pages = [
        Page(document_id=doc_id, page_number=1, page_label="1", text="First page text.", warnings=[], heading_hint="Introduction"),
        Page(document_id=doc_id, page_number=2, page_label="2", text="Second page text.", warnings=["short page"], heading_hint=None),
    ]
    store.upsert_pages(pages)
    found = store.get_pages(doc_id)
    assert len(found) == 2
    assert found[0].page_number == 1
    assert found[1].warnings == ["short page"]


def test_add_and_list_questions(store: DocumentStore):
    q = Question(id=new_id("q"), text="What is a Fourier transform?")
    store.add_question(q)
    listed = store.list_questions(limit=10)
    assert any(x.id == q.id for x in listed)


def test_save_and_retrieve_answer(store: DocumentStore):
    from backend.models import Answer, Citation

    q = Question(id=new_id("q"), text="Question")
    store.add_question(q)
    answer = Answer(
        id=new_id("answer"),
        question_id=q.id,
        answer_text="Answer text",
        supplementary_text="Supp",
        evidence_analysis={"status": "supported"},
        citations=[Citation(passage="p", document_id="doc", page_number=1)],
        diagrams=[],
        figures=[],
        status="supported",
    )
    store.save_answer(answer)
    found = store.get_answer(answer.id)
    assert found is not None
    assert found.answer_text == "Answer text"
    assert found.citations[0].page_number == 1


def test_save_and_list_saved_answers(store: DocumentStore):
    saved = SavedAnswer(
        id=new_id("saved"),
        question="What is osmosis?",
        answer_preview="Osmosis is...",
        document_title="Biology PDF",
    )
    store.add_saved_answer(saved)
    listed = store.list_saved_answers(limit=10)
    assert any(x.id == saved.id for x in listed)
    assert listed[0].answer_preview.startswith("Osmosis")


def test_delete_document_cascades_chunks_and_pages(store: DocumentStore):
    doc_id = new_id("doc")
    store.add_document(Document(id=doc_id, title="D", filename="d.pdf", content_type="application/pdf", size_bytes=100, page_count=1, status="ready"))
    store.upsert_pages([Page(document_id=doc_id, page_number=1, page_label="1", text="txt")])
    from backend.models import Chunk
    store.add_chunks([Chunk(id=new_id("chunk"), document_id=doc_id, page_number=1, index_in_page=0, text="c")])
    deleted = store.delete_document(doc_id)
    assert deleted
    assert store.get_document(doc_id) is None
    assert store.get_pages(doc_id) == []
