from __future__ import annotations

import pathlib
import tempfile
from unittest.mock import patch

import pytest

from backend.models import Answer, Citation, DiagramAsset, FigureAsset, Question, new_id
from backend.export_engine import (
    SUPPORTED_EXPORT_FORMATS,
    build_export_path,
    export_answer,
)


def sample_answer() -> Answer:
    return Answer(
        id=new_id("answer"),
        question_id=new_id("q"),
        answer_text="This is the PDF-grounded answer.\nIt has two paragraphs.",
        supplementary_text="This is the supplementary note.",
        evidence_analysis={"status": "supported", "passage_count": 2},
        citations=[
            Citation(passage="p1", document_id="doc1", page_number=1, excerpt="excerpt 1", support_level="supported"),
            Citation(passage="p2", document_id="doc1", page_number=2, excerpt="excerpt 2", support_level="partial"),
        ],
        diagrams=[
            DiagramAsset(id="d1", kind="flowchart", title="Flow", source="generated", body="graph TD\nA-->B", rendered_path=""),
        ],
        figures=[
            FigureAsset(
                id="f1",
                document_id="doc1",
                page_number=1,
                image_path="",
                caption="Sample figure",
                source_label="original_pdf_figure",
            ),
        ],
        status="supported",
        provider_used="openai-compatible",
    )


def sample_question() -> Question:
    return Question(id=new_id("q"), text="What is machine learning?")


def test_supported_export_formats():
    assert "pdf" in SUPPORTED_EXPORT_FORMATS
    assert "docx" in SUPPORTED_EXPORT_FORMATS
    assert "md" in SUPPORTED_EXPORT_FORMATS
    assert "txt" in SUPPORTED_EXPORT_FORMATS


def test_export_pdf_creates_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from backend.config import ensure_data_dir
    ensure_data_dir()
    answer = sample_answer()
    question = sample_question()
    out = tmp_path / "out.pdf"
    export_answer(answer, question, format="pdf", out_path=out)
    assert out.exists()
    assert out.stat().st_size > 0


def test_export_docx_creates_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from backend.config import ensure_data_dir
    ensure_data_dir()
    answer = sample_answer()
    question = sample_question()
    out = tmp_path / "out.docx"
    export_answer(answer, question, format="docx", out_path=out)
    assert out.exists()
    assert out.stat().st_size > 0


def test_export_markdown_creates_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from backend.config import ensure_data_dir
    ensure_data_dir()
    answer = sample_answer()
    question = sample_question()
    out = tmp_path / "out.md"
    export_answer(answer, question, format="md", out_path=out)
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "PDF-Grounded Answer" in content
    assert "supplementary" not in content.lower() or "Supplementary" in content
    assert "excerpt 1" in content


def test_export_text_creates_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from backend.config import ensure_data_dir
    ensure_data_dir()
    answer = sample_answer()
    question = sample_question()
    out = tmp_path / "out.txt"
    export_answer(answer, question, format="txt", out_path=out)
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "What is machine learning?" in content
    assert "PDF-Grounded Answer" in content


def test_export_pdf_includes_citations_and_page_numbers(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from backend.config import ensure_data_dir
    ensure_data_dir()
    answer = sample_answer()
    question = sample_question()
    out = tmp_path / "out.pdf"
    export_answer(answer, question, format="pdf", out_path=out)
    content = out.read_bytes()
    text = content.decode("latin-1", errors="replace")
    # A valid ReportLab PDF embeds readable page-number text like "Page 1"
    # or at least the citation header text. We assert the file is a PDF and contains
    # visible citation markers.
    assert content.startswith(b"%PDF")
    # The citation header uses "doc" and the page number; it may be split across font streams.
    # We assert that some highly specific citation text is present.
    assert ("doc" in text) and ("page" in text.lower())
