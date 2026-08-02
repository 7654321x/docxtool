"""DOCX 文本编号前缀的物理特征提取。"""

from __future__ import annotations

import re
from typing import Any


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


def apply_physical_numbering_features(
    features: Any,
    paragraph_element,
    text: str,
    *,
    debug_logger: Any,
) -> None:
    """把既有 Word 列表和标题样式事实写入段落特征。

    该入口只收口原物理读取顺序：先尝试 ``w:numPr``，再应用 Word 标题
    样式。异常吞吐、日志和前缀覆盖规则均与迁移前一致，不解析或新增最终
    标题类型，也不构造新的编号元数据。
    """
    try:
        word_prefix = word_list_level_prefix(paragraph_element, text)
        if word_prefix and not features.numbering_prefix:
            features.numbering_prefix = word_prefix
            lvl = int(word_prefix[5:])
            debug_logger.debug(
                "[多级列表] ilvl=%s → heading%s chars=%s",
                lvl,
                lvl + 2,
                len(text),
            )
    except Exception as exc:
        debug_logger.debug("[多级列表] 提取失败: %s", exc)

    try:
        style_prefix = heading_style_prefix(features.style_name)
        if style_prefix:
            features.numbering_prefix = style_prefix
    except Exception:
        pass


def is_auto_numbered_item(features: Any) -> bool:
    """判断段落特征是否来自 Word 自动列表或标题样式编号。

    传入数据是带 `numbering_prefix` 属性的段落特征对象。返回值为布尔值，
    只表示存在 Word 原生编号事实，不决定附件项、标题或正文的最终类型。
    """
    prefix = getattr(features, "numbering_prefix", "") if features is not None else ""
    return bool(prefix and (prefix.startswith("@lvl_") or prefix.startswith("@style_")))
