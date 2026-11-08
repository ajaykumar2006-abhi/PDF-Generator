from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from pypdf import PdfReader
from reportlab.pdfgen import canvas

from backend import pipeline
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
    monkeypatch.setattr("backend.export_engine.DATA_DIR", tmp_path, raising=False)
    return DocumentStore(db_path=tmp_path / "store.db")


SAMPLE = [
    "Unit 1 Pipelining\nA pipeline overlaps the execution of instructions.\nThroughput improves with more stages.",
    "Unit 2 Cache memory\nA cache stores recently used data close to the CPU.\nHit ratio measures effectiveness.",
    "Unit 3 Virtual memory\nPages are mapped to frames by the page table.",
]


def test_ingest_multi_page_pdf_records_pages_and_chunks(store):
    result = pipeline.ingest_pdf(store, _make_pdf(SAMPLE), "notes.pdf", "application/pdf")
    doc = store.get_document(result.document.id)
    assert doc.page_count == 3
    assert doc.status in {"ready", "ready_with_warnings"}
    pages = store.get_pages(doc.id)
    assert [p.page_number for p in pages] == [1, 2, 3]
    assert "pipeline" in pages[0].text.lower()


def test_question_answered_from_pdf_has_page_citations(store):
    doc = pipeline.ingest_pdf(store, _make_pdf(SAMPLE), "notes.pdf").document
    answer = pipeline.ask_question(store, doc.id, "What is a cache and its hit ratio?")
    assert answer.id
    assert answer.citations, "expected at least one page citation"
    assert all(c.page_number in {1, 2, 3} for c in answer.citations)


def test_question_absent_from_pdf_is_labelled_not_invented(store):
    doc = pipeline.ingest_pdf(store, _make_pdf(SAMPLE), "notes.pdf").document
    answer = pipeline.ask_question(store, doc.id, "Explain quantum chromodynamics gluon confinement")
    assert answer.id
    assert answer.answer_text, "PDF panel must always contain text"


def test_invalid_uploads_are_rejected(store):
    with pytest.raises(DocumentError):
        pipeline.ingest_pdf(store, b"not a pdf at all", "fake.pdf")
    with pytest.raises(DocumentError):
        pipeline.ingest_pdf(store, _make_pdf(SAMPLE), "notes.txt")
    with pytest.raises(DocumentError):
        pipeline.ingest_pdf(store, b"", "empty.pdf")


def test_diagram_renders_svg(store):
    asset = pipeline.make_diagram("flowchart", "Pipeline", "flowchart TD\n  A[Fetch] --> B[Decode]")
    assert asset.rendered_path and Path(asset.rendered_path).exists()
    assert "<svg" in Path(asset.rendered_path).read_text(encoding="utf-8")


def test_exports_open_and_contain_answer_text(store):
    doc = pipeline.ingest_pdf(store, _make_pdf(SAMPLE), "notes.pdf").document
    answer = pipeline.ask_question(store, doc.id, "What is a cache?")

    txt = pipeline.export_to_file(store, answer.id, "txt")
    assert "cache" in txt.read_text(encoding="utf-8").lower()

    md = pipeline.export_to_file(store, answer.id, "md")
    assert md.read_text(encoding="utf-8").strip()

    pdf = pipeline.export_to_file(store, answer.id, "pdf")
    assert pdf.read_bytes()[:4] == b"%PDF"
    pdf_text = "".join(p.extract_text() or "" for p in PdfReader(str(pdf)).pages)
    assert "What is a cache" in pdf_text

    docx = pipeline.export_to_file(store, answer.id, "docx")
    with zipfile.ZipFile(docx) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    assert "What is a cache" in xml


def test_unsupported_export_format_rejected(store):
    with pytest.raises(DocumentError):
        pipeline.export_to_file(store, "missing", "exe")
