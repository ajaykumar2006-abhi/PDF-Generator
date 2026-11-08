from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from backend.models import DiagramAsset, new_id

# Allowed diagram kinds for this build
ALLOWED_KINDS = {
    "flowchart",
    "sequence",
    "architecture_block",
    "concept_map",
    "state",
    "decision_tree",
    "comparison_table_as_diagram",
}

# Very minimal external-resource stripping for safety
_DANGEROUS_RE = re.compile(
    r'link\s+|!include\s+|class\s*\{[^}]*\}'  # block raw external links/includes
)


def sanitize_mermaid(source: str) -> str:
    source = _DANGEROUS_RE.sub("", source)
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    return source.strip()


def validate_mermaid(source: str) -> list[str]:
    warnings: list[str] = []
    if not source.strip():
        warnings.append("Diagram source is empty")
        return warnings
    low = source.lower()
    if low.startswith("graph") or low.startswith("flowchart") or low.startswith("sequenceDiagram") or low.startswith("stateDiagram") or low.startswith(("classDiagram", "erDiagram", "gitgraph")):
        pass
    else:
        # Accept custom text around a mermaid-like block only if it has recognizable diagram syntax
        if not any(k in low for k in ("-->", "->>", "::", "|", "==", "==>", "rect", "circle", "diamond")):
            warnings.append("Diagram may not be valid Mermaid syntax")
    if len(source) > 4000:
        warnings.append("Diagram source is unusually long")
    return warnings


def render_mermaid_to_svg(
    source: str,
    *,
    out_path: Path,
    output_kind: str = "svg",
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    safe = sanitize_mermaid(source)
    warnings = validate_mermaid(safe)
    encoded = _encode_mermaid(safe)
    svg_text = _fetch_mermaid_svg(encoded)
    if not svg_text:
        svg_text = _local_flowchart_svg(safe)
    if svg_text:
        out_path.write_text(svg_text, encoding="utf-8")
        return out_path
    # Fallback placeholder SVG
    placeholder = _mermaid_placeholder_svg(source=safe, warnings=warnings)
    out_path.write_text(placeholder, encoding="utf-8")
    return out_path


def render_mermaid_to_png(
    source: str,
    *,
    out_path: Path,
) -> Path:
    svg_path = out_path.with_suffix(".svg")
    render_mermaid_to_svg(source, out_path=svg_path)
    _svg_to_png(svg_path, out_path)
    return out_path


def fetch_diagram_png(source: str) -> bytes | None:
    """Fetch a PNG render of the diagram from mermaid.ink (requires network)."""
    encoded = _encode_mermaid(sanitize_mermaid(source))
    try:
        import httpx

        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            resp = client.get(f"https://mermaid.ink/png/{encoded}")
        if resp.status_code == 200 and resp.content[:4] == b"\x89PNG":
            return resp.content
    except Exception:
        return None
    return None


def _encode_mermaid(source: str) -> str:
    import base64

    payload = f"graph TD\n{source}" if not source.strip().lower().startswith(("graph", "flowchart", "sequenceDiagram", "stateDiagram", "classDiagram")) else source
    # Keep only ASCII-safe base64
    encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    return encoded


def _fetch_mermaid_svg(encoded: str) -> str | None:
    import httpx

    url = f"https://mermaid.ink/svg/{encoded}"
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            resp = client.get(url)
        if resp.status_code == 200 and "<svg" in resp.text:
            return resp.text
    except Exception:
        return None
    return None


def _svg_to_png(svg_path: Path, png_path: Path) -> None:
    try:
        from PIL import Image
        import cairosvg

        cairosvg.svg2png(url=str(svg_path), write_to=str(png_path))
    except Exception:
        # Pillow cannot rasterize SVG by itself; keep SVG if PNG fails
        png_path.write_bytes(svg_path.read_bytes())
        png_path.with_suffix(".svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 60">'
            '<text x="10" y="30" font-family="sans-serif" font-size="14">Diagram rendering unavailable; SVG provided instead.</text>'
            "</svg>"
        )


def _mermaid_placeholder_svg(*, source: str, warnings: list[str]) -> str:
    text = "Diagram rendering unavailable"
    if warnings:
        text = warnings[0]
    wrapped = _wrap_svg_text(text, max_chars=60)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="120" viewBox="0 0 600 120">'
        '<rect width="600" height="120" fill="#f7f8fa" stroke="#d0d5dd" stroke-width="1"/>'
        f'<text x="20" y="40" font-family="sans-serif" font-size="14" fill="#1f2937">{wrapped[0]}</text>'
        f'<text x="20" y="65" font-family="sans-serif" font-size="12" fill="#6b7280">{wrapped[1]}</text>'
        f'<text x="20" y="90" font-family="monospace" font-size="10" fill="#9ca3af">Source: {source[:120]}</text>'
        "</svg>"
    )


