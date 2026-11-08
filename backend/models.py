from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Document:
    id: str
    title: str
    filename: str
    content_type: str
    size_bytes: int
    page_count: int
    status: str
    branch: str | None = None
    semester: str | None = None
    subject: str | None = None
    unit: str | None = None
    mode: str | None = None
    depth: str | None = None
    created_at: datetime = field(default_factory=now)
    updated_at: datetime = field(default_factory=now)
    content_hash: str | None = None
    error_message: str | None = None
    warning_messages: list[str] = field(default_factory=list)

    def to_store(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "filename": self.filename,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "page_count": self.page_count,
            "status": self.status,
            "branch": self.branch,
            "semester": self.semester,
            "subject": self.subject,
            "unit": self.unit,
            "mode": self.mode,
            "depth": self.depth,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "content_hash": self.content_hash,
            "error_message": self.error_message,
            "warning_messages": self.warning_messages,
        }


@dataclass
class Page:
    document_id: str
    page_number: int
    page_label: str
    text: str
    images: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    heading_hint: str | None = None
    first_line: str | None = None


@dataclass
class Chunk:
    id: str
    document_id: str
    page_number: int
    index_in_page: int
    text: str
    heading_hint: str | None = None
    doc_section: str | None = None
    position: float = 0.0


@dataclass
class Question:
    id: str
    text: str
    document_id: str | None = None
    page_range: str | None = None
    selected_document_ids: list[str] | None = None
    branch: str | None = None
    semester: str | None = None
    subject: str | None = None
    unit: str | None = None
    mode: str | None = None
    depth: str | None = None
    created_at: datetime = field(default_factory=now)
    updated_at: datetime = field(default_factory=now)


@dataclass
class Answer:
    id: str
    question_id: str
    answer_text: str
    supplementary_text: str | None
    evidence_analysis: dict[str, Any]
    citations: list[Citation]
    diagrams: list[DiagramAsset]
    figures: list[FigureAsset]
    status: str
    provider_used: str | None = None
    created_at: datetime = field(default_factory=now)


@dataclass
class Citation:
    passage: str
    document_id: str
    page_number: int
    excerpt: str | None = None
    support_level: str | None = None


@dataclass
class DiagramAsset:
    id: str
    kind: str
    title: str
    source: str
    body: str
    rendered_path: str | None = None
    labels: dict[str, Any] | None = None


@dataclass
class FigureAsset:
    id: str
    document_id: str
    page_number: int
    image_path: str
    caption: str | None = None
    source_label: str = "original_pdf_figure"


@dataclass
class SavedAnswer:
    id: str
    question: str
    answer_preview: str
    document_title: str | None = None
    branch: str | None = None
    semester: str | None = None
    subject: str | None = None
    unit: str | None = None
    created_at: datetime = field(default_factory=now)


@dataclass
class ExportJob:
    id: str
    answer_id: str
    format: str
    status: str
    output_path: str | None = None
    error_message: str | None = None
    created_at: datetime = field(default_factory=now)


def new_id(prefix: str = "") -> str:
    base = uuid4().hex
    if prefix:
        return f"{prefix}_{base}"
    return base
