"""Framework-independent workflow for the PDF study assistant.

The Streamlit UI calls these functions; they can also be tested directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.answer_generation import generate_answer
from backend.chunking import chunk_pages
from backend.config import DATA_DIR, MAX_UPLOAD_SIZE_BYTES
from backend.diagrams import (
    ALLOWED_KINDS,
    build_diagram_asset,
    render_diagram_asset,
    sanitize_mermaid,
    validate_mermaid,
)
from backend.exceptions import DocumentError, RetrievalError
from backend.export_engine import SUPPORTED_EXPORT_FORMATS, build_export_path, export_answer
from backend.models import Answer, DiagramAsset, Document, Question, new_id
from backend.pdf_extractor import compute_content_hash, extract_pdf, save_page_images, validate_pdf
from backend.retrieval import assemble_context, lexical_search


@dataclass
class IngestResult:
    document: Document
    figures: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_upload(filename: str, data: bytes, content_type: str | None = None) -> None:
    """Raise DocumentError for anything that is not a usable PDF upload."""
    if not filename:
        raise DocumentError("No filename provided")
    if not filename.lower().endswith(".pdf"):
        raise DocumentError("Only .pdf files are accepted")
    if not data:
        raise DocumentError("The uploaded file is empty")
    if len(data) > MAX_UPLOAD_SIZE_BYTES:
        raise DocumentError(f"File exceeds the maximum upload size of {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB")
    if content_type and not content_type.startswith("application/pdf"):
        raise DocumentError("Only PDF files are accepted")
    try:
        validate_pdf(data, filename)
    except Exception as exc:
        raise DocumentError(f"Invalid or corrupted PDF: {exc}") from exc


def ingest_pdf(store, data: bytes, filename: str, content_type: str | None = None) -> IngestResult:
    """Store, extract, chunk and index an uploaded PDF. Failures are recorded on the document."""
    validate_upload(filename, data, content_type)
    doc = Document(
        id=new_id("doc"),
        title=Path(filename).stem or filename,
        filename=filename,
        content_type="application/pdf",
        size_bytes=len(data),
        page_count=0,
        status="processing",
        content_hash=compute_content_hash(data),
    )
    upload_path = DATA_DIR / "uploads" / f"{doc.id}.pdf"
    upload_path.parent.mkdir(parents=True, exist_ok=True)
    upload_path.write_bytes(data)
    store.add_document(doc)

    try:
        page_count, pages, warnings = extract_pdf(data, filename=filename)
        for page in pages:
            page.document_id = doc.id
        store.upsert_pages(pages)
        figures = save_page_images(pages, document_id=doc.id, out_dir=DATA_DIR / "extracted")
        for row in figures:
            row["id"] = new_id("figure")
        store.clear_chunks(doc.id)
        store.add_chunks(chunk_pages(pages))

        doc.page_count = page_count
        doc.warning_messages = warnings
        doc.status = "ready_with_warnings" if warnings else "ready"
        doc.error_message = None
        store.update_document(doc)
        return IngestResult(document=doc, figures=figures, warnings=warnings)
    except Exception as exc:
        doc.status = "error"
        doc.error_message = str(exc)
        store.update_document(doc)
        raise DocumentError(f"Could not extract this PDF: {exc}") from exc


def list_documents(store, limit: int = 50) -> list[Document]:
    """List previously ingested documents, newest first."""
    return store.list_documents(limit=limit)


def open_document(store, document_id: str) -> IngestResult:
    """Reload a previously ingested document so the UI can resume work on it."""
    doc = store.get_document(document_id)
    if not doc:
        raise DocumentError("Document not found", code="not_found", status=404)
    if doc.status == "error":
        raise DocumentError(f"This document failed during processing: {doc.error_message or 'unknown error'}")
    figures = document_figures(document_id)
    warnings = list(doc.warning_messages or [])
    return IngestResult(document=doc, figures=figures, warnings=warnings)


def document_figures(document_id: str) -> list[dict[str, Any]]:
    """Recover the extracted figure records for a document from disk."""
    extracted_dir = DATA_DIR / "extracted"
    figures: list[dict[str, Any]] = []
    if not extracted_dir.is_dir():
        return figures
    for path in sorted(extracted_dir.glob(f"{document_id}_p*_img*.png")):
        stem = path.stem  # {doc_id}_p{NNN}_img{M}
        try:
            page_number = int(stem.split("_p")[1].split("_")[0])
        except (IndexError, ValueError):
            continue
        figures.append(
            {
                "document_id": document_id,
                "page_number": page_number,
                "image_path": str(path),
                "caption": None,
                "source_label": "original_pdf_figure",
            }
        )
    return figures


def delete_document(store, document_id: str) -> None:
    """Remove a document, its pages/chunks, stored PDF and extracted figures."""
    doc = store.get_document(document_id)
    if not doc:
        raise DocumentError("Document not found", code="not_found", status=404)
    store.delete_document(document_id)
    upload = DATA_DIR / "uploads" / f"{document_id}.pdf"
    if upload.exists():
        upload.unlink()
    for fig in document_figures(document_id):
        try:
            Path(fig["image_path"]).unlink(missing_ok=True)
        except OSError:
            pass


def recent_answers(store, limit: int = 20) -> list[tuple[Answer, Question]]:
    """Return (answer, question) pairs, newest first, for the history view."""
    pairs: list[tuple[Answer, Question]] = []
    for answer in store.list_answers(limit=limit):
        question = store.get_question(answer.question_id)
        if question is not None:
            pairs.append((answer, question))
    return pairs


def retrieve_context(store, question_text: str, document_id: str) -> list[dict]:
    try:
        retrieved = lexical_search(store, question_text, document_ids=[document_id], top_k=12)
    except Exception as exc:
        raise RetrievalError(str(exc)) from exc
    return assemble_context(retrieved, max_chunks=10)


def ask_question(store, document_id: str, question_text: str) -> Answer:
    """Create a question for one document and generate its saved answer."""
    if not store.get_document(document_id):
        raise DocumentError("Document not found", code="not_found", status=404)
    question = store.add_question(
        Question(id=new_id("q"), text=question_text, document_id=document_id, selected_document_ids=[document_id])
    )
    context = retrieve_context(store, question_text, document_id)
    answer = generate_answer(question, context)
    return store.save_answer(answer)


def make_diagram(kind: str, title: str, source: str) -> DiagramAsset:
    """Validate Mermaid-style source, then render it to SVG under the data directory."""
    if kind not in ALLOWED_KINDS:
        raise DocumentError(f"Unsupported diagram kind: {kind}")
    cleaned = sanitize_mermaid(source)
    warnings = validate_mermaid(cleaned)
    asset = build_diagram_asset(kind=kind, title=title, source=cleaned or source, body=cleaned or source)
    if warnings:
        asset.labels = {"warnings": warnings}
    return render_diagram_asset(asset, out_dir=DATA_DIR / "generated" / "diagrams")


def export_to_file(store, answer_id: str, fmt: str) -> Path:
    """Write an answer to disk in the requested format and return the file path."""
    fmt = fmt.lower()
    if fmt not in SUPPORTED_EXPORT_FORMATS:
        raise DocumentError(f"Unsupported export format: {fmt}")
    answer = store.get_answer(answer_id)
    if not answer:
        raise DocumentError("Answer not found", code="not_found", status=404)
    question = store.get_question(answer.question_id) or Question(id="", text="")
    document_title = None
    if question.document_id:
        doc = store.get_document(question.document_id)
        document_title = doc.title if doc else None
    out_path = build_export_path(format=fmt, answer_id=answer.id)
    export_answer(answer, question, format=fmt, out_path=out_path, document_title=document_title)
    return out_path
