"""Structural paragraph style catalog for generated DOCX files."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from docxtool.document.style_config import PageSettings, StyleRule


@dataclass(frozen=True)
class _ParagraphStyleSpec:
    style_id: str
    name: str
    rule_index: int
    alignment: str | None = None
    first_line_indent: float | None = None
    keep_with_next: bool = False
    outline_level: int | None = None


_STYLE_SPECS: tuple[_ParagraphStyleSpec, ...] = (
    _ParagraphStyleSpec("DCT-Title", "Docxtool Title", 0, "居中", 0.0, True),
    _ParagraphStyleSpec("DCT-DocumentNumber", "Docxtool Document Number", 5, "居中", 0.0),
    _ParagraphStyleSpec("DCT-Author", "Docxtool Author", 12, "居中", 0.0),
    _ParagraphStyleSpec("DCT-RoleName", "Docxtool Role Name", 13, "居中", 0.0),
    _ParagraphStyleSpec("DCT-Recipient", "Docxtool Recipient", 10, "左对齐", 2.0),
    _ParagraphStyleSpec("DCT-Heading1", "Docxtool Heading 1", 1, "左对齐", 2.0, False, 0),
    _ParagraphStyleSpec("DCT-Heading2", "Docxtool Heading 2", 2, "左对齐", 2.0, False, 1),
    _ParagraphStyleSpec("DCT-Heading3", "Docxtool Heading 3", 3, "左对齐", 2.0, False, 2),
    _ParagraphStyleSpec("DCT-Heading4", "Docxtool Heading 4", 4, "左对齐", 2.0, False, 3),
    _ParagraphStyleSpec("DCT-Body", "Docxtool Body", 5, "两端对齐", 2.0),
    _ParagraphStyleSpec("DCT-Responsibility", "Docxtool Responsibility", 5, "左对齐", 0.0),
    _ParagraphStyleSpec("DCT-Signature", "Docxtool Signature", 22, "右对齐", 0.0),
    _ParagraphStyleSpec("DCT-Date", "Docxtool Date", 23, "右对齐", 0.0),
    _ParagraphStyleSpec("DCT-AttachmentNote", "Docxtool Attachment Note", 17, "左对齐", 0.0),
    _ParagraphStyleSpec("DCT-AttachmentNoteItem", "Docxtool Attachment Note Item", 18, "左对齐", 0.0),
    _ParagraphStyleSpec("DCT-AttachmentMark", "Docxtool Attachment Mark", 19, "左对齐", 0.0, True),
    _ParagraphStyleSpec("DCT-AttachmentTitle", "Docxtool Attachment Title", 20, "居中", 0.0, True),
    _ParagraphStyleSpec("DCT-AttachmentBody", "Docxtool Attachment Body", 21, "两端对齐", 2.0),
)

_ALIGNMENT_TO_JC = {
    "左对齐": "left",
    "居中": "center",
    "右对齐": "right",
    "两端对齐": "both",
}


def ensure_document_styles(
    document,
    rules: Sequence[StyleRule] | None,
    settings: PageSettings | None,
) -> None:
    """Ensure stable structural paragraph styles exist in *document*.

    The catalog only writes paragraph-level style properties. It does not apply
    styles to document paragraphs, rewrite text, create numbering definitions,
    or move run-level font logic out of the renderer.
    """

    resolved_rules = list(rules or [])
    resolved_settings = settings or PageSettings()
    styles_element = document.styles._element

    for spec in _STYLE_SPECS:
        style = _get_or_create_style(styles_element, spec)
        _replace_ppr(style, _build_ppr(spec, _rule_at(resolved_rules, spec.rule_index), resolved_settings))


def _rule_at(rules: Sequence[StyleRule], index: int) -> StyleRule:
    if 0 <= index < len(rules):
        return rules[index]
    return StyleRule.default_for_row(index)


def _get_or_create_style(styles_element, spec: _ParagraphStyleSpec):
    for style in styles_element.findall(qn("w:style")):
        if style.get(qn("w:styleId")) == spec.style_id:
            _ensure_child_value(style, "w:name", spec.name)
            _ensure_child_value(style, "w:basedOn", "Normal")
            return style

    style = OxmlElement("w:style")
    style.set(qn("w:type"), "paragraph")
    style.set(qn("w:styleId"), spec.style_id)
    styles_element.append(style)
    _ensure_child_value(style, "w:name", spec.name)
    _ensure_child_value(style, "w:basedOn", "Normal")
    return style


def _ensure_child_value(parent, tag: str, value: str):
    element = parent.find(qn(tag))
    if element is None:
        element = OxmlElement(tag)
        parent.append(element)
    element.set(qn("w:val"), value)
    return element


def _replace_ppr(style, ppr) -> None:
    old = style.find(qn("w:pPr"))
    if old is not None:
        style.remove(old)
    style.append(ppr)


def _build_ppr(spec: _ParagraphStyleSpec, rule: StyleRule, settings: PageSettings):
    ppr = OxmlElement("w:pPr")

    if spec.keep_with_next:
        ppr.append(OxmlElement("w:keepNext"))
        ppr.append(OxmlElement("w:keepLines"))

    if spec.outline_level is not None:
        outline = OxmlElement("w:outlineLvl")
        outline.set(qn("w:val"), str(spec.outline_level))
        ppr.append(outline)

    alignment = spec.alignment or getattr(rule, "alignment", "")
    jc_value = _ALIGNMENT_TO_JC.get(alignment, "left")
    jc = OxmlElement("w:jc")
    jc.set(qn("w:val"), jc_value)
    ppr.append(jc)

    first_line_indent = (
        spec.first_line_indent
        if spec.first_line_indent is not None
        else float(getattr(rule, "first_line_indent", 0.0) or 0.0)
    )
    ppr.append(_indent_element(first_line_indent))
    ppr.append(_spacing_element(rule, settings))

    return ppr


def _indent_element(first_line_indent: float):
    chars = max(float(first_line_indent or 0.0), 0.0)
    ind = OxmlElement("w:ind")
    ind.set(qn("w:firstLineChars"), str(int(round(chars * 100))))
    ind.set(qn("w:firstLine"), str(int(round(chars * 320))))
    return ind


def _spacing_element(rule: StyleRule, settings: PageSettings):
    line_twips = _line_spacing_twips(settings)
    before_value = getattr(rule, "spacing_before", None)
    after_value = getattr(rule, "spacing_after", None)
    before_lines = float(
        getattr(settings, "space_before_line", 0.0) if before_value is None else before_value
    )
    after_lines = float(
        getattr(settings, "space_after_line", 0.0) if after_value is None else after_value
    )

    spacing = OxmlElement("w:spacing")
    spacing.set(qn("w:before"), str(int(round(before_lines * line_twips))))
    spacing.set(qn("w:after"), str(int(round(after_lines * line_twips))))
    spacing.set(qn("w:beforeLines"), str(int(round(before_lines * 100))))
    spacing.set(qn("w:afterLines"), str(int(round(after_lines * 100))))
    spacing.set(qn("w:line"), str(line_twips))
    spacing.set(qn("w:lineRule"), "exact")
    return spacing


def _line_spacing_twips(settings: PageSettings) -> int:
    try:
        value = float(settings.line_spacing_value)
    except (TypeError, ValueError):
        value = 28.0
    if value <= 0:
        value = 28.0
    return int(round(value * 20))


__all__ = ["ensure_document_styles"]
