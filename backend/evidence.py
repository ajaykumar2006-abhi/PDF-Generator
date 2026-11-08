from __future__ import annotations

import re
from typing import Any, List

from backend.models import Citation


def analyze_evidence(
    context: List[dict],
    question: str,
    *,
    min_passages_for_full_support: int = 2,
) -> dict[str, Any]:
    if not context:
        return {
            "status": "insufficient_evidence",
            "passage_count": 0,
            "fully_supported": 0,
            "partially_supported": 0,
            "conflicting": 0,
            "missing": True,
            "missing_reasons": ["No relevant passages retrieved from the uploaded PDF."],
            "suggested_next": "Try broader document selection, a simpler question, or check that the PDF covers the topic.",
        }

    passages = [p["text"] for p in context]
    page_numbers = sorted({p["page_number"] for p in context})
    doc_ids = sorted({p["document_id"] for p in context})

    coverage_state = _classify_coverage(question, passages)

    return {
        "status": coverage_state["status"],
        "passage_count": len(context),
        "page_numbers": page_numbers,
        "document_ids": doc_ids,
        "fully_supported": coverage_state["fully_supported"],
        "partially_supported": coverage_state["partially_supported"],
        "conflicting": 0,
        "conflicting_passages": [],
        "missing": coverage_state["status"] in ("insufficient_evidence", "no_answer"),
        "missing_reasons": coverage_state["missing_reasons"],
        "suggested_next": _suggested_next(coverage_state["status"]),
    }


def build_citations(
    context: List[dict],
    evidence: dict[str, Any],
) -> List[Citation]:
    citations: List[Citation] = []
    for p in context:
        support_level = _citation_support_level(p["text"], evidence)
        excerpt = _make_excerpt(p["text"])
        citations.append(
            Citation(
                passage=p["text"],
                document_id=p["document_id"],
                page_number=p["page_number"],
                excerpt=excerpt,
                support_level=support_level,
            )
        )
    return citations


def _classify_coverage(question: str, passages: List[str]) -> dict[str, Any]:
    q_terms = _content_terms(question)
    if not passages:
        return {
            "status": "insufficient_evidence",
            "fully_supported": 0,
            "partially_supported": 0,
            "missing_reasons": ["No relevant passages retrieved from the uploaded PDF."],
        }

    matched = 0
    partial = 0
    for passage in passages:
        pts = _content_terms(passage)
        overlap = len(q_terms & pts)
        if overlap >= 2:
            matched += 1
        elif overlap == 1:
            partial += 1

    if matched >= 2:
        status = "supported"
        missing_reasons: List[str] = []
    elif matched == 1 or partial >= 1:
        status = "partial"
        missing_reasons = ["Only partial coverage found; answer may be incomplete."]
    else:
        status = "insufficient_evidence"
        missing_reasons = [
            "Retrieved passages do not clearly address the question.",
            "The answer may be missing, phrased differently, or on a nearby page not captured in retrieval.",
        ]

    if status == "insufficient_evidence":
        missing_reasons.append("Consider rephrasing the question or selecting a different document/page range.")

    return {
        "status": status,
        "fully_supported": matched,
        "partially_supported": partial,
        "missing_reasons": missing_reasons,
    }


def _citation_support_level(text: str, evidence: dict[str, Any]) -> str | None:
    status = evidence.get("status", "")
    if status == "supported":
        return "supported"
    if status == "partial":
        return "partial"
    if status == "insufficient_evidence":
        return "weak"
    return "weak"


def _make_excerpt(text: str, length: int = 320) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= length:
        return text
    return text[: length - 1].rstrip() + "…"


def _content_terms(text: str) -> set[str]:
    ignore = {"the", "and", "for", "are", "but", "not", "you", "all", "can", "had", "her", "was", "one", "our", "out", "has", "have", "from", "with", "that", "this", "will", "what", "when", "where", "which", "would", "could", "their", "there", "these", "those", "been", "also", "each", "into", "more", "some", "them", "than", "then", "they"}
    tokens = []
    for t in re.findall(r"[a-z][a-z0-9]+", text.lower()):
        if t not in ignore and len(t) > 2:
            tokens.append(t)
    return set(tokens)


def _suggested_next(status: str) -> str:
    if status == "supported":
        return "Answer is sourced from the uploaded PDF. Check citations and page links."
    if status == "partial":
        return "Review missing sections; the AI-enhanced answer may add context clearly labeled as outside the PDF."
    return "Rephrase the question, choose a different document, or expand the page range."
