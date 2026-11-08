from __future__ import annotations

import pathlib
import tempfile

from backend.diagrams import (
    ALLOWED_KINDS,
    sanitize_mermaid,
    validate_mermaid,
    render_mermaid_to_svg,
    build_diagram_asset,
)


def test_allowed_kinds_defined():
    assert "flowchart" in ALLOWED_KINDS
    assert "sequence" in ALLOWED_KINDS
    assert "architecture_block" in ALLOWED_KINDS


def test_sanitize_mermaid_strips_dangerous_directives():
    source = "graph TD\nlink https://evil.example\nevil\n"
    sanitized = sanitize_mermaid(source)
    assert "link" not in sanitized.lower() or "https://" not in sanitized


def test_validate_mermaid_empty_source_warns():
    warnings = validate_mermaid("")
    assert any("empty" in w.lower() for w in warnings)


def test_validate_mermaid_accepts_simple_flowchart():
    source = "graph TD\nA-->B\nB-->C"
    warnings = validate_mermaid(source)
    assert not warnings or len(warnings) == 0


def test_build_diagram_asset_has_id_and_kind():
    asset = build_diagram_asset(kind="flowchart", title="Test", source="graph TD\nA-->B", body="graph TD\nA-->B")
    assert asset.kind == "flowchart"
    assert asset.id.startswith("diagram_")


def test_render_mermaid_to_svg_creates_file_unavailable_internet():
    source = "graph TD\nStart-->End"
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / "out.svg"
        result = render_mermaid_to_svg(source, out_path=out)
        assert result.exists()
        text = result.read_text(encoding="utf-8", errors="replace")
        # Real network may return a mermaid.ink SVG; offline fallback returns a placeholder.
        # Either is acceptable: the file is a valid SVG.
        assert "<svg" in text
