"""Opt-in conservative cleanup for explicitly configured run-level style anomalies."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from docx.enum.text import WD_COLOR_INDEX
from docx.oxml.ns import qn


def cleanup_styles(document, options: Mapping[str, Any] | None = None, protected_elements=None):
    """Clean only configured safe style anomalies; default mode is off."""

    opts = dict(options or {})
    if str(opts.get("mode", "off")).lower() != "safe":
        return document

    highlight_colors = _normalized_highlights(opts.get("clear_highlight_colors", ()))
    shading_fills = _normalized_hex_values(opts.get("clear_shading_fills", ()))
    font_colors = _normalized_hex_values(opts.get("clear_font_colors", ()))
    underline_values = set(opts.get("clear_underline_values", ()) or ())
    italic_values = set(opts.get("clear_italic_values", ()) or ())
    if not any((highlight_colors, shading_fills, font_colors, underline_values, italic_values)):
        return document

    protected_elements = protected_elements or set()
    # Object paragraphs and table-cell paragraphs are pass-through content.
    # Cleanup is intentionally limited to ordinary top-level body paragraphs.
    for paragraph in getattr(document, "paragraphs", []):
        if paragraph._p in protected_elements:
            continue
        if _paragraph_is_signature_related(paragraph):
            continue
        for run in paragraph.runs:
            if _run_is_protected(run):
                continue
            _cleanup_run(run, highlight_colors, shading_fills, font_colors, underline_values, italic_values)
    return document


def _cleanup_run(run, highlight_colors, shading_fills, font_colors, underline_values, italic_values) -> None:
    if highlight_colors and run.font.highlight_color in highlight_colors:
        run.font.highlight_color = None
    if font_colors and run.font.color.rgb is not None:
        color = str(run.font.color.rgb).upper()
        if color in font_colors:
            run.font.color.rgb = None
    if underline_values and _underline_matches(run.font.underline, underline_values):
        run.font.underline = None
    if italic_values and run.font.italic in italic_values:
        run.font.italic = None
    if shading_fills:
        r_pr = run._element.rPr
        if r_pr is not None:
            for shading in list(r_pr.findall(qn("w:shd"))):
                fill = (shading.get(qn("w:fill")) or "").upper()
                if fill in shading_fills:
                    r_pr.remove(shading)


def _iter_paragraphs(container):
    for paragraph in getattr(container, "paragraphs", []):
        yield paragraph
    for table in getattr(container, "tables", []):
        for row in table.rows:
            for cell in row.cells:
                yield from _iter_paragraphs(cell)


def _run_is_protected(run) -> bool:
    parent = run._element.getparent()
    while parent is not None:
        if parent.tag in {
            qn("w:hyperlink"),
            qn("w:ins"),
            qn("w:del"),
            qn("w:moveFrom"),
            qn("w:moveTo"),
            qn("w:smartTag"),
        }:
            return True
        parent = parent.getparent()
    return False


def _paragraph_is_signature_related(paragraph) -> bool:
    text = paragraph.text
    return "电子签名" in text or ("签名" in text and ("有效" in text or "Signature" in text))


def _underline_matches(value, configured: set[Any]) -> bool:
    if value in configured:
        return True
    if value is True and ("single" in configured or "true" in configured):
        return True
    return str(value).lower() in {str(item).lower() for item in configured}


def _normalized_hex_values(values) -> set[str]:
    return {str(value).strip().lstrip("#").upper() for value in values or () if str(value).strip()}


def _normalized_highlights(values) -> set[WD_COLOR_INDEX]:
    result = set()
    by_name = {name.lower(): color for name, color in WD_COLOR_INDEX.__members__.items()}
    for value in values or ():
        if isinstance(value, WD_COLOR_INDEX):
            result.add(value)
            continue
        text = str(value).strip().lower()
        if text in by_name:
            result.add(by_name[text])
    return result
