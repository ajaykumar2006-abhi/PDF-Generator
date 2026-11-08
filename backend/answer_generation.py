from __future__ import annotations

from typing import Any, List

from backend.ai_provider import BaseProvider, build_provider
from backend.evidence import analyze_evidence, build_citations
from backend.retrieval import RetrievedChunk
from backend.models import (
    Answer,
    Citation,
    DiagramAsset,
    FigureAsset,
    Question,
    new_id,
)


def generate_answer(
    question: Question,
    context: List[dict],
    *,
    pages: List[dict] | None = None,
    figures: List[dict] | None = None,
    diagrams: List[DiagramAsset] | None = None,
) -> Answer:
    evidence = analyze_evidence(context, question.text)
    citations = build_citations(context, evidence)

    answer_text = _draft_pdf_answer(question, context, evidence)
    supplementary_text = _draft_supplementary(question, evidence, context)

    provider = build_provider()
    provider_used: str | None = None
    if provider.is_available():
        try:
            drafted = provider.chat(
                _answer_system_prompt(),
                _answer_user_prompt(question, context, evidence, supplementary_text),
            )
            if drafted and drafted.strip():
                answer_text = drafted
                provider_used = provider.name
        except Exception:
            pass

    return Answer(
        id=new_id("answer"),
        question_id=question.id,
        answer_text=answer_text,
        supplementary_text=supplementary_text,
        evidence_analysis=evidence,
        citations=citations,
        diagrams=diagrams or [],
        figures=[FigureAsset(**f) for f in (figures or [])],
        status=evidence["status"] if evidence["status"] in ("supported", "partial", "insufficient_evidence") else "partial",
        provider_used=provider_used,
    )


def _answer_system_prompt() -> str:
    return (
        "You are a careful academic assistant for B.Tech students. "
        "Answer using the supplied PDF passages as the primary source of truth. "
        "Only state a fact as present in the PDF if at least one supplied passage supports it. "
        "Do not invent page numbers, quotations, formulas, or citations. "
        "If the PDF does not contain enough information, say so plainly and do not pretend otherwise. "
        "Separate what the PDF supports from any general knowledge you add. "
        "Prefer clear, exam-style academic language and preserve the terminology used in the supplied passages."
    )


def _answer_user_prompt(
    question: Question,
    context: List[dict],
    evidence: dict[str, Any],
    supplementary: str,
) -> str:
    parts = [
        "QUESTION:\n" + question.text,
        "",
        "SELECTED DOCUMENTS: " + _list_documents(context),
        "EVIDENCE COVERAGE: " + _evidence_summary(evidence),
        "",
        "SUPPLIED PDF PASSAGES:\n" + _context_block(context),
        "",
        "PDF-GROUNDED ANSWER DRAFT:\n" + _safe_preview(),
        "",
        "SUPPLEMENTARY KNOWLEDGE TO USE ONLY IF NEEDED (clearly labeled as external to the PDF):\n" + (supplementary or "(none provided)"),
        "",
        "INSTRUCTIONS:\n"
        "- Write the final PDF-grounded answer in the ANSWER section.\n"
        "- If the PDF does not answer the question, move the supported parts into the answer and state clearly what is missing.\n"
        "- After the ANSWER section, write a separate SUPPLEMENTARY NOTE that clearly labels anything not from the PDF.\n"
        "- Do not add fake citations or page numbers.\n"
    ]
    return "\n".join(parts)


def _list_documents(context: List[dict]) -> str:
    doc_ids = sorted({p["document_id"] for p in context})
    return ", ".join(doc_ids) if doc_ids else "none"


def _evidence_summary(evidence: dict[str, Any]) -> str:
    status = evidence.get("status", "unknown")
    count = evidence.get("passage_count", 0)
    return f"status={status}, passages={count}"


def _context_block(context: List[dict]) -> str:
    lines: List[str] = []
    for p in context:
        lines.append(f"[doc={p['document_id']} page={p['page_number']}]")
        lines.append(p["text"])
        lines.append("")
    return "\n".join(lines)


def _safe_preview() -> str:
    return "(Use the supplied PDF passages above; do not invent content.)"


def _draft_pdf_answer(question: Question, context: List[dict], evidence: dict[str, Any]) -> str:
    status = evidence.get("status", "insufficient_evidence")
    if status == "insufficient_evidence":
        return (
            "The uploaded PDF did not clearly support an answer to this question based on the retrieved passages. "
            "Review the citations below and the suggested follow-up questions. "
            "The AI-enhanced supplementary note, if available, is labeled separately and is not taken from the PDF."
        )
    if status == "partial":
        return (
            "The uploaded PDF provides partial support for this question. "
            "What follows is the portion the PDF supports, with citations. "
            "Missing or unclear parts are listed at the end and, where available, addressed separately in the supplementary note."
        )
    return "The following answer is grounded in the supplied PDF passages. Page citations are listed separately."


def _draft_supplementary(question: Question, evidence: dict[str, Any], context: List[dict]) -> str:
    status = evidence.get("status", "insufficient_evidence")
    if status == "supported":
        return "The PDF supports the main answer. No external supplementation is required; any extra explanation would be optional study context clearly marked as outside the PDF."
    if status == "partial":
        return "The PDF only partially addresses this question. Supplementary explanation, if provided, is added separately and clearly labeled as coming from general model knowledge rather than the PDF."
    if status == "insufficient_evidence":
        return "The PDF did not provide enough evidence. Any further explanation is optional study guidance outside the PDF and should be verified against the course material."
    return ""


def compile_answer_export_metadata(answer: Answer, question: Question) -> dict[str, Any]:
    return {
        "question": question.text,
        "answer": answer.answer_text,
        "supplementary": answer.supplementary_text or "",
        "evidence": answer.evidence_analysis,
        "citations": [c.__dict__ for c in answer.citations],
        "diagrams": [d.__dict__ for d in answer.diagrams],
        "figures": [f.__dict__ for f in answer.figures],
        "provider_used": answer.provider_used,
        "created_at": answer.created_at.isoformat(),
    }
