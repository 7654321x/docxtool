"""Paragraph-level formatting helpers for the DOCX renderer.

本模块只负责渲染阶段的段落直接格式：字体、对齐、缩进、段前段后、
网格对齐和孤行控制。它只消费已经确定的 ``StyleRule``，不读取识别
上下文，也不改变段落文本、顺序或最终类型。
"""

from __future__ import annotations

import copy

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

from docxtool.document.engine.typography import set_run_fonts
from docxtool.document.style_config import StyleRule, logger


def apply_right_indent(paragraph, characters: float = 2) -> None:
    """设置右缩进；传入段落和字符数，直接修改段落并返回 None。"""
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    properties = paragraph._element.get_or_add_pPr()
    indent = properties.find(qn("w:ind"))
    if indent is None:
        indent = OxmlElement("w:ind")
        properties.append(indent)
    for attr in ("w:left", "w:leftChars", "w:firstLine", "w:firstLineChars", "w:hanging", "w:hangingChars"):
        indent.attrib.pop(qn(attr), None)
    indent.set(qn("w:right"), str(int(characters * 560)))
    indent.set(qn("w:rightChars"), str(int(round(characters * 100))))


def set_widow_control(paragraph, enabled: bool) -> None:
    """设置孤行控制开关；传入段落和布尔值，返回 None。"""
    properties = paragraph._element.get_or_add_pPr()
    widow_control = OxmlElement("w:widowControl")
    widow_control.set(qn("w:val"), "1" if enabled else "0")
    _set_unique(properties, qn("w:widowControl"), widow_control)


def apply_first_line_indent_chars(paragraph, chars: int) -> None:
    """设置首行缩进；传入段落和字符数，清除冲突缩进后返回 None。"""
    properties = paragraph._element.get_or_add_pPr()
    indent = _get_or_add_indent(properties)
    _clear_indent_attrs(indent)
    indent.set(qn("w:firstLineChars"), str(chars * 100))
    indent.set(qn("w:firstLine"), str(chars * 320))


def apply_left_indent_chars(paragraph, chars: float) -> None:
    """设置整段左缩进；传入段落和字符数，清除首行/悬挂缩进后返回 None。"""
    properties = paragraph._element.get_or_add_pPr()
    indent = _get_or_add_indent(properties)
    _clear_indent_attrs(indent)
    indent.set(qn("w:leftChars"), str(int(chars * 100)))
    indent.set(qn("w:left"), str(int(chars * 320)))


def apply_hanging_indent_chars(paragraph, first_chars: float, follow_chars: float) -> None:
    """设置兼容悬挂缩进；传入首行和后续行字符列，返回 None。"""
    base = max(float(first_chars or 0), 0.0)
    follow = max(float(follow_chars or base), base)
    properties = paragraph._element.get_or_add_pPr()
    indent = _get_or_add_indent(properties)
    _clear_indent_attrs(indent)
    indent.set(qn("w:firstLineChars"), str(int(base * 100)))
    indent.set(qn("w:firstLine"), str(int(base * 320)))
    if follow > base:
        hanging = int(max(0, round((follow - base) * 100)))
        if hanging:
            indent.set(qn("w:hangingChars"), str(hanging))


def set_para_spacing(
    paragraph,
    before_lines: float = 0,
    after_lines: float = 0,
    line_twips: int = 560,
    *,
    explicit_zero: bool = False,
) -> None:
    """设置段落间距；传入段落、段前/段后行数和行距 twips，返回 None。"""
    properties = paragraph._element.get_or_add_pPr()
    spacing = OxmlElement("w:spacing")
    if before_lines > 0 or explicit_zero:
        spacing.set(qn("w:before"), str(int(round(before_lines * line_twips))))
        spacing.set(qn("w:beforeLines"), str(int(round(before_lines * 100))))
    if after_lines > 0 or explicit_zero:
        spacing.set(qn("w:after"), str(int(round(after_lines * line_twips))))
        spacing.set(qn("w:afterLines"), str(int(round(after_lines * 100))))
    if line_twips > 0:
        spacing.set(qn("w:line"), str(line_twips))
        spacing.set(qn("w:lineRule"), "exact")
    _set_unique(properties, qn("w:spacing"), spacing)


