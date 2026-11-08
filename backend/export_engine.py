from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
    ListFlowable,
    ListItem,
)
from reportlab.platypus.flowables import HRFlowable

from backend.config import ensure_data_dir
from backend.models import Answer, DiagramAsset, FigureAsset, Question
from backend.exceptions import AppError

SUPPORTED_EXPORT_FORMATS = {"pdf", "docx", "md", "txt"}


def build_export_path(*, format: str, answer_id: str) -> Path:
    data_dir = ensure_data_dir()
    out_dir = data_dir / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
    return out_dir / f"answer_{answer_id}_{stamp}.{format}"


def export_answer(
    answer: Answer,
    question: Question,
    *,
    format: str,
    out_path: Path,
    document_title: str | None = None,
) -> Path:
    fmt = (format or "pdf").lower()
    if fmt not in SUPPORTED_EXPORT_FORMATS:
        raise AppError(f"Unsupported export format: {format}")
    if fmt == "pdf":
        _export_pdf(answer, question, out_path, document_title=document_title)
    elif fmt == "docx":
        _export_docx(answer, question, out_path, document_title=document_title)
    elif fmt == "md":
        _export_markdown(answer, question, out_path, document_title=document_title)
    elif fmt == "txt":
        _export_text(answer, question, out_path, document_title=document_title)
    return out_path


def _report_title(document_title: str | None) -> str:
    if document_title:
        return f"BTech Study Intelligence — Answer Report · {document_title}"
    return "BTech Study Intelligence — Answer Report"


# ---------- PDF ----------