def _wrap_svg_text(text: str, max_chars: int = 60) -> list[str]:
    import textwrap

    lines = textwrap.wrap(text, width=max_chars) or [text]
    if len(lines) == 1:
        return [lines[0], ""]
    return [lines[0], lines[1]]


def build_diagram_asset(
    kind: str,
    title: str,
    source: str,
    body: str,
    *,
    rendered_path: str | None = None,
    labels: dict[str, Any] | None = None,
) -> DiagramAsset:
    return DiagramAsset(
        id=new_id("diagram"),
        kind=kind,
        title=title,
        source=source,
        body=body,
        rendered_path=rendered_path,
        labels=labels or {},
    )


def render_diagram_asset(asset: DiagramAsset, *, out_dir: Path) -> DiagramAsset:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{asset.id}.svg"
    render_mermaid_to_svg(asset.body, out_path=out_path)
    asset.rendered_path = str(out_path)
    # Try to also produce a PNG (used when embedding diagrams into PDF/DOCX reports).
    png_bytes = fetch_diagram_png(asset.body)
    if png_bytes:
        png_path = out_path.with_suffix(".png")
        png_path.write_bytes(png_bytes)
        asset.labels = {**(asset.labels or {}), "png_path": str(png_path)}
    return asset


# ---------------------------------------------------------------------------
# Offline flowchart renderer
#
# mermaid.ink requires network access. For simple flowcharts we render a clean
# SVG locally so diagrams still work offline. Only `graph`/`flowchart` sources
# with `ID[label] --> ID[label]` style edges are supported; anything else
# returns None and falls back to the placeholder.
# ---------------------------------------------------------------------------

_NODE_DEF_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:\[([^\]]*)\]|\(([^)]*)\)|\{([^}]*)\})?\s*$")
_EDGE_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:\[([^\]]*)\]|\(([^)]*)\)|\{([^}]*)\})?\s*"
    r"(-{1,2}>|-->|==>|-.->|---|==)\s*(?:\|([^|]*)\|\s*)?"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:\[([^\]]*)\]|\(([^)]*)\)|\{([^}]*)\})?\s*$"
)


_CHAIN_SPLIT_RE = re.compile(r"(-{1,2}>|-->|==>|-.->|---|==)")
_EDGE_LABEL_PREFIX_RE = re.compile(r"^\|([^|]*)\|\s*(.*)$")


def _parse_node_token(token: str) -> tuple[str | None, str | None, str | None]:
    """Parse `A[Label]`, `|edge label| B`, or a bare id. Returns (id, label, edge_label)."""
    token = token.strip()
    edge_label = None
    m = _EDGE_LABEL_PREFIX_RE.match(token)
    if m:
        edge_label = m.group(1).strip()
        token = m.group(2).strip()
    node = _NODE_DEF_RE.match(token)
    if node:
        node_id = node.group(1)
        label = next((g for g in node.groups()[1:] if g), None)
        return node_id, label, edge_label
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token):
        return token, None, edge_label
    return None, None, edge_label