def apply_rule_paragraph_format(paragraph, rule: StyleRule, line_twips: int) -> None:
    """应用段落级 StyleRule；传入段落、规则和行距，返回 None。"""
    set_para_spacing(
        paragraph,
        before_lines=getattr(rule, "spacing_before", 0.0) or 0.0,
        after_lines=getattr(rule, "spacing_after", 0.0) or 0.0,
        line_twips=line_twips,
    )
    left_indent = getattr(rule, "left_indent", 0.0) or 0.0
    right_indent = getattr(rule, "right_indent", 0.0) or 0.0
    if left_indent > 0:
        apply_left_indent_chars(paragraph, left_indent)
    if right_indent > 0:
        apply_right_indent(paragraph, right_indent)
    if getattr(rule, "page_break_before", False):
        properties = paragraph._element.get_or_add_pPr()
        page_break = OxmlElement("w:pageBreakBefore")
        _set_unique(properties, qn("w:pageBreakBefore"), page_break)


def apply_style(paragraph, rule: StyleRule) -> None:
    """应用 run 和基础段落样式；传入段落和 StyleRule，返回 None。"""
    if not paragraph.runs:
        paragraph.add_run("")

    for run in paragraph.runs:
        set_run_fonts(run, cn_font=rule.font, en_font="Times New Roman")
        run.font.size = Pt(rule.font_size_pt)
        if rule.bold is not None:
            run.font.bold = rule.bold

    align_id = align_to_enum(rule.alignment)
    if align_id is not None:
        paragraph.alignment = align_id

    if rule.row_index >= 5:
        properties = paragraph._element.get_or_add_pPr()
        snap = OxmlElement("w:snapToGrid")
        snap.set(qn("w:val"), "1")
        _set_unique(properties, qn("w:snapToGrid"), snap)

    if rule.row_index < 5:
        properties = paragraph._element.get_or_add_pPr()
        snap = OxmlElement("w:snapToGrid")
        snap.set(qn("w:val"), "0")
        _set_unique(properties, qn("w:snapToGrid"), snap)
        widow_control = OxmlElement("w:widowControl")
        widow_control.set(qn("w:val"), "0")
        _set_unique(properties, qn("w:widowControl"), widow_control)
        for run in paragraph.runs:
            run_properties = run._element.get_or_add_rPr()
            spacing = OxmlElement("w:spacing")
            spacing.set(qn("w:val"), "0")
            run_properties.append(spacing)

    if rule.first_line_indent > 0:
        properties = paragraph._element.get_or_add_pPr()
        indent = _get_or_add_indent(properties)
        indent.set(qn("w:firstLineChars"), str(int(rule.first_line_indent * 100)))
        indent.attrib.pop(qn("w:firstLine"), None)


def align_to_enum(align_str: str):
    """转换对齐值；传入中英文对齐字符串，返回 python-docx 枚举或 None。"""
    mapping = {
        "left": WD_ALIGN_PARAGRAPH.LEFT,
        "center": WD_ALIGN_PARAGRAPH.CENTER,
        "right": WD_ALIGN_PARAGRAPH.RIGHT,
        "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
        "distribute": WD_ALIGN_PARAGRAPH.DISTRIBUTE,
    }
    zh_to_en = {
        "左对齐": "left",
        "居中": "center",
        "右对齐": "right",
        "两端对齐": "justify",
        "分散对齐": "distribute",
    }
    key = zh_to_en.get(align_str, align_str)
    return mapping.get(key)


def apply_style_safe(paragraph, rule: StyleRule) -> bool:
    """安全应用样式；传入段落和规则，成功返回 True，降级失败返回 False。"""
    try:
        apply_style(paragraph, rule)
        return True
    except Exception as exc:
        logger.warning("[引擎] 字体 '%s' 应用失败: %s，回退宋体", rule.font, exc)
        try:
            fallback = copy.copy(rule)
            fallback.font = "宋体"
            fallback.font_size_pt = 12
            fallback.bold = False
            apply_style(paragraph, fallback)
        except Exception as fallback_exc:
            logger.error("[引擎] 完全降级失败: %s", fallback_exc)
        return False


def _get_or_add_indent(properties):
    """获取缩进节点；传入 pPr，返回已有或新建的 w:ind。"""
    indent = properties.find(qn("w:ind"))
    if indent is None:
        indent = OxmlElement("w:ind")
        properties.append(indent)
    return indent


def _clear_indent_attrs(indent) -> None:
    """清除缩进冲突属性；传入 w:ind 节点，返回 None。"""
    for attr in (
        qn("w:firstLine"),
        qn("w:firstLineChars"),
        qn("w:left"),
        qn("w:leftChars"),
        qn("w:hanging"),
        qn("w:hangingChars"),
    ):
        indent.attrib.pop(attr, None)


def _set_unique(properties, tag, element) -> None:
    """替换同名子节点；传入父节点、标签和新节点，返回 None。"""
    old = properties.find(tag)
    if old is not None:
        properties.remove(old)
    properties.append(element)
