"""Renderer helpers for reliable heading/body split output.

本模块只处理识别和分段已经确认的 ``标题。正文`` 输出形态：把标题
写在当前段落，把正文写入紧邻的新段落，并在导出末尾校验二者没有被
后续格式流程破坏。它不判断是否应该拆段。
"""

from __future__ import annotations

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from docxtool.document.engine.inline import segment_writer
from docxtool.document.engine.inline_effects import INLINE_HEADING_BODY_MIN_CHARS
from docxtool.document.engine.paragraph_format import apply_rule_paragraph_format, apply_style_safe
from docxtool.document.engine.paragraph_styles import set_paragraph_style_id
from docxtool.document.engine.typography import set_run_fonts
from docxtool.document.errors import ExportError


def insert_paragraph_after(paragraph) -> Paragraph:
    """在指定段落后插入新段落；传入 paragraph，返回新 Paragraph。"""
    new_element = OxmlElement("w:p")
    paragraph._p.addnext(new_element)
    return Paragraph(new_element, paragraph._parent)


def apply_inline_heading_body_split(
    paragraph,
    text: str,
    rule,
    body_rule,
    line_twips: int,
    *,
    remove_heading_period: bool = False,
    body_style_id: str = "DCT-Body",
):
    """输出标题正文拆分；传入段落、文本和样式规则，返回正文段落或 None。"""
    period = text.find("。")
    if period <= 0 or period >= len(text) - 1:
        return None
    body_text = text[period + 1:].strip()
    if len(body_text) < INLINE_HEADING_BODY_MIN_CHARS:
        return None

    heading_text = text[:period].rstrip() if remove_heading_period else text[:period + 1]
    write = segment_writer(paragraph, set_run_fonts=set_run_fonts)
    write(heading_text)

    body_paragraph = insert_paragraph_after(paragraph)
    body_paragraph.add_run(body_text)
    set_paragraph_style_id(body_paragraph, body_style_id)
    apply_style_safe(body_paragraph, body_rule)
    apply_rule_paragraph_format(body_paragraph, body_rule, line_twips)
    properties = body_paragraph._element.get_or_add_pPr()
    widow_control = OxmlElement("w:widowControl")
    widow_control.set(qn("w:val"), "0")
    _set_unique(properties, qn("w:widowControl"), widow_control)
    contextual_spacing = OxmlElement("w:contextualSpacing")
    contextual_spacing.set(qn("w:val"), "0")
    _set_unique(properties, qn("w:contextualSpacing"), contextual_spacing)
    snap = OxmlElement("w:snapToGrid")
    snap.set(qn("w:val"), "1")
    _set_unique(properties, qn("w:snapToGrid"), snap)
    return body_paragraph


def verify_inline_heading_body_pair(
    heading_paragraph,
    body_paragraph,
    expected_body_text: str,
    *,
    expected_body_style_id: str = "DCT-Body",
) -> None:
    """校验标题正文相邻和正文完整；传入两段和期望正文，异常表示导出不安全。"""
    if heading_paragraph._p.getnext() is not body_paragraph._p:
        raise ExportError("一级标题与其完整正文段不再相邻，已中止导出")
    if body_paragraph.text != expected_body_text:
        raise ExportError("一级标题后的正文未完整保留，已中止导出")
    if body_paragraph.style.style_id != expected_body_style_id:
        raise ExportError("一级标题后的正文未使用正文样式，已中止导出")


def _set_unique(properties, tag, element) -> None:
    """替换同名子节点；传入父节点、标签和新节点，返回 None。"""
    old = properties.find(tag)
    if old is not None:
        properties.remove(old)
    properties.append(element)
