from __future__ import annotations

from backend.evidence import analyze_evidence, build_citations, _make_excerpt


def test_analyze_evidence_with_no_context():
    evidence = analyze_evidence([], "What is machine learning?")
    assert evidence["status"] == "insufficient_evidence"
    assert evidence["missing"] is True
    assert evidence["passage_count"] == 0


def test_analyze_evidence_with_strong_overlap():
    context = [
        {"text": "Machine learning is a subset of artificial intelligence that enables systems to learn from data without being explicitly programmed.", "document_id": "doc1", "page_number": 1},
        {"text": "Supervised learning uses labeled data to train models that can make predictions on new data.", "document_id": "doc1", "page_number": 2},
    ]
    evidence = analyze_evidence(context, "What is machine learning?")
    assert evidence["passage_count"] == 2
    assert evidence["status"] in {"supported", "partial"}


def test_analyze_evidence_missing_reasons_when_insufficient():
    context = [
        {"text": "Unrelated civil engineering topic about bridges.", "document_id": "doc1", "page_number": 1},
    ]
    evidence = analyze_evidence(context, "Explain quantum entanglement")
    assert evidence["missing"] is True
    assert evidence["missing_reasons"]


def test_build_citations_preserves_page_numbers():
    context = [
        {"text": "First passage on page one.", "document_id": "doc1", "page_number": 1},
        {"text": "Second passage on page two.", "document_id": "doc1", "page_number": 2},
    ]
    evidence = analyze_evidence(context, "What is covered?")
    citations = build_citations(context, evidence)
    pages = [c.page_number for c in citations]
    assert pages == [1, 2]


def test_make_excerpt_truncates_long_text():
    long_text = "word " * 200
    excerpt = _make_excerpt(long_text, length=50)
    assert len(excerpt) <= 50
    assert excerpt.endswith("…")


def test_make_excerpt_keeps_short_text_intact():
    short = "Short passage."
    assert _make_excerpt(short, length=200) == short
