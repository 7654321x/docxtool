"""Conservative signature and document-date layout helpers."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import Any

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


_SIGNATURE_STYLE_ID = "DCT-Signature"
_DATE_STYLE_ID = "DCT-Date"
_COMPLEX_TAGS = ("w:drawing", "w:pict", "w:object")
_MULTI_AGENCY_SPACING_RE = re.compile(r"\s{2,}")


def apply_signature_block(document, options: Mapping[str, Any] | None = None) -> int:
    """Apply the selected layout to reliable single-agency signature pairs."""

    mode = str((options or {}).get("mode", "preserve")).strip().lower()
    if mode == "preserve":
        return 0
    if mode not in {"without_seal", "with_seal"}:
        return 0

    adjusted = 0
    for date_paragraph in document.paragraphs:
        if _style_id(date_paragraph) != _DATE_STYLE_ID:
            continue
        signature_paragraph = _reliable_signature_before(date_paragraph)
        if signature_paragraph is None:
            continue
        if mode == "with_seal":
            _apply_with_seal(signature_paragraph, date_paragraph)
        else:
            _apply_without_seal(signature_paragraph, date_paragraph)
        adjusted += 1
    return adjusted


def _reliable_signature_before(date_paragraph):
    date_element = date_paragraph._p
    signature_element = date_element.getprevious()
    if signature_element is None or signature_element.tag != qn("w:p"):
        return None
    if _element_style_id(signature_element) != _SIGNATURE_STYLE_ID:
        return None
    if date_element.getparent() is not signature_element.getparent():
        return None

    previous = signature_element.getprevious()
    if previous is not None and previous.tag == qn("w:p"):
        if _element_style_id(previous) == _SIGNATURE_STYLE_ID:
            return None
    following = date_element.getnext()
    if following is not None and following.tag == qn("w:p"):
        if _element_style_id(following) == _DATE_STYLE_ID:
            return None

    signature_paragraph = next(
        (paragraph for paragraph in date_paragraph._parent.paragraphs if paragraph._p is signature_element),
        None,
    )
    if signature_paragraph is None:
        return None
    if not _is_simple_single_line(signature_paragraph) or not _is_simple_single_line(date_paragraph):
        return None
    if _MULTI_AGENCY_SPACING_RE.search(signature_paragraph.text):
        return None
    return signature_paragraph


def _is_simple_single_line(paragraph) -> bool:
    if not paragraph.text.strip() or "\n" in paragraph.text or "\t" in paragraph.text:
        return False
    return not any(
        paragraph._p.find(".//" + qn(tag)) is not None for tag in _COMPLEX_TAGS
    )


def _style_id(paragraph) -> str:
    return paragraph.style.style_id if paragraph.style is not None else ""


def _element_style_id(element) -> str:
    properties = element.find(qn("w:pPr"))
    style = properties.find(qn("w:pStyle")) if properties is not None else None
    return style.get(qn("w:val"), "") if style is not None else ""


def _apply_without_seal(signature_paragraph, date_paragraph) -> None:
    _set_right_indent(signature_paragraph, 2.0)
    _set_right_indent(date_paragraph, 4.0)


def _apply_with_seal(signature_paragraph, date_paragraph) -> None:
    signature_width = _display_width(signature_paragraph.text)
    date_width = _display_width(date_paragraph.text)
    date_right_indent = 4.0
    signature_right_indent = max(
        0.0,
        date_right_indent + (date_width - signature_width) / 2,
    )
    _set_right_indent(signature_paragraph, signature_right_indent)
    _set_right_indent(date_paragraph, date_right_indent)


def _display_width(text: str) -> float:
    width = 0.0
    for character in text.strip():
        if character.isspace():
            continue
        width += 1.0 if unicodedata.east_asian_width(character) in {"W", "F", "A"} else 0.5
    return width


def _set_right_indent(paragraph, characters: float) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    properties = paragraph._element.get_or_add_pPr()
    indent = properties.find(qn("w:ind"))
    if indent is None:
        indent = OxmlElement("w:ind")
        properties.append(indent)
    for name in (
        "w:left",
        "w:leftChars",
        "w:right",
        "w:rightChars",
        "w:firstLine",
        "w:firstLineChars",
        "w:hanging",
        "w:hangingChars",
    ):
        indent.attrib.pop(qn(name), None)
    hundredths = max(0, round(characters * 100))
    indent.set(qn("w:rightChars"), str(hundredths))
    indent.set(qn("w:right"), str(round(characters * 16 * 20)))
