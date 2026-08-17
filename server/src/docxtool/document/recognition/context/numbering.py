"""Heading-family ordinal extraction for document context analysis."""

from __future__ import annotations

import re

from ..features import ParagraphFeatures


_CIRCLED_ORDINALS = {char: index for index, char in enumerate("①②③④⑤⑥⑦⑧⑨⑩", 1)}
_CN_DIGITS = {
    "零": 0, "〇": 0, "○": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}


def _cn_ordinal(value: str) -> int | None:
    text = value.strip()
    if not text:
        return None
    if text == "十":
        return 10
    if "十" in text:
        left, _, right = text.partition("十")
        tens = _CN_DIGITS.get(left, 1) if left else 1
        ones = _CN_DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones
    total = 0
    for char in text:
        digit = _CN_DIGITS.get(char)
        if digit is None:
            return None
        total = total * 10 + digit
    return total or None


def _numbering_ordinal(feature: ParagraphFeatures) -> int | None:
    if feature.native_numbering_ordinal is not None:
        return feature.native_numbering_ordinal
    prefix = str(feature.numbering_prefix or "").strip()
    if not prefix or prefix.startswith("@"):
        return None
    if prefix in _CIRCLED_ORDINALS:
        return _CIRCLED_ORDINALS[prefix]
    value = re.sub(r"^[（(]\s*|\s*[）)]$", "", prefix)
    value = re.sub(r"[、.．]+$", "", value).strip()
    if value.isdigit():
        return int(value)
    return _cn_ordinal(value)