def _export_pdf(
    answer: Answer,
    question: Question,
    out_path: Path,
    *,
    document_title: str | None = None,
) -> None:
    data_dir = ensure_data_dir()
    extracted_dir = data_dir / "extracted"
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title2",
        parent=styles["Title"],
        fontSize=18,
        leading=22,
        spaceAfter=10,
        textColor=colors.HexColor("#0b1f3a"),
    )
    h2 = ParagraphStyle(
        "H2",
        parent=styles["Heading2"],
        fontSize=13,
        leading=16,
        spaceBefore=10,
        spaceAfter=4,
        textColor=colors.HexColor("#111827"),
    )
    body = ParagraphStyle(
        "Body2",
        parent=styles["BodyText"],
        fontSize=10,
        leading=14,
        spaceAfter=6,
    )
    small = ParagraphStyle(
        "Small",
        parent=styles["BodyText"],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#6b7280"),
    )

    story: list[Any] = []

    def add(*items: Any) -> None:
        for item in items:
            if isinstance(item, list):
                story.extend(item)
            else:
                story.append(item)

    add(Paragraph(_report_title(document_title), title_style))
    add(Paragraph("Generated " + answer.created_at.strftime("%Y-%m-%d %H:%M UTC"), small))
    add(Spacer(1, 4))
    add(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1")))
    add(Spacer(1, 6))

    add(Paragraph("Question", h2))
    add(Paragraph(_escape(question.text), body))
    add(Spacer(1, 6))

    add(Paragraph("PDF-Grounded Answer", h2))
    add(_paragraphs_from_text(answer.answer_text, body))
    add(Spacer(1, 6))

    if answer.supplementary_text:
        add(Paragraph("AI-Enhanced Supplementary Note", h2))
        add(_paragraphs_from_text(answer.supplementary_text, body))
        add(Spacer(1, 6))

    add(Paragraph("Evidence Coverage", h2))
    add(_paragraphs_from_text(_summary_text(answer.evidence_analysis), body))
    add(Spacer(1, 6))

    if answer.citations:
        add(Paragraph("Source Citations", h2))
        for c in answer.citations:
            add(_citation_block_pdf(c, body, small))
            add(Spacer(1, 4))
        add(Spacer(1, 6))

    # Figures from PDF
    figures = [f for f in answer.figures if f.source_label == "original_pdf_figure"]
    if figures:
        add(Paragraph("Original Figures from PDF", h2))
        for f in figures:
            add(_figure_block_pdf(f, extracted_dir, body, small))
            add(Spacer(1, 4))
        add(Spacer(1, 6))

    # Generated diagrams
    diagrams = [d for d in answer.diagrams if d.rendered_path]
    if diagrams:
        add(Paragraph("Generated Diagrams", h2))
        for d in diagrams:
            add(_diagram_block_pdf(d, body, small))
            add(Spacer(1, 4))

    add(Spacer(1, 8))
    add(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1")))
    add(Paragraph("End of report", small))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        title=_report_title(document_title),
        author="BTech Study Intelligence",
        onFirstPage=_pdf_page_decorator,
        onLaterPages=_pdf_page_decorator,
    )
    doc.build(story)


def _pdf_page_decorator(canvas_obj, doc) -> None:
    """Draw a slim footer with page numbers on every page of the report."""
    canvas_obj.saveState()
    width, _height = A4
    canvas_obj.setFont("Helvetica", 8)
    canvas_obj.setFillColor(colors.HexColor("#6b7280"))
    canvas_obj.drawCentredString(width / 2, 12 * mm, f"Page {doc.page} · BTech Study Intelligence")
    canvas_obj.restoreState()


def _markdown_inline(text: str) -> str:
    """Convert a small markdown subset to ReportLab paragraph markup."""
    text = _escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`([^`]+)`", r'<font face="Courier">\1</font>', text)
    return text


def _paragraphs_from_text(text: str, style: ParagraphStyle) -> list[Any]:
    out: list[Any] = []
    h_styles = _pdf_heading_styles(style)
    for block in re.split(r"\n\s*\n", text.strip()):
        block = block.strip()
        if not block:
            continue
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        table_lines = [ln for ln in lines if ln.startswith("|") and ln.endswith("|") and "|" in ln[1:-1]]
        content_lines = [ln for ln in lines if ln not in table_lines]
        for line in content_lines:
            out.extend(_line_to_flowables(line, style, h_styles))
        for line in table_lines:
            out.append(_markdown_table_to_table(line))
            out.append(Spacer(1, 4))
    return out


def _pdf_heading_styles(base: ParagraphStyle) -> dict[int, ParagraphStyle]:
    return {
        1: ParagraphStyle("MdH1", parent=base, fontSize=14, leading=18, spaceBefore=8, spaceAfter=4,
                          textColor=colors.HexColor("#0b1f3a")),
        2: ParagraphStyle("MdH2", parent=base, fontSize=12, leading=15, spaceBefore=6, spaceAfter=3,
                          textColor=colors.HexColor("#111827")),
        3: ParagraphStyle("MdH3", parent=base, fontSize=11, leading=14, spaceBefore=4, spaceAfter=2,
                          textColor=colors.HexColor("#111827")),
    }


def _line_to_flowables(line: str, body: ParagraphStyle, h_styles: dict[int, ParagraphStyle]) -> list[Any]:
    m = re.match(r"^(#{1,3})\s+(.*)$", line)
    if m:
        level = min(len(m.group(1)), 3)
        return [Paragraph(_markdown_inline(m.group(2)), h_styles[level])]
    m = re.match(r"^[-*•]\s+(.*)$", line)
    if m:
        return [Paragraph("•&nbsp;&nbsp;" + _markdown_inline(m.group(1)), body)]
    m = re.match(r"^\d+[.)]\s+(.*)$", line)
    if m:
        return [Paragraph(_markdown_inline(line), body)]
    return [Paragraph(_markdown_inline(line), body)]


def _markdown_table_to_table(line: str) -> Any:
    cells = [c.strip() for c in line.strip("|").split("|")]
    if len(cells) < 2:
        return Paragraph(_escape(line), getSampleStyleSheet()["BodyText"])
    data = [[Paragraph(_escape(c), getSampleStyleSheet()["BodyText"]) for c in cells]]
    t = Table(data, colWidths=None, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#9ca3af")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return t


def _citation_block_pdf(c: Any, body: ParagraphStyle, small: ParagraphStyle) -> list[Any]:
    header = f"Page {c.page_number} — doc {c.document_id}"
    support = c.support_level or "unlabeled"
    out: list[Any] = []
    out.append(Paragraph(f"<b>{header}</b> <i>(support: {support})</i>", small))
    excerpt = c.excerpt or (c.passage[:320] if c.passage else "")
    excerpt = _escape(excerpt)
    out.append(Paragraph(excerpt, body))
    return out


def _figure_block_pdf(
    f: FigureAsset,
    extracted_dir: Path,
    body: ParagraphStyle,
    small: ParagraphStyle,
) -> list[Any]:
    image_path = Path(f.image_path)
    caption = f.caption or f"Figure from PDF, page {f.page_number}"
    out: list[Any] = []
    out.append(Paragraph(_escape(caption), small))
    if image_path.exists():
        try:
            from PIL import Image

            pil = Image.open(image_path)
            w, h = pil.size
            max_w = 460
            scaled = max_w / w
            if scaled < 1:
                w = int(w * scaled)
                h = int(h * scaled)
            out.append(
                Table(
                    [[__doc_image(str(image_path), w, h)]],
                    colWidths=[w + 8],
                )
            )
        except Exception:
            out.append(Paragraph("Original figure image unavailable", small))
    else:
        out.append(Paragraph("Original figure image not found on disk", small))
    out.append(Spacer(1, 4))
    return out


def _diagram_block_pdf(d: DiagramAsset, body: ParagraphStyle, small: ParagraphStyle) -> list[Any]:
    out: list[Any] = []
    out.append(Paragraph(f"<b>{_escape(d.title)}</b> ({_escape(d.kind)})", small))
    image_path = _diagram_image_path(d)
    if image_path is not None:
        try:
            from PIL import Image

            pil = Image.open(image_path)
            w, h = pil.size
            max_w = 460
            scaled = max_w / w
            if scaled < 1:
                w = int(w * scaled)
                h = int(h * scaled)
            out.append(
                Table(
                    [[__doc_image(str(image_path), w, h)]],
                    colWidths=[w + 8],
                )
            )
        except Exception:
            out.append(Paragraph("Diagram image unavailable", small))
    elif d.rendered_path and Path(d.rendered_path).exists():
        out.append(Paragraph("Diagram rendered as SVG; see the SVG download for the image.", small))
    else:
        out.append(Paragraph("Diagram could not be rendered; source preserved below.", small))
    out.append(Spacer(1, 2))
    source_label = "AI-generated" if d.source == "generated" else d.source
    out.append(Paragraph(f"<i>Source: {_escape(str(source_label))}</i>", small))
    if image_path is None:
        for line in (d.body or d.source or "").splitlines()[:20]:
            out.append(Paragraph(_escape(line) or "&nbsp;", small))
    return out


def _diagram_image_path(d: DiagramAsset) -> Path | None:
    """Return a raster image path suitable for embedding, or None."""
    candidates: list[Path] = []
    labels = d.labels or {}
    if labels.get("png_path"):
        candidates.append(Path(labels["png_path"]))
    if d.rendered_path:
        rendered = Path(d.rendered_path)
        candidates.append(rendered)
        if rendered.suffix.lower() == ".svg":
            candidates.append(rendered.with_suffix(".png"))
    for candidate in candidates:
        if candidate.exists() and candidate.suffix.lower() in {".png", ".jpg", ".jpeg"}:
            return candidate
    for candidate in candidates:
        if candidate.exists() and candidate.suffix.lower() == ".svg":
            try:
                import cairosvg  # optional dependency; may not be installed

                png = candidate.with_suffix(".png")
                cairosvg.svg2png(url=str(candidate), write_to=str(png))
                return png
            except Exception:
                continue
    return None


def __doc_image(path: str, w: int, h: int):
    from reportlab.platypus import Image

    return Image(path, width=w, height=h)


# ---------- DOCX ----------

def _export_docx(
    answer: Answer,
    question: Question,
    out_path: Path,
    *,
    document_title: str | None = None,
) -> None:
    try:
        from docx import Document
        from docx.shared import Pt, RGBColor, Inches
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.enum.table import WD_TABLE_ALIGNMENT
    except Exception as exc:
        raise AppError("python-docx unavailable") from exc

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    doc.add_heading(_report_title(document_title), level=0)
    p = doc.add_paragraph()
    r = p.add_run("Generated " + answer.created_at.isoformat())
    r.italic = True
    r.font.size = Pt(9)
    r.font.color.rgb = RGBColor(0x6b, 0x72, 0x80)

    doc.add_heading("Question", level=1)
    doc.add_paragraph(question.text)

    doc.add_heading("PDF-Grounded Answer", level=1)
    _docx_add_paragraphs(doc, answer.answer_text)

    if answer.supplementary_text:
        doc.add_heading("AI-Enhanced Supplementary Note", level=1)
        _docx_add_paragraphs(doc, answer.supplementary_text)

    doc.add_heading("Evidence Coverage", level=1)
    _docx_add_paragraphs(doc, _summary_text(answer.evidence_analysis))

    if answer.citations:
        doc.add_heading("Source Citations", level=1)
        for c in answer.citations:
            p = doc.add_paragraph()
            r = p.add_run(f"Page {c.page_number} — doc {c.document_id}")
            r.bold = True
            r.font.size = Pt(9)
            r.font.color.rgb = RGBColor(0x37, 0x41, 0x51)
            r2 = p.add_run(f"  (support: {c.support_level or 'unlabeled'})")
            r2.italic = True
            r2.font.size = Pt(9)
            doc.add_paragraph(c.excerpt or c.passage[:500])

    figures = [f for f in answer.figures if f.source_label == "original_pdf_figure"]
    if figures:
        doc.add_heading("Original Figures from PDF", level=1)
        for f in figures:
            image_path = Path(f.image_path)
            caption = f.caption or f"Figure from PDF, page {f.page_number}"
            p = doc.add_paragraph()
            r = p.add_run(caption)
            r.italic = True
            r.font.size = Pt(9)
            if image_path.exists():
                try:
                    doc.add_picture(str(image_path), width=Inches(5.5))
                except Exception:
                    doc.add_paragraph("Original figure image unavailable")
            else:
                doc.add_paragraph("Original figure image not found on disk")
            doc.add_paragraph()

    diagrams = [d for d in answer.diagrams if d.rendered_path]
    if diagrams:
        doc.add_heading("Generated Diagrams", level=1)
        for d in diagrams:
            p = doc.add_paragraph()
            r = p.add_run(f"{d.title} ({d.kind})")
            r.bold = True
            image_path = _diagram_image_path(d)
            if image_path is not None:
                try:
                    doc.add_picture(str(image_path), width=Inches(5.5))
                except Exception:
                    doc.add_paragraph("Diagram image unavailable")
            else:
                doc.add_paragraph("Diagram rendered as SVG or unavailable; see the SVG download.")
                for line in (d.body or d.source or "").splitlines()[:20]:
                    doc.add_paragraph(line, style="Intense Quote")
            p = doc.add_paragraph()
            r = p.add_run(f"Source: {'AI-generated' if d.source == 'generated' else d.source}")
            r.italic = True
            r.font.size = Pt(9)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))


def _docx_add_paragraphs(doc: Any, text: str) -> None:
    for block in re.split(r"\n\s*\n", text.strip()):
        block = block.strip()
        if not block:
            continue
        for line in block.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("|") and line.endswith("|") and "|" in line[1:-1]:
                _docx_add_table(doc, line)
            else:
                doc.add_paragraph(line)


def _docx_add_table(doc: Any, line: str) -> None:
    cells = [c.strip() for c in line.strip("|").split("|")]
    if len(cells) < 2:
        doc.add_paragraph(line)
        return
    table = doc.add_table(rows=1, cols=len(cells))
    table.style = "Light Grid Accent 1"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = table.rows[0].cells
    for i, cell_text in enumerate(cells):
        hdr[i].text = cell_text
        for p in hdr[i].paragraphs:
            for r in p.runs:
                r.bold = True


# ---------- Markdown ----------

def _export_markdown(
    answer: Answer,
    question: Question,
    out_path: Path,
    *,
    document_title: str | None = None,
) -> None:
    data_dir = ensure_data_dir()
    lines: list[str] = []
    lines.append(f"# {_report_title(document_title)}")
    if document_title:
        lines.append("")
        lines.append(f"**Document:** {document_title}")
    lines.append("")
    lines.append(f"Generated: {answer.created_at.isoformat()}")
    lines.append("")
    lines.append("## Question")
    lines.append("")
    lines.append(question.text)
    lines.append("")
    lines.append("## PDF-Grounded Answer")
    lines.append("")
    lines.extend(_markdown_blocks(answer.answer_text))
    lines.append("")
    if answer.supplementary_text:
        lines.append("## AI-Enhanced Supplementary Note")
        lines.append("")
        lines.extend(_markdown_blocks(answer.supplementary_text))
        lines.append("")
    lines.append("## Evidence Coverage")
    lines.append("")
    lines.extend(_markdown_blocks(_summary_text(answer.evidence_analysis)))
    lines.append("")
    if answer.citations:
        lines.append("## Source Citations")
        lines.append("")
        for c in answer.citations:
            support = c.support_level or "unlabeled"
            lines.append(f"- **Page {c.page_number} — doc {c.document_id}** (support: {support})")
            lines.append(f"  {c.excerpt or c.passage[:300]}")
        lines.append("")
    figures = [f for f in answer.figures if f.source_label == "original_pdf_figure"]
    if figures:
        lines.append("## Original Figures from PDF")
        lines.append("")
        for f in figures:
            image_path = Path(f.image_path)
            caption = f.caption or f"Figure from PDF, page {f.page_number}"
            lines.append(f"### {caption}")
            lines.append("")
            if image_path.exists():
                # embed relative path for portability
                rel = image_path.relative_to(data_dir) if image_path.is_relative_to(data_dir) else image_path.name
                lines.append(f"![{caption}]({rel})")
            else:
                lines.append("_Figure image not found on disk._")
            lines.append("")
    diagrams = [d for d in answer.diagrams if d.rendered_path]
    if diagrams:
        lines.append("## Generated Diagrams")
        lines.append("")
        for d in diagrams:
            lines.append(f"### {d.title}")
            lines.append("")
            lines.append(f"**Kind:** {d.kind}  ")
            lines.append(f"**Source:** {'AI-generated' if d.source == 'generated' else d.source}")
            lines.append("")
            rendered = Path(d.rendered_path)
            if rendered.exists():
                rel = rendered.relative_to(data_dir) if rendered.is_relative_to(data_dir) else rendered.name
                if rendered.suffix.lower() == ".svg":
                    lines.append(f"![{d.title}]({rel})")
                else:
                    lines.append(f"![{d.title}]({rel})")
            else:
                lines.append("_Diagram not rendered._")
            lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("_End of report._")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


def _markdown_blocks(text: str) -> list[str]:
    out: list[str] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        block = block.strip()
        if not block:
            continue
        if block.startswith("|") and block.endswith("|") and "|" in block[1:-1]:
            out.append("")
            out.append(block)
            out.append("")
        else:
            out.extend(block.splitlines())
            out.append("")
    return out


# ---------- Text ----------

def _export_text(
    answer: Answer,
    question: Question,
    out_path: Path,
    *,
    document_title: str | None = None,
) -> None:
    lines: list[str] = []
    lines.append(_report_title(document_title))
    if document_title:
        lines.append(f"Document: {document_title}")
    lines.append(f"Generated: {answer.created_at.isoformat()}")
    lines.append("")
    lines.append("Question:")
    lines.append(question.text)
    lines.append("")
    lines.append("PDF-Grounded Answer:")
    lines.append(answer.answer_text)
    lines.append("")
    if answer.supplementary_text:
        lines.append("AI-Enhanced Supplementary Note:")
        lines.append(answer.supplementary_text)
        lines.append("")
    lines.append("Evidence Coverage:")
    lines.append(_summary_text(answer.evidence_analysis))
    lines.append("")
    if answer.citations:
        lines.append("Source Citations:")
        for c in answer.citations:
            lines.append(f"- Page {c.page_number} (doc {c.document_id}, support: {c.support_level or 'unlabeled'}):")
            lines.append(f"  {c.excerpt or c.passage[:300]}")
        lines.append("")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


def _summary_text(evidence: dict[str, Any]) -> str:
    return json.dumps(evidence, ensure_ascii=False, indent=2)


def _escape(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return text
