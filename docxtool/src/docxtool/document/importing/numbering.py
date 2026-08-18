"""DOCX 文本编号前缀的物理特征提取。"""

from __future__ import annotations

import copy
import re
from typing import Any

from docxtool.document.models import NativeNumbering


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


def _value(element, child_tag: str, default: str = "") -> str:
    """读取一个编号子元素的 ``w:val``。"""
    from docx.oxml.ns import qn

    child = element.find(qn(child_tag)) if element is not None else None
    return child.get(qn("w:val"), default) if child is not None else default


def _find_by_id(root, tag: str, attribute: str, value: int):
    from docx.oxml.ns import qn

    expected = str(value)
    return next(
        (
            element
            for element in root.findall(qn(tag))
            if element.get(qn(attribute)) == expected
        ),
        None,
    )


def _direct_num_pr(paragraph_element):
    from docx.oxml.ns import qn

    properties = paragraph_element.find(qn("w:pPr"))
    return properties.find(qn("w:numPr")) if properties is not None else None


def _style_num_pr(paragraph):
    from docx.oxml.ns import qn

    style = getattr(paragraph, "style", None)
    visited: set[str] = set()
    while style is not None:
        style_id = str(getattr(style, "style_id", "") or "")
        if style_id in visited:
            break
        visited.add(style_id)
        properties = style.element.find(qn("w:pPr"))
        if properties is not None:
            num_pr = properties.find(qn("w:numPr"))
            if num_pr is not None:
                return num_pr
        style = style.base_style
    return None


def _level_definition(abstract_num, ilvl: int):
    from docx.oxml.ns import qn

    return next(
        (
            level
            for level in abstract_num.findall(qn("w:lvl"))
            if int(level.get(qn("w:ilvl"), "0")) == ilvl
        ),
        None,
    )


def _level_override(num, ilvl: int):
    from docx.oxml.ns import qn

    return next(
        (
            override
            for override in num.findall(qn("w:lvlOverride"))
            if int(override.get(qn("w:ilvl"), "0")) == ilvl
        ),
        None,
    )


def extract_native_numbering(paragraph, *, ordinal: int = 1) -> NativeNumbering | None:
    """解析段落有效原生编号；损坏引用直接报错。"""
    from docx.oxml.ns import qn

    direct_num_pr = _direct_num_pr(paragraph._element)
    num_pr = direct_num_pr
    if num_pr is None:
        num_pr = _style_num_pr(paragraph)
    if num_pr is None:
        return None
    raw_num_id = _value(num_pr, "w:numId")
    if not raw_num_id:
        return None
    num_id = int(raw_num_id)
    if num_id == 0:
        return None
    ilvl = int(_value(num_pr, "w:ilvl", "0"))
    numbering_root = paragraph.part.numbering_part.element
    num = _find_by_id(numbering_root, "w:num", "w:numId", num_id)
    if num is None:
        raise ValueError(f"WPS_NATIVE_NUMBERING_NUM_MISSING:{num_id}")
    raw_abstract_id = _value(num, "w:abstractNumId")
    if not raw_abstract_id:
        raise ValueError(f"WPS_NATIVE_NUMBERING_ABSTRACT_ID_MISSING:{num_id}")
    abstract_num_id = int(raw_abstract_id)
    abstract_num = _find_by_id(
        numbering_root, "w:abstractNum", "w:abstractNumId", abstract_num_id
    )
    if abstract_num is None:
        raise ValueError(
            f"WPS_NATIVE_NUMBERING_ABSTRACT_MISSING:{abstract_num_id}"
        )
    level = _level_definition(abstract_num, ilvl)
    override = _level_override(num, ilvl)
    override_level = override.find(qn("w:lvl")) if override is not None else None
    effective_level = override_level if override_level is not None else level
    if effective_level is None:
        raise ValueError(
            f"WPS_NATIVE_NUMBERING_LEVEL_MISSING:{abstract_num_id}:{ilvl}"
        )
    start_override_raw = _value(override, "w:startOverride") if override is not None else ""
    start_override = int(start_override_raw) if start_override_raw else None
    start = int(_value(effective_level, "w:start", "1"))
    return NativeNumbering(
        num_id=num_id,
        abstract_num_id=abstract_num_id,
        ilvl=ilvl,
        num_fmt=_value(effective_level, "w:numFmt"),
        lvl_text=_value(effective_level, "w:lvlText"),
        start=start,
        start_override=start_override,
        ordinal=ordinal,
        family_id=f"abstract:{abstract_num_id}",
        num_xml=copy.deepcopy(num),
        abstract_num_xml=copy.deepcopy(abstract_num),
        num_pr_xml=copy.deepcopy(
            direct_num_pr if direct_num_pr is not None else num_pr
        ),
    )


def heading_style_prefix(style_name: str) -> str:
    """传入 Word 样式名称，返回系统内部 heading 样式前缀或空字符串。"""
    normalized = (style_name or "").lower()
    type_id = HEADING_STYLE_TYPES.get(normalized)
    return f"@style_{type_id}" if type_id else ""


def apply_physical_numbering_features(
    features: Any,
    paragraph,
    text: str,
    *,
    debug_logger: Any,
    ordinal: int = 1,
) -> None:
    """把既有 Word 列表和标题样式事实写入段落特征。

    该入口只收口原物理读取顺序：先尝试 ``w:numPr``，再应用 Word 标题
    样式。异常吞吐、日志和前缀覆盖规则均与迁移前一致，不解析或新增最终
    标题类型，也不构造新的编号元数据。
    """
    try:
        native_numbering = extract_native_numbering(paragraph, ordinal=ordinal)
        if native_numbering is not None:
            features.native_numbering = native_numbering
        word_prefix = (
            f"@lvl_{native_numbering.ilvl}"
            if native_numbering is not None and not literal_digit_numbering_present(text)
            else word_list_level_prefix(paragraph._element, text)
        )
        if word_prefix and not features.numbering_prefix:
            features.numbering_prefix = word_prefix
            debug_logger.debug(
                "[多级列表] 已保留原生编号事实 ilvl=%s chars=%s",
                int(word_prefix[5:]),
                len(text),
            )
    except Exception:
        raise

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
