from __future__ import annotations

import io
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from backend import pipeline
from backend.diagrams import _local_flowchart_svg
from backend.document_store import DocumentStore
from backend.exceptions import DocumentError


def _make_pdf(pages: list[str]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for text in pages:
        y = 760
        for line in text.split("\n"):
            c.drawString(72, y, line)
            y -= 18
        c.showPage()
    c.save()
    return buf.getvalue()


@pytest.fixture
def store(tmp_path: Path, monkeypatch) -> DocumentStore:
    monkeypatch.setattr(pipeline, "DATA_DIR", tmp_path)
    return DocumentStore(db_path=tmp_path / "store.db")


SAMPLE = [
    "Unit 1 Pipelining\nA pipeline overlaps the execution of instructions.\nThroughput improves with more stages.",
    "Unit 2 Cache memory\nA cache stores recently used data close to the CPU.\nHit ratio measures effectiveness.",
]


def test_list_and_open_document(store):
    result = pipeline.ingest_pdf(store, _make_pdf(SAMPLE), "notes.pdf")
    docs = pipeline.list_documents(store)
    assert [d.id for d in docs] == [result.document.id]

    reopened = pipeline.open_document(store, result.document.id)
    assert reopened.document.id == result.document.id
    assert reopened.document.page_count == 2


def test_open_missing_document_fails(store):
    with pytest.raises(DocumentError):
        pipeline.open_document(store, "doc_missing")


def test_delete_document_removes_files(store):
    result = pipeline.ingest_pdf(store, _make_pdf(SAMPLE), "notes.pdf")
    doc_id = result.document.id
    upload = pipeline.DATA_DIR / "uploads" / f"{doc_id}.pdf"
    assert upload.exists()

    pipeline.delete_document(store, doc_id)
    assert store.get_document(doc_id) is None
    assert not upload.exists()
    assert pipeline.list_documents(store) == []


def test_delete_missing_document_fails(store):
    with pytest.raises(DocumentError):
        pipeline.delete_document(store, "doc_missing")


def test_recent_answers_returns_question_pairs(store):
    doc = pipeline.ingest_pdf(store, _make_pdf(SAMPLE), "notes.pdf").document
    answer = pipeline.ask_question(store, doc.id, "What is a cache?")
    pairs = pipeline.recent_answers(store)
    assert len(pairs) == 1
    assert pairs[0][0].id == answer.id
    assert "cache" in pairs[0][1].text.lower()


def test_export_includes_document_title(store):
    doc = pipeline.ingest_pdf(store, _make_pdf(SAMPLE), "unit2-notes.pdf").document
    answer = pipeline.ask_question(store, doc.id, "What is a cache?")

    md = pipeline.export_to_file(store, answer.id, "md")
    content = md.read_text(encoding="utf-8")
    assert "unit2-notes" in content

    txt = pipeline.export_to_file(store, answer.id, "txt")
    assert "unit2-notes" in txt.read_text(encoding="utf-8")

    pdf = pipeline.export_to_file(store, answer.id, "pdf")
    assert pdf.read_bytes()[:4] == b"%PDF"


def test_local_flowchart_svg_renders_offline():
    svg = _local_flowchart_svg("flowchart TD\n  A[Input] --> B[Process]\n  B --> C[Output]")
    assert svg is not None
    assert svg.startswith("<svg")
    assert "Input" in svg and "Process" in svg and "Output" in svg


def test_local_flowchart_svg_horizontal():
    svg = _local_flowchart_svg("graph LR\n  X --> Y --> Z")
    assert svg is not None
    assert 'width="' in svg


def test_local_flowchart_svg_rejects_non_flowchart():
    assert _local_flowchart_svg("sequenceDiagram\n  A->>B: hi") is None
    svg = _local_flowchart_svg("pie title Pets\n  \"Dogs\" : 50")
    # a pie chart has no parseable nodes/edges -> order empty -> None
    assert svg is None


def test_local_flowchart_svg_edge_labels():
    svg = _local_flowchart_svg("flowchart LR\n  A -->|yes| B")
    assert svg is not None
    assert "yes" in svg
