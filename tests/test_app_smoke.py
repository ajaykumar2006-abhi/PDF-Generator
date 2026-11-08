from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parent.parent / "app.py"

PAGE_HEADINGS = {
    "Upload PDF": "Upload PDF",
    "Ask question": "Ask a question",
    "Answers": "Answers",
    "Diagrams": "Diagrams & flowcharts",
    "Documents": "Documents",
    "Downloads": "Download center",
}


def _new_app() -> AppTest:
    return AppTest.from_file(str(APP), default_timeout=30).run()


def _page_texts(at: AppTest) -> str:
    parts = [t.value for t in at.markdown] + [h.value for h in at.header]
    return "\n".join(parts)


def test_home_page_renders_without_exceptions():
    at = _new_app()
    assert not at.exception
    assert "PDF Study Assistant" in _page_texts(at)


def test_sidebar_navigation_switches_every_page():
    at = _new_app()
    for label, heading in PAGE_HEADINGS.items():
        at.sidebar.radio[0].set_value(label).run()
        assert not at.exception, label
        assert heading in _page_texts(at), label


def test_ask_page_without_document_shows_guidance():
    at = _new_app()
    at.sidebar.radio[0].set_value("Ask question").run()
    assert not at.exception
    assert any("Upload and process a PDF first" in w.value for w in at.warning)


def test_documents_page_renders():
    at = _new_app()
    at.sidebar.radio[0].set_value("Documents").run()
    assert not at.exception
    assert "Documents" in _page_texts(at)
