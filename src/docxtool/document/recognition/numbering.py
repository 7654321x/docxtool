"""标题编号和 Word 编号事实到识别候选的映射。"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional, Tuple

from docxtool.document.style_config import NB_FIXED, NB_SUFFIXES

HEADING_PATTERNS = (
    (re.compile(r'^[一二三四五六七八九十百]+[、.．]+'), "heading1"),
    (re.compile(r'^[（\(][一二三四五六七八九十百]+[）\)]'), "heading2"),
    (re.compile(r'^\d+[.．]'), "heading3"),
    (re.compile(r'^[（\(]\d+[）\)]'), "heading4"),
)

_NB_RE = re.compile(rf'[一二三四五六七八九十]+(?:{"|".join(NB_SUFFIXES)})')
_NB_FIXED_RE = re.compile(rf'^(?:{"|".join(map(re.escape, NB_FIXED))})') if NB_FIXED else None


def find_numbered_bold_pos(text: str, *, normalize_text: Optional[Callable[[str], str]] = None) -> int:
    """传入段落文本，返回“一是/一要/比如”等引导句首次位置；未命中返回 -1。"""
    value = normalize_text(text) if normalize_text else (text or "")
    if _NB_FIXED_RE:
        fixed_match = _NB_FIXED_RE.search(value)
        if fixed_match:
            return fixed_match.start()
    match = _NB_RE.search(value)
    return match.start() if match else -1


def looks_like_damaged_heading(text: str) -> bool:
    """传入段落文本，返回是否具备 OCR 或标点损坏后的中文标题编号形态。"""
    value = (text or "").strip()
    if len(value) > 30 or re.search(r'[。；：]', value[:10]):
        return False
    if re.match(r'^([一二三四五六七八九十百]+)[，,、\s]', value):
        return True
    if re.match(r'^[）\)][一二三四五六七八九十百]+', value):
        return True
    if re.match(r'^[（\(][一二三四五六七八九十百]+', value) and len(value) <= 15:
        return True
    return False


def match_numbering(
    text: str,
    *,
    normalize_text: Optional[Callable[[str], str]] = None,
    contains_colon: Optional[Callable[[str], bool]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """传入段落文本，返回标题层级和原始编号前缀；未命中返回 `(None, None)`。"""
    value = normalize_text(text) if normalize_text else (text or "")
    colon_check = contains_colon or (lambda candidate: "：" in candidate or ":" in candidate)
    for pattern, type_id in HEADING_PATTERNS:
        match = pattern.match(value)
        if match:
            if type_id == "heading4" and colon_check(value):
                continue
            return type_id, match.group(0)
    return None, None


def match_style_or_level(
    text: str,
    features: Any,
    *,
    normalize_text: Optional[Callable[[str], str]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """传入段落文本和特征，返回 Word 样式/列表推导的标题类型和前缀。"""
    if not features:
        return None, None
    prefix = getattr(features, "numbering_prefix", "") or ""
    if find_numbered_bold_pos(text, normalize_text=normalize_text) == 0:
        return None, None
    if prefix.startswith("@lvl_0") and len(text) > 25 and re.search(r'[、，；]', text):
        return None, None
    if prefix.startswith("@lvl_"):
        try:
            level = int(prefix[5:])
            return f"heading{min(level + 2, 4)}", ""
        except ValueError:
            pass
    if prefix.startswith("@style_"):
        return prefix[7:], ""
    return None, None