def _local_flowchart_svg(source: str) -> str | None:
    lines = [ln.strip() for ln in source.splitlines() if ln.strip() and not ln.strip().startswith("%%")]
    if not lines:
        return None
    direction = "TD"
    body_lines = lines
    has_header = False
    header = lines[0].lower()
    if header.startswith("flowchart") or header.startswith("graph"):
        has_header = True
        parts = header.split()
        if len(parts) >= 2 and parts[-1].upper() in {"TD", "TB", "LR", "RL", "BT"}:
            direction = parts[-1].upper()
            if direction == "TB":
                direction = "TD"
        body_lines = lines[1:]

    labels: dict[str, str] = {}
    edges: list[tuple[str, str, str]] = []  # (src, dst, edge_label)
    order: list[str] = []

    def register(node_id: str, label: str | None) -> None:
        if node_id not in labels:
            order.append(node_id)
            labels[node_id] = (label or node_id).strip() or node_id
        elif label:
            labels[node_id] = label.strip()

    for line in body_lines:
        low = line.lower()
        if low.startswith(("subgraph", "end", "classdef", "class ", "style ", "link ", "click ")):
            continue
        edge = _EDGE_RE.match(line)
        if edge:
            src, s1, s2, s3, _arrow, edge_label, dst, d1, d2, d3 = edge.groups()
            src_label = next((g for g in (s1, s2, s3) if g), None)
            dst_label = next((g for g in (d1, d2, d3) if g), None)
            register(src, src_label)
            register(dst, dst_label)
            edges.append((src, dst, (edge_label or "").strip()))
            continue
        segments = _CHAIN_SPLIT_RE.split(line)
        if len(segments) > 2:
            parsed = [_parse_node_token(t) for t in segments[0::2]]
            for i in range(len(parsed) - 1):
                src_id, src_label, _ = parsed[i]
                dst_id, dst_label, dst_edge_label = parsed[i + 1]
                if src_id and dst_id:
                    register(src_id, src_label)
                    register(dst_id, dst_label)
                    edges.append((src_id, dst_id, dst_edge_label or ""))
            continue
        node = _NODE_DEF_RE.match(line)
        if node:
            node_id = node.group(1)
            label = next((g for g in node.groups()[1:] if g), None)
            register(node_id, label)

    if not order:
        return None
    if not has_header and not edges:
        # Without an explicit flowchart/graph header, only render when real
        # edges were found — avoids turning arbitrary text into a node diagram.
        return None

    horizontal = direction in {"LR", "RL"}
    node_w, node_h, gap_x, gap_y = 150, 54, 70, 60
    count = len(order)
    if horizontal:
        width = count * (node_w + gap_x) + 40
        height = 220
    else:
        width = 560
        height = count * (node_h + gap_y) + 40

    positions: dict[str, tuple[float, float]] = {}
    for i, node_id in enumerate(order):
        if horizontal:
            x = 20 + i * (node_w + gap_x)
            y = height / 2 - node_h / 2
        else:
            x = width / 2 - node_w / 2
            y = 20 + i * (node_h + gap_y)
        positions[node_id] = (x, y)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="Segoe UI, Arial, sans-serif">',
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        'markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" '
        'fill="#475569"/></marker></defs>',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
    ]

    for src, dst, edge_label in edges:
        if src not in positions or dst not in positions:
            continue
        x1, y1 = positions[src]
        x2, y2 = positions[dst]
        cx1, cy1 = x1 + node_w / 2, y1 + node_h / 2
        cx2, cy2 = x2 + node_w / 2, y2 + node_h / 2
        # Trim the line so it starts/ends at the node borders.
        dx, dy = cx2 - cx1, cy2 - cy1
        length = max(1.0, (dx * dx + dy * dy) ** 0.5)
        sx = cx1 + dx / length * (node_w / 2 if abs(dx) >= abs(dy) else 0)
        sy = cy1 + dy / length * (node_h / 2 if abs(dy) > abs(dx) else 0)
        ex = cx2 - dx / length * (node_w / 2 if abs(dx) >= abs(dy) else 0)
        ey = cy2 - dy / length * (node_h / 2 if abs(dy) > abs(dx) else 0)
        parts.append(
            f'<line x1="{sx:.1f}" y1="{sy:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" '
            f'stroke="#475569" stroke-width="1.6" marker-end="url(#arrow)"/>'
        )
        if edge_label:
            mx, my = (sx + ex) / 2, (sy + ey) / 2
            parts.append(
                f'<text x="{mx:.1f}" y="{my - 4:.1f}" font-size="10" fill="#64748b" '
                f'text-anchor="middle">{_svg_escape(edge_label)}</text>'
            )

    for node_id, (x, y) in positions.items():
        lines_text = _wrap_svg_text(labels.get(node_id, node_id), max_chars=22)
        text_y = y + node_h / 2 - 6 - (len(lines_text) - 1) * 7
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{node_w}" height="{node_h}" rx="8" '
            f'fill="#eef2ff" stroke="#4f46e5" stroke-width="1.4"/>'
        )
        for i, ln in enumerate(lines_text):
            parts.append(
                f'<text x="{x + node_w / 2:.1f}" y="{text_y + i * 14:.1f}" font-size="12" '
                f'fill="#1e293b" text-anchor="middle">{_svg_escape(ln)}</text>'
            )

    parts.append("</svg>")
    return "\n".join(parts)


def _svg_escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
