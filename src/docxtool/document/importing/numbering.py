"""DOCX 文本编号前缀的物理特征提取。"""

from __future__ import annotations

import re


NUMBERING_PATTERNS = [
    (re.compile(r'^[一二三四五六七八九十百]+[、.．]+'), "chinese_dun"),
    (re.compile(r'^[（\(][一二三四五六七八九十百]+[）\)]'), "chinese_paren"),
    (re.compile(r'^\d+[.．]'), "digit_dot"),
    (re.compile(r'^[（\(]\d+[）\)]'), "digit_paren"),
    (re.compile(r'^\[(\d+)\]'), "bracket_ref"),
    (re.compile(r'^-\s*\d+\s*-'), "page_num"),
]

HEADING_STYLE_TYPES = {
    "heading 1": "heading1", "heading1": "heading1",
    "标题 1": "heading1", "标题1": "heading1",
    "heading 2": "heading2", "heading2": "heading2",
    "标题 2": "heading2", "标题2": "heading2",
    "heading 3": "heading3", "heading3": "heading3",
    "标题 3": "heading3", "标题3": "heading3",
    "heading 4": "heading4", "heading4": "heading4",
    "标题 4": "heading4", "标题4": "heading4",
}


def detect_numbering_prefix(text: str) -> str:
    """传入段落文本，返回匹配到的字面编号前缀；无编号时返回空字符串。"""
    for pattern, _name in NUMBERING_PATTERNS:
        match = pattern.match(text)
        if match:
            return match.group(0)
    return ""


def literal_digit_numbering_present(text: str) -> bool:
    """传入段落文本，返回开头是否已有阿拉伯数字类字面编号。"""
    return bool(re.match(r'^[（\(]?\d+[）\)\.．]', (text or "").strip()))


def word_list_level_prefix(paragraph_element, text: str) -> str:
    """传入段落 OOXML 元素和文本，返回 Word 多级列表层级前缀或空字符串。"""
    from docx.oxml.ns import qn as _qn

    pPr = paragraph_element.find(_qn('w:pPr'))
    if pPr is None:
        return ""
    numPr = pPr.find(_qn('w:numPr'))
    if numPr is None:
        return ""
    ilvl_el = numPr.find(_qn('w:ilvl'))
    lvl = int(ilvl_el.get(_qn('w:val'), '0')) if ilvl_el is not None else 0
    if literal_digit_numbering_present(text):
        return ""
    return f"@lvl_{lvl}"


def heading_style_prefix(style_name: str) -> str:
    """传入 Word 样式名称，返回系统内部 heading 样式前缀或空字符串。"""
    normalized = (style_name or "").lower()
    type_id = HEADING_STYLE_TYPES.get(normalized)
    return f"@style_{type_id}" if type_id else ""
