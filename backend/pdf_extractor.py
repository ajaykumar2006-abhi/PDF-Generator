from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from backend.exceptions import ExtractionWarning
from backend.models import Page


def compute_content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def validate_pdf(data: bytes, filename: str) -> None:
    if len(data) < 8:
        raise PdfReadError("File too small to be a valid PDF")
    head = data[:8]
    if not head.startswith(b"%PDF"):
        raise PdfReadError("File does not start with a PDF header")


def extract_pdf(
    data: bytes,
    *,
    filename: str = "document.pdf",
    max_pages: int | None = None,
) -> tuple[int, list[Page], list[str]]:
    """Extract page-by-page text and embedded images.

    Returns (page_count, pages, warnings).
    """
    warnings: list[str] = []
    pages: list[Page] = []

    try:
        stream = BytesIO(data)
        reader = PdfReader(stream)
    except PdfReadError as exc:
        raise PdfReadError(f"PDF parse error: {exc}") from exc

    total_pages = len(reader.pages)
    limit = max_pages if max_pages else total_pages

    for index in range(limit):
        page_number = index + 1
        try:
            page = reader.pages[index]
        except Exception as exc:
            warnings.append(f"Page {page_number}: could not read page object ({exc})")
            pages.append(
                Page(
                    document_id="",
                    page_number=page_number,
                    page_label=str(page_number),
                    text="",
                    warnings=[f"Page {page_number}: unreadable page object"],
                )
            )
            continue

        text = _safe_extract_text(page)

        # Heuristic heading hint from first non-empty line
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        heading_hint = lines[0] if lines else None
        first_line = lines[0] if lines else None

        images = _extract_images(page, page_number=page_number)

        page_warnings: list[str] = []
        if not text or len(text.strip()) < 5:
            page_warnings.append(f"Page {page_number}: little or no extractable text")
            warnings.append(f"Page {page_number}: little or no extractable text")
        if len(images) > 0 and not text.strip():
            page_warnings.append(f"Page {page_number}: appears image-only")
            warnings.append(f"Page {page_number}: appears image-only")

        pages.append(
            Page(
                document_id="",
                page_number=page_number,
                page_label=str(page_number),
                text=text,
                images=images,
                warnings=page_warnings,
                heading_hint=heading_hint,
                first_line=first_line,
            )
        )

    if total_pages > limit:
        warnings.append(f"Document has {total_pages} pages; only first {limit} processed")

    return limit, pages, warnings


def _safe_extract_text(page: Any) -> str:
    try:
        text = page.extract_text()
    except Exception:
        text = ""
    if text is None:
        text = ""
    return text


def _extract_images(page: Any, *, page_number: int) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = []
    try:
        resources = page.get("/Resources", None)
        if resources is None:
            return images
        xobj = resources.get("/XObject", None)
        if xobj is None:
            return images
        for name, obj in xobj.items():
            try:
                subtype = obj.get("/Subtype")
                if subtype != "/Image":
                    continue
                mode_map = {
                    "/RGB": "RGB",
                    "/RGBA": "RGBA",
                    "/Gray": "L",
                    "/CMYK": "CMYK",
                }
                color_space = obj.get("/ColorSpace")
                mode = mode_map.get(color_space, "RGB")
                width = int(obj.get("/Width", 0))
                height = int(obj.get("/Height", 0))
                if width <= 0 or height <= 0:
                    continue
                data = obj.get_data()
                if not data:
                    continue
                try:
                    from PIL import Image

                    img = Image.open(BytesIO(data))
                    img = img.convert("RGB")
                except Exception:
                    continue
                images.append(
                    {
                        "name": str(name),
                        "width": width,
                        "height": height,
                        "mode": mode,
                        "bytes": data,
                        "page_number": page_number,
                    }
                )
            except Exception:
                continue
    except Exception:
        pass
    return images


def save_page_images(
    pages: list[Page],
    *,
    document_id: str,
    out_dir: Path,
) -> list[dict[str, Any]]:
    saved: list[dict[str, Any]] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    for page in pages:
        for idx, img in enumerate(page.images):
            try:
                from PIL import Image

                pil = Image.open(BytesIO(img["bytes"])).convert("RGB")
            except Exception:
                continue
            name = f"{document_id}_p{page.page_number:03d}_img{idx}.png"
            path = out_dir / name
            pil.save(path)
            saved.append(
                {
                    "document_id": document_id,
                    "page_number": page.page_number,
                    "image_path": str(path),
                    "width": pil.width,
                    "height": pil.height,
                    "caption": None,
                    "source_label": "original_pdf_figure",
                }
            )
    return saved
