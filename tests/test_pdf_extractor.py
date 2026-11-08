from __future__ import annotations

import io

import pytest

from pypdf import PdfWriter

from backend.pdf_extractor import (
    compute_content_hash,
    extract_pdf,
    validate_pdf,
)


def _make_searchable_pdf(text_by_page: list[str], filename: str = "sample.pdf") -> bytes:
    writer = PdfWriter()
    for text in text_by_page:
        writer.add_blank_page(width=612, height=792)
        # use the PdfWriter page object to set text via annotations is not trivial;
        # instead create an indirect text object using pypdf's low-level interface is heavy.
        # We instead use pypdf's built-in text annotation approach only where intended.
        # For reliable extraction in tests we use a simple text addition via page creator.
        pass
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _make_simple_text_pdf(text_by_page: list[str]) -> bytes:
    from pypdf import PdfWriter
    from reportlab.pdfgen import canvas
    import io as _io

    buf = _io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(612, 792))
    for text in text_by_page:
        c.drawString(72, 720, text[:200])
        c.showPage()
    c.save()
    return buf.getvalue()


def test_compute_content_hash_is_deterministic():
    h1 = compute_content_hash(b"hello")
    h2 = compute_content_hash(b"hello")
    assert h1 == h2
    assert len(h1) == 16


def test_validate_pdf_accepts_valid_header():
    data = b"%PDF-1.4\n" + b"\x00" * 20
    validate_pdf(data, "doc.pdf")


def test_validate_pdf_rejects_non_pdf():
    data = b"not a pdf file content"
    with pytest.raises(Exception):
        validate_pdf(data, "doc.pdf")


def test_extract_pdf_returns_pages_and_warnings():
    pdf_bytes = _make_simple_text_pdf(["First page content here.", "Second page content here."])
    count, pages, warnings = extract_pdf(pdf_bytes, filename="sample.pdf")
    assert count == 2
    assert len(pages) == 2
    assert pages[0].page_number == 1
    assert pages[1].page_number == 2
    assert pages[0].text.strip()
    assert pages[1].text.strip()
    assert pages[0].page_label == "1"


def test_extract_pdf_page_text_preserves_source_content():
    pdf_bytes = _make_simple_text_pdf(["Machine Learning overview.", "Deep learning details."])
    count, pages, _warnings = extract_pdf(pdf_bytes, filename="sample.pdf")
    assert "Machine Learning" in pages[0].text
    assert "Deep learning" in pages[1].text


def test_extract_pdf_empty_document_produces_warnings():
    from pypdf import PdfWriter
    import io as _io

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = _io.BytesIO()
    writer.write(buf)
    pdf_bytes = buf.getvalue()
    count, pages, warnings = extract_pdf(pdf_bytes, filename="blank.pdf")
    assert count == 1
    assert pages[0].text.strip() == ""
    assert any("little or no extractable text" in w for w in warnings)


def test_extract_pdf_multiple_pages_counts_correctly():
    pdf_bytes = _make_simple_text_pdf(["p1", "p2", "p3", "p4"])
    count, pages, _warnings = extract_pdf(pdf_bytes, filename="multi.pdf")
    assert count == 4
    assert len(pages) == 4
    assert pages[-1].page_number == 4


def test_extract_pdf_page_label_is_string():
    pdf_bytes = _make_simple_text_pdf(["hello"])
    count, pages, _warnings = extract_pdf(pdf_bytes, filename="sample.pdf")
    assert isinstance(pages[0].page_label, str)


def test_extract_pdf_discards_images_if_no_embedded_images():
    pdf_bytes = _make_simple_text_pdf(["text page"])
    count, pages, _warnings = extract_pdf(pdf_bytes, filename="sample.pdf")
    assert pages[0].images == []
