"""Streamlit interface for the PDF study assistant.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

from backend.ai_provider import provider_status
from backend.config import DATA_DIR
from backend.document_store import DocumentStore
from backend.exceptions import AppError, DocumentError
from backend.models import Document
from backend.pipeline import (
    ask_question,
    delete_document,
    export_to_file,
    ingest_pdf,
    list_documents,
    make_diagram,
    open_document,
    recent_answers,
)

st.set_page_config(page_title="PDF Study Assistant", page_icon="📘", layout="wide")

APP_CSS = """
<style>
    .block-container { padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1100px; }
    [data-testid="stSidebar"] { background: #0f172a; }
    [data-testid="stSidebar"] * { color: #e2e8f0 !important; }
    [data-testid="stSidebar"] .stButton > button {
        background: #334155; border: none; color: #f8fafc !important;
    }
    .psa-header {
        display: flex; align-items: center; gap: 0.75rem;
        border-bottom: 2px solid #e2e8f0; padding-bottom: 0.9rem; margin-bottom: 1.4rem;
    }
    .psa-header h1 { font-size: 1.9rem !important; margin: 0; letter-spacing: -0.02em; }
    .psa-sub { color: #64748b; font-size: 0.95rem; margin-top: 0.15rem; }
    .psa-card {
        background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px;
        padding: 1.1rem 1.25rem; margin-bottom: 0.9rem;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
    }
    .psa-badge {
        display: inline-block; padding: 0.15rem 0.6rem; border-radius: 999px;
        font-size: 0.78rem; font-weight: 600; background: #eef2ff; color: #4338ca;
    }
    .psa-badge.warn { background: #fef3c7; color: #92400e; }
    .psa-muted { color: #64748b; font-size: 0.85rem; }
</style>
"""

PAGES = ["Home", "Upload PDF", "Ask question", "Answers", "Diagrams", "Documents", "Downloads"]
STEP_PAGES = ["Upload PDF", "Ask question", "Answers", "Diagrams", "Downloads"]
DOWNLOADS = [
    ("pdf", "PDF report", "application/pdf"),
    ("docx", "Word document (DOCX)", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ("md", "Markdown (MD)", "text/markdown"),
    ("txt", "Plain text (TXT)", "text/plain"),
]


@st.cache_resource
def get_store() -> DocumentStore:
    return DocumentStore()


@st.cache_data(ttl=60, show_spinner=False)
def _provider_status() -> dict:
    return provider_status()


def _init_state() -> None:
    defaults = {
        "page": "Home",
        "document": None,
        "figures": [],
        "question": "",
        "answer": None,
        "diagram": None,
        "confirm_delete": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _go(page: str) -> None:
    # The sidebar radio owns the "nav" key, so request the change and apply it before the radio renders.
    st.session_state.nav_request = page
    st.rerun()


def _nav_buttons(prev_page: str | None, next_page: str | None) -> None:
    cols = st.columns(2)
    if prev_page and cols[0].button("← Back", key=f"back_{prev_page}_{next_page}"):
        _go(prev_page)
        st.rerun()
    if next_page and cols[1].button("Next →", key=f"next_{prev_page}_{next_page}", type="primary"):
        _go(next_page)
        st.rerun()


def _progress() -> None:
    if st.session_state.page not in STEP_PAGES:
        return
    current = STEP_PAGES.index(st.session_state.page) + 1
    st.progress(current / len(STEP_PAGES), text=f"Step {current} of {len(STEP_PAGES)} — {st.session_state.page}")


def _page_header(title: str, subtitle: str = "") -> None:
    st.markdown(
        f'<div class="psa-header"><div><h1>{title}</h1>'
        + (f'<div class="psa-sub">{subtitle}</div>' if subtitle else "")
        + "</div></div>",
        unsafe_allow_html=True,
    )


def _error_message(exc: Exception) -> str:
    return exc.message if isinstance(exc, AppError) else str(exc)


def _doc_dict(doc: Document) -> dict:
    return {
        "id": doc.id,
        "title": doc.title,
        "filename": doc.filename,
        "page_count": doc.page_count,
        "status": doc.status,
    }


def _select_document(doc_id: str) -> None:
    """Load a stored document into the session so later pages can use it."""
    result = open_document(get_store(), doc_id)
    st.session_state.document = _doc_dict(result.document)
    st.session_state.figures = result.figures
    st.session_state.answer = None
    st.session_state.diagram = None


def _reset_workspace() -> None:
    st.session_state.document = None
    st.session_state.figures = []
    st.session_state.question = ""
    st.session_state.answer = None
    st.session_state.diagram = None
    st.session_state.confirm_delete = None


# ---------------------------------------------------------------- Home


def page_home() -> None:
    _page_header("PDF Study Assistant", "Ask questions of your course PDFs and get cited, exportable answers.")
    st.markdown('<div class="psa-card">', unsafe_allow_html=True)
    st.markdown(
        "**How it works**\n\n"
        "1. **Upload** an academic PDF — text is extracted page by page.\n"
        "2. **Ask** a question — the app searches the whole document.\n"
        "3. **Review** two answers: one grounded in your PDF with page citations, "
        "and a clearly labelled AI explanation.\n"
        "4. **Export** the result as PDF, DOCX, Markdown or plain text."
    )
    st.markdown("</div>", unsafe_allow_html=True)

    status = _provider_status()
    if status.get("available"):
        st.success(f"AI provider configured: {status.get('provider', 'unknown')} ({status.get('model', '')})")
    else:
        st.info(
            "No AI provider is configured, so the AI-generated answer is marked as unavailable. "
            "PDF-grounded answers work without any API key — see `.env.example`."
        )
    if st.button("Start: upload a PDF", type="primary"):
        _go("Upload PDF")
        st.rerun()

    docs = list_documents(get_store(), limit=5)
    if docs:
        st.markdown("**Recent documents**")
        for d in docs:
            st.markdown(f"- {d.title} — {d.page_count} pages")


# ---------------------------------------------------------------- Upload


def page_upload() -> None:
    _page_header("Upload PDF", "PDFs up to 200 MB. Text is extracted with page numbers preserved.")
    _progress()

    if st.session_state.document:
        st.info(f"A document is already loaded: **{st.session_state.document['title']}**. "
                "Upload a new file to replace it.")

    uploaded = st.file_uploader("Choose a PDF", type=["pdf"], key="pdf_uploader")
    if uploaded is not None:
        c1, c2 = st.columns([1, 4])
        c1.metric("Size", f"{len(uploaded.getvalue()) / (1024 * 1024):.1f} MB")
        c2.caption(uploaded.name)

    if uploaded is not None and st.button("Process document", type="primary"):
        with st.spinner("Extracting text, chunking and indexing pages…"):
            try:
                result = ingest_pdf(get_store(), uploaded.getvalue(), uploaded.name, uploaded.type)
            except (DocumentError, AppError) as exc:
                st.error(f"Could not process this file: {_error_message(exc)}")
                return
        st.session_state.document = _doc_dict(result.document)
        st.session_state.figures = result.figures
        st.session_state.answer = None
        st.session_state.diagram = None
        st.success(f"Processed **{result.document.filename}** — {result.document.page_count} pages.")
        for w in result.warnings:
            st.warning(w)

    doc = st.session_state.document
    if doc:
        c1, c2, c3 = st.columns(3)
        c1.metric("Document", doc["title"])
        c2.metric("Pages", doc["page_count"])
        status = doc["status"]
        (c3.success if status.startswith("ready") else c3.error)(status.replace("_", " "))
        if st.session_state.figures:
            st.caption(f"Extracted {len(st.session_state.figures)} original figure(s) from the PDF.")
        _page_preview(doc["id"])

    if st.button("Clear / start over", key="reset_upload"):
        _reset_workspace()
        st.rerun()

    _nav_buttons(prev_page="Home", next_page="Ask question" if doc else None)


def _page_preview(document_id: str) -> None:
    pages = get_store().get_pages(document_id)
    if not pages:
        return
    with st.expander(f"Preview extracted text ({len(pages)} pages)", expanded=False):
        for p in pages[:5]:
            st.markdown(f"**Page {p.page_number}**")
            preview = (p.text or "").strip()
            st.text(preview[:1200] + ("…" if len(preview) > 1200 else "") or "(no text on this page)")
        if len(pages) > 5:
            st.caption(f"Showing first 5 of {len(pages)} pages.")


# ---------------------------------------------------------------- Ask


def page_ask() -> None:
    _page_header("Ask a question", "Search the whole document — answers cite the pages they came from.")
    _progress()
    if not st.session_state.document:
        st.warning("Upload and process a PDF first, or open one from the **Documents** page.")
        _nav_buttons(prev_page="Upload PDF", next_page=None)
        return
    st.caption(f"Document: **{st.session_state.document['title']}**")
    question = st.text_area(
        "Your question",
        value=st.session_state.question,
        height=120,
        placeholder="e.g. Explain the working of a pipelined processor with a diagram.",
    )
    st.session_state.question = question
    if st.button("Get both answers", type="primary"):
        text = question.strip()
        if len(text) < 3:
            st.error("Please enter a question of at least 3 characters.")
        else:
            with st.spinner("Searching the PDF and generating answers…"):
                try:
                    st.session_state.answer = ask_question(
                        get_store(), st.session_state.document["id"], text
                    )
                except AppError as exc:
                    st.error(exc.message)
                    return
            _go("Answers")
            st.rerun()
    _nav_buttons(prev_page="Upload PDF", next_page="Answers" if st.session_state.answer else None)
    _history_picker()


def _history_picker() -> None:
    pairs = recent_answers(get_store(), limit=10)
    if not pairs:
        return
    with st.expander("Previous questions & answers"):
        for answer, question in pairs:
            label = f"{question.text[:90]}{'…' if len(question.text) > 90 else ''}"
            if st.button(label, key=f"hist_{answer.id}"):
                st.session_state.answer = answer
                st.session_state.question = question.text
                _go("Answers")
                st.rerun()


# ---------------------------------------------------------------- Answers


def _citations_md(citations) -> str:
    lines = []
    for c in citations:
        page = getattr(c, "page_number", None) or getattr(c, "page", "?")
        excerpt = getattr(c, "excerpt", "") or getattr(c, "text", "")
        lines.append(f"- **Page {page}**: {excerpt}")
    return "\n".join(lines) if lines else "_No page citations were found for this answer._"


def page_answers() -> None:
    _page_header("Answers", "PDF-grounded answer with citations, plus a separate AI note.")
    _progress()
    answer = st.session_state.answer
    if not answer:
        st.info("Ask a question first, or pick one from **Previous questions & answers** on the Ask page.")
        _nav_buttons(prev_page="Ask question", next_page=None)
        return
    st.caption(f"**Question:** {st.session_state.question}")
    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.subheader("📄 PDF-grounded answer")
            st.caption("Only uses passages retrieved from your uploaded PDF.")
            st.markdown(answer.answer_text or "_The PDF does not contain enough information to answer this._")
            st.markdown("**Page citations**")
            st.markdown(_citations_md(answer.citations))
    with right:
        with st.container(border=True):
            st.subheader("🤖 AI-generated answer")
            st.caption("Not taken from the PDF. Supplementary knowledge is labelled as AI-generated.")
            st.markdown(answer.supplementary_text or f"_Unavailable: {answer.status}_")
    st.caption(f"Answer status: {answer.status} · provider: {answer.provider_used or 'none'}")
    _nav_buttons(prev_page="Ask question", next_page="Diagrams")


# ---------------------------------------------------------------- Diagrams


def page_diagrams() -> None:
    _page_header("Diagrams & flowcharts", "Render Mermaid-style diagrams as SVG.")
    _progress()
    answer = st.session_state.answer
    if answer and answer.diagrams:
        st.subheader("Diagrams from the answer")
        for d in answer.diagrams:
            _show_diagram_asset(d)
    if st.session_state.figures:
        st.subheader("Original PDF figures")
        st.caption("Extracted directly from the uploaded PDF.")
        for fig in st.session_state.figures[:12]:
            st.image(fig["image_path"], caption=f"Page {fig['page_number']} (original PDF figure)", width=360)
    st.subheader("Create your own diagram")
    st.caption("Mermaid-style source; validated before rendering. Works offline for simple flowcharts.")
    kind = st.selectbox("Diagram type", ["flowchart", "sequence", "architecture_block"])
    title = st.text_input("Title", value="Diagram")
    source = st.text_area(
        "Diagram source",
        height=160,
        value="flowchart TD\n  A[Input] --> B[Process]\n  B --> C[Output]",
    )
    if st.button("Render diagram"):
        try:
            st.session_state.diagram = make_diagram(kind, title, source)
        except AppError as exc:
            st.error(exc.message)
    if st.session_state.diagram:
        _show_diagram_asset(st.session_state.diagram)
    _nav_buttons(prev_page="Answers", next_page="Downloads")


def _show_diagram_asset(asset) -> None:
    path = getattr(asset, "rendered_path", None) or (asset.get("rendered_path") if isinstance(asset, dict) else None)
    title = getattr(asset, "title", None) or "Diagram"
    st.markdown(f"**{title}** — AI-generated diagram, not from the PDF.")
    if path and str(path).lower().endswith(".svg"):
        with open(path, encoding="utf-8") as fh:
            st.html(fh.read())
        st.download_button(
            "Download SVG",
            data=open(path, "rb").read(),
            file_name=f"{title}.svg",
            mime="image/svg+xml",
            key=f"svg_{path}",
        )
    elif path and str(path).lower().endswith(".png"):
        st.image(path, caption=title)
        st.download_button(
            "Download PNG",
            data=open(path, "rb").read(),
            file_name=f"{title}.png",
            mime="image/png",
            key=f"png_{path}",
        )
    else:
        st.warning("Diagram could not be rendered; check the source syntax.")


# ---------------------------------------------------------------- Documents


def page_documents() -> None:
    _page_header("Documents", "Manage uploaded PDFs — reopen or remove them.")
    store = get_store()
    docs = list_documents(store)
    if not docs:
        st.info("No documents yet. Upload a PDF from the **Upload PDF** page.")
        _nav_buttons(prev_page="Diagrams", next_page="Downloads")
        return
    current_id = st.session_state.document["id"] if st.session_state.document else None
    for d in docs:
        badge = " <span class='psa-badge'>current</span>" if d.id == current_id else ""
        with st.container(border=True):
            st.markdown(f"**{d.title}**{badge} — {d.page_count} pages · {d.status.replace('_', ' ')}")
            st.caption(f"{d.filename} · uploaded {d.created_at.strftime('%Y-%m-%d %H:%M')}")
            c1, c2, c3 = st.columns([1, 1, 2])
            if c1.button("Open", key=f"open_{d.id}", disabled=d.status == "error"):
                try:
                    _select_document(d.id)
                    st.success(f"Opened **{d.title}**.")
                except AppError as exc:
                    st.error(exc.message)
                st.rerun()
            if c2.button("Delete", key=f"del_{d.id}"):
                st.session_state.confirm_delete = d.id
            if st.session_state.confirm_delete == d.id:
                st.warning(f"Delete **{d.title}** and all its extracted data? This cannot be undone.")
                c4, c5 = st.columns(2)
                if c4.button("Yes, delete", key=f"del_yes_{d.id}", type="primary"):
                    try:
                        delete_document(store, d.id)
                    except AppError as exc:
                        st.error(exc.message)
                    if current_id == d.id:
                        _reset_workspace()
                    st.session_state.confirm_delete = None
                    st.rerun()
                if c5.button("Cancel", key=f"del_no_{d.id}"):
                    st.session_state.confirm_delete = None
                    st.rerun()
    _nav_buttons(prev_page="Diagrams", next_page="Downloads")


# ---------------------------------------------------------------- Downloads


def page_downloads() -> None:
    _page_header("Download center", "Generate reports on demand from the saved answer.")
    _progress()
    answer = st.session_state.answer
    if not answer:
        st.info("Ask a question first, or pick one from **Previous questions & answers** on the Ask page.")
        _nav_buttons(prev_page="Diagrams", next_page=None)
        return
    st.caption(f"**Question:** {st.session_state.question}")
    for fmt, label, mime in DOWNLOADS:
        try:
            path = export_to_file(get_store(), answer.id, fmt)
        except AppError as exc:
            st.error(f"{label}: {exc.message}")
            continue
        st.download_button(label, data=path.read_bytes(), file_name=path.name, mime=mime, key=f"dl_{fmt}")
    _history_exports()
    _nav_buttons(prev_page="Diagrams", next_page=None)


def _history_exports() -> None:
    pairs = recent_answers(get_store(), limit=10)
    if not pairs:
        return
    with st.expander("Export an earlier answer"):
        for answer, question in pairs:
            st.markdown(f"**{question.text[:100]}{'…' if len(question.text) > 100 else ''}**")
            cols = st.columns(4)
            for col, (fmt, label, mime) in zip(cols, DOWNLOADS):
                try:
                    path = export_to_file(get_store(), answer.id, fmt)
                except AppError:
                    continue
                col.download_button(
                    fmt.upper(),
                    data=path.read_bytes(),
                    file_name=path.name,
                    mime=mime,
                    key=f"hist_dl_{answer.id}_{fmt}",
                )
            st.divider()


# ---------------------------------------------------------------- App shell


_init_state()
st.markdown(APP_CSS, unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### 📘 Study Assistant")
    if "nav_request" in st.session_state:
        st.session_state.nav = st.session_state.pop("nav_request")
    st.session_state.page = st.radio("Navigate", PAGES, key="nav", label_visibility="collapsed")
    doc = st.session_state.document
    if doc:
        st.caption(f"Active document: **{doc['title']}** ({doc['page_count']} pages)")
    else:
        st.caption("No document loaded")
    status = _provider_status()
    st.caption("AI provider: " + ("configured" if status.get("available") else "not configured"))
    st.caption(f"Data folder: `{DATA_DIR}`")

ROUTES = {
    "Home": page_home,
    "Upload PDF": page_upload,
    "Ask question": page_ask,
    "Answers": page_answers,
    "Diagrams": page_diagrams,
    "Documents": page_documents,
    "Downloads": page_downloads,
}
ROUTES[st.session_state.page]()
