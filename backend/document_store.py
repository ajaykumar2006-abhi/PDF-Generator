from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.config import ensure_data_dir
from backend.models import (
    Answer,
    Chunk,
    DiagramAsset,
    Document,
    ExportJob,
    FigureAsset,
    Page,
    Question,
    SavedAnswer,
    new_id,
)
from backend.exceptions import DocumentError


class DocumentStore:
    def __init__(self, db_path: Path | None = None):
        data_dir = ensure_data_dir()
        self.db_path = db_path or (data_dir / "store.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connect()
        self._migrate()

    def _connect(self) -> None:
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    @contextmanager
    def transaction(self):
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def _migrate(self) -> None:
        with self.transaction() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    page_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    branch TEXT,
                    semester TEXT,
                    subject TEXT,
                    unit TEXT,
                    mode TEXT,
                    depth TEXT,
                    content_hash TEXT,
                    error_message TEXT,
                    warning_messages TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL,
                    page_number INTEGER NOT NULL,
                    page_label TEXT NOT NULL,
                    text TEXT NOT NULL DEFAULT '',
                    images TEXT DEFAULT '[]',
                    warnings TEXT DEFAULT '[]',
                    heading_hint TEXT,
                    first_line TEXT,
                    UNIQUE(document_id, page_number)
                );

                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    page_number INTEGER NOT NULL,
                    index_in_page INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    heading_hint TEXT,
                    doc_section TEXT,
                    position REAL NOT NULL DEFAULT 0.0
                );

                CREATE TABLE IF NOT EXISTS questions (
                    id TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    document_id TEXT,
                    page_range TEXT,
                    selected_document_ids TEXT DEFAULT '[]',
                    branch TEXT,
                    semester TEXT,
                    subject TEXT,
                    unit TEXT,
                    mode TEXT,
                    depth TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS answers (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL,
                    answer_text TEXT NOT NULL,
                    supplementary_text TEXT,
                    evidence_analysis TEXT NOT NULL DEFAULT '{}',
                    citations TEXT NOT NULL DEFAULT '[]',
                    diagrams TEXT NOT NULL DEFAULT '[]',
                    figures TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'pending',
                    provider_used TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (question_id) REFERENCES questions(id)
                );

                CREATE TABLE IF NOT EXISTS saved_answers (
                    id TEXT PRIMARY KEY,
                    question TEXT NOT NULL,
                    answer_preview TEXT NOT NULL,
                    document_title TEXT,
                    branch TEXT,
                    semester TEXT,
                    subject TEXT,
                    unit TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS export_jobs (
                    id TEXT PRIMARY KEY,
                    answer_id TEXT NOT NULL,
                    format TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    output_path TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (answer_id) REFERENCES answers(id)
                );

                CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(document_id);
                CREATE INDEX IF NOT EXISTS idx_chunks_text ON chunks(text);
                CREATE INDEX IF NOT EXISTS idx_pages_doc ON pages(document_id);
                CREATE INDEX IF NOT EXISTS idx_questions_doc ON questions(document_id);
                """
            )

    # ---------------- Documents ----------------

    def add_document(self, doc: Document) -> Document:
        row = doc.to_store()
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO documents VALUES (
                    :id, :title, :filename, :content_type, :size_bytes,
                    :page_count, :status, :branch, :semester, :subject, :unit,
                    :mode, :depth, :content_hash, :error_message, :warning_messages,
                    :created_at, :updated_at
                )
                """,
                {**row, "warning_messages": _json(row["warning_messages"])},
            )
        return doc

    def update_document(self, doc: Document) -> None:
        row = doc.to_store()
        row["updated_at"] = now_iso()
        with self.transaction() as conn:
            conn.execute(
                """
                UPDATE documents SET
                    title=:title, filename=:filename, content_type=:content_type,
                    size_bytes=:size_bytes, page_count=:page_count, status=:status,
                    branch=:branch, semester=:semester, subject=:subject, unit=:unit,
                    mode=:mode, depth=:depth, content_hash=:content_hash,
                    error_message=:error_message, warning_messages=:warning_messages,
                    updated_at=:updated_at
                WHERE id=:id
                """,
                {**row, "warning_messages": _json(row["warning_messages"])},
            )

    def get_document(self, doc_id: str) -> Document | None:
        with self._conn as conn:
            row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        return _document_from_row(row) if row else None

    def list_documents(self, limit: int = 50, offset: int = 0) -> list[Document]:
        with self._conn as conn:
            rows = conn.execute(
                "SELECT * FROM documents ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [_document_from_row(r) for r in rows]

    def delete_document(self, doc_id: str) -> bool:
        with self.transaction() as conn:
            conn.execute("DELETE FROM chunks WHERE document_id=?", (doc_id,))
            conn.execute("DELETE FROM pages WHERE document_id=?", (doc_id,))
            deleted = conn.execute("DELETE FROM documents WHERE id=?", (doc_id,)).rowcount
        return deleted > 0

    # ---------------- Pages ----------------

    def upsert_pages(self, pages: list[Page]) -> None:
        if not pages:
            return
        with self.transaction() as conn:
            for p in pages:
                conn.execute(
                    """
                    INSERT INTO pages(document_id, page_number, page_label, text, images, warnings, heading_hint, first_line)
                    VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(document_id, page_number) DO UPDATE SET
                        text=excluded.text,
                        images=excluded.images,
                        warnings=excluded.warnings,
                        heading_hint=excluded.heading_hint,
                        first_line=excluded.first_line
                    """,
                    (
                        p.document_id,
                        p.page_number,
                        p.page_label,
                        p.text,
                        _json(p.images),
                        _json(p.warnings),
                        p.heading_hint,
                        p.first_line,
                    ),
                )

    def get_pages(self, document_id: str) -> list[Page]:
        with self._conn as conn:
            rows = conn.execute(
                "SELECT * FROM pages WHERE document_id=? ORDER BY page_number",
                (document_id,),
            ).fetchall()
        return [_page_from_row(r) for r in rows]

    # ---------------- Chunks ----------------

    def clear_chunks(self, document_id: str) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))

    def add_chunks(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        with self.transaction() as conn:
            for c in chunks:
                conn.execute(
                    """
                    INSERT INTO chunks(id, document_id, page_number, index_in_page, text, heading_hint, doc_section, position)
                    VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                        text=excluded.text,
                        heading_hint=excluded.heading_hint,
                        doc_section=excluded.doc_section,
                        position=excluded.position
                    """,
                    (
                        c.id,
                        c.document_id,
                        c.page_number,
                        c.index_in_page,
                        c.text,
                        c.heading_hint,
                        c.doc_section,
                        c.position,
                    ),
                )

    def search_chunks(
        self,
        query: str,
        document_ids: list[str] | None = None,
        limit: int = 20,
        min_length: int = 50,
    ) -> list[Chunk]:
        terms = [t for t in _tokenize(query) if len(t) > 1]
        if not terms:
            return self._filter_chunks(document_ids, limit, min_length)
        with self._conn as conn:
            rows = conn.execute(
                "SELECT * FROM chunks WHERE length(text) >= ?",
                (min_length,),
            ).fetchall()
        candidates = [_chunk_from_row(r) for r in rows]
        scored = []
        for c in candidates:
            if document_ids and c.document_id not in document_ids:
                continue
            score = _bm25_like_score(c.text, terms)
            if score > 0:
                scored.append((score, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:limit]]

    def _filter_chunks(
        self,
        document_ids: list[str] | None,
        limit: int,
        min_length: int,
    ) -> list[Chunk]:
        with self._conn as conn:
            if document_ids:
                rows = conn.execute(
                    "SELECT * FROM chunks WHERE document_id IN ({}) AND length(text) >= ? ORDER BY position DESC LIMIT ?".format(
                        ",".join("?" for _ in document_ids)
                    ),
                    [*document_ids, min_length, limit],
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM chunks WHERE length(text) >= ? ORDER BY position DESC LIMIT ?",
                    (min_length, limit),
                ).fetchall()
        return [_chunk_from_row(r) for r in rows]

    # ---------------- Questions ----------------

    def add_question(self, q: Question) -> Question:
        row = {
            "id": q.id,
            "text": q.text,
            "document_id": q.document_id,
            "page_range": q.page_range,
            "selected_document_ids": _json(q.selected_document_ids or []),
            "branch": q.branch,
            "semester": q.semester,
            "subject": q.subject,
            "unit": q.unit,
            "mode": q.mode,
            "depth": q.depth,
            "created_at": q.created_at.isoformat(),
            "updated_at": q.updated_at.isoformat(),
        }
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO questions(id, text, document_id, page_range, selected_document_ids, branch, semester, subject, unit, mode, depth, created_at, updated_at)
                VALUES (:id, :text, :document_id, :page_range, :selected_document_ids, :branch, :semester, :subject, :unit, :mode, :depth, :created_at, :updated_at)
                """,
                row,
            )
        return q

    def get_question(self, question_id: str) -> Question | None:
        with self._conn as conn:
            row = conn.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
        return _question_from_row(row) if row else None

    def list_questions(self, limit: int = 50, offset: int = 0) -> list[Question]:
        with self._conn as conn:
            rows = conn.execute(
                "SELECT * FROM questions ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [_question_from_row(r) for r in rows]

    # ---------------- Answers ----------------

    def save_answer(self, answer: Answer) -> Answer:
        row = {
            "id": answer.id,
            "question_id": answer.question_id,
            "answer_text": answer.answer_text,
            "supplementary_text": answer.supplementary_text,
            "evidence_analysis": _json(answer.evidence_analysis),
            "citations": _json([c.__dict__ for c in answer.citations]),
            "diagrams": _json([d.__dict__ for d in answer.diagrams]),
            "figures": _json([f.__dict__ for f in answer.figures]),
            "status": answer.status,
            "provider_used": answer.provider_used,
            "created_at": answer.created_at.isoformat(),
        }
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO answers(id, question_id, answer_text, supplementary_text, evidence_analysis, citations, diagrams, figures, status, provider_used, created_at)
                VALUES (:id, :question_id, :answer_text, :supplementary_text, :evidence_analysis, :citations, :diagrams, :figures, :status, :provider_used, :created_at)
                """,
                row,
            )
        return answer

    def get_answer(self, answer_id: str) -> Answer | None:
        with self._conn as conn:
            row = conn.execute("SELECT * FROM answers WHERE id=?", (answer_id,)).fetchone()
        return _answer_from_row(row) if row else None

    def list_answers(self, limit: int = 50, offset: int = 0) -> list[Answer]:
        with self._conn as conn:
            rows = conn.execute(
                "SELECT * FROM answers ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [_answer_from_row(r) for r in rows]

    def answer_exists_for_question(self, question_id: str) -> bool:
        with self._conn as conn:
            row = conn.execute(
                "SELECT 1 FROM answers WHERE question_id=?", (question_id,)
            ).fetchone()
        return row is not None

    # ---------------- Saved answers ----------------

    def add_saved_answer(self, saved: SavedAnswer) -> SavedAnswer:
        row = {
            "id": saved.id,
            "question": saved.question,
            "answer_preview": saved.answer_preview,
            "document_title": saved.document_title,
            "branch": saved.branch,
            "semester": saved.semester,
            "subject": saved.subject,
            "unit": saved.unit,
            "created_at": saved.created_at.isoformat(),
        }
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO saved_answers(id, question, answer_preview, document_title, branch, semester, subject, unit, created_at)
                VALUES (:id, :question, :answer_preview, :document_title, :branch, :semester, :subject, :unit, :created_at)
                """,
                row,
            )
        return saved

    def list_saved_answers(self, limit: int = 50, offset: int = 0) -> list[SavedAnswer]:
        with self._conn as conn:
            rows = conn.execute(
                "SELECT * FROM saved_answers ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [_saved_answer_from_row(r) for r in rows]

    # ---------------- Export jobs ----------------

    def add_export_job(self, job: ExportJob) -> ExportJob:
        row = {
            "id": job.id,
            "answer_id": job.answer_id,
            "format": job.format,
            "status": job.status,
            "output_path": job.output_path,
            "error_message": job.error_message,
            "created_at": job.created_at.isoformat(),
        }
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO export_jobs(id, answer_id, format, status, output_path, error_message, created_at)
                VALUES (:id, :answer_id, :format, :status, :output_path, :error_message, :created_at)
                """,
                row,
            )
        return job

    def get_export_job(self, job_id: str) -> ExportJob | None:
        with self._conn as conn:
            row = conn.execute("SELECT * FROM export_jobs WHERE id=?", (job_id,)).fetchone()
        return _export_job_from_row(row) if row else None

    def list_export_jobs(self, answer_id: str | None = None, limit: int = 50) -> list[ExportJob]:
        with self._conn as conn:
            if answer_id:
                rows = conn.execute(
                    "SELECT * FROM export_jobs WHERE answer_id=? ORDER BY created_at DESC LIMIT ?",
                    (answer_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM export_jobs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [_export_job_from_row(r) for r in rows]


# ---------- tiny helpers ----------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _tokenize(text: str) -> list[str]:
    import re

    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return text.split()


def _bm25_like_score(text: str, terms: list[str]) -> float:
    text_lower = text.lower()
    total = 0.0
    for term in terms:
        count = text_lower.count(term)
        if count:
            total += count / max(1, len(text_lower.split())) * 2.0
    return total


def _document_from_row(row: sqlite3.Row) -> Document:
    return Document(
        id=row["id"],
        title=row["title"],
        filename=row["filename"],
        content_type=row["content_type"],
        size_bytes=row["size_bytes"],
        page_count=row["page_count"],
        status=row["status"],
        branch=row["branch"],
        semester=row["semester"],
        subject=row["subject"],
        unit=row["unit"],
        mode=row["mode"],
        depth=row["depth"],
        created_at=_iso_to_dt(row["created_at"]),
        updated_at=_iso_to_dt(row["updated_at"]),
        content_hash=row["content_hash"],
        error_message=row["error_message"],
        warning_messages=_json_load(row["warning_messages"]),
    )


def _page_from_row(row: sqlite3.Row) -> Page:
    return Page(
        document_id=row["document_id"],
        page_number=row["page_number"],
        page_label=row["page_label"],
        text=row["text"],
        images=_json_load(row["images"]),
        warnings=_json_load(row["warnings"]),
        heading_hint=row["heading_hint"],
        first_line=row["first_line"],
    )


def _chunk_from_row(row: sqlite3.Row) -> Chunk:
    return Chunk(
        id=row["id"],
        document_id=row["document_id"],
        page_number=row["page_number"],
        index_in_page=row["index_in_page"],
        text=row["text"],
        heading_hint=row["heading_hint"],
        doc_section=row["doc_section"],
        position=row["position"],
    )


def _question_from_row(row: sqlite3.Row) -> Question:
    return Question(
        id=row["id"],
        text=row["text"],
        document_id=row["document_id"],
        page_range=row["page_range"],
        selected_document_ids=_json_load(row["selected_document_ids"]),
        branch=row["branch"],
        semester=row["semester"],
        subject=row["subject"],
        unit=row["unit"],
        mode=row["mode"],
        depth=row["depth"],
        created_at=_iso_to_dt(row["created_at"]),
        updated_at=_iso_to_dt(row["updated_at"]),
    )


def _answer_from_row(row: sqlite3.Row) -> Answer:
    from backend.models import Citation, DiagramAsset, FigureAsset

    citations = _json_load(row["citations"])
    diagrams = _json_load(row["diagrams"])
    figures = _json_load(row["figures"])
    return Answer(
        id=row["id"],
        question_id=row["question_id"],
        answer_text=row["answer_text"],
        supplementary_text=row["supplementary_text"],
        evidence_analysis=_json_load(row["evidence_analysis"]),
        citations=[Citation(**c) for c in citations],
        diagrams=[DiagramAsset(**d) for d in diagrams],
        figures=[FigureAsset(**f) for f in figures],
        status=row["status"],
        provider_used=row["provider_used"],
        created_at=_iso_to_dt(row["created_at"]),
    )


def _saved_answer_from_row(row: sqlite3.Row) -> SavedAnswer:
    return SavedAnswer(
        id=row["id"],
        question=row["question"],
        answer_preview=row["answer_preview"],
        document_title=row["document_title"],
        branch=row["branch"],
        semester=row["semester"],
        subject=row["subject"],
        unit=row["unit"],
        created_at=_iso_to_dt(row["created_at"]),
    )


def _export_job_from_row(row: sqlite3.Row) -> ExportJob:
    return ExportJob(
        id=row["id"],
        answer_id=row["answer_id"],
        format=row["format"],
        status=row["status"],
        output_path=row["output_path"],
        error_message=row["error_message"],
        created_at=_iso_to_dt(row["created_at"]),
    )


def _iso_to_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _json_load(value: str) -> Any:
    if not value:
        return []
    try:
        return json.loads(value)
    except Exception:
        return []
