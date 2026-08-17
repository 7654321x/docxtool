"""Date and attachment mark normalization helpers."""

from __future__ import annotations

import re
from typing import Optional


_CN_NUM2 = {
    "零": 0,
    "〇": 0,
    "○": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CN_YEAR_DIGITS = {
    "零": "0",
    "〇": "0",
    "○": "0",
    "一": "1",
    "二": "2",
    "两": "2",
    "三": "3",
    "四": "4",
    "五": "5",
    "六": "6",
    "七": "7",
    "八": "8",
    "九": "9",
}
_ATT_PAGE_RE = re.compile(r"^\s*附件\s*([0-9一二三四五六七八九十百千]*)\s*$")
_SIGN_DATE_RE = re.compile(
    r"^\s*((?:19|20)\d{2}|[零〇○一二两三四五六七八九]{4})\s*年\s*"
    r"([0-9]{1,2}|[零〇一二两三四五六七八九十]{1,3})\s*月\s*"
    r"([0-9]{1,2}|[零〇一二两三四五六七八九十]{1,3})\s*日\s*$"
)
_SIGN_DATE_SUFFIX_RE = re.compile(
    r"((?:19|20)\d{2}|[零〇○一二两三四五六七八九]{4})\s*年\s*"
    r"(?:[0-9]{1,2}|[零〇一二两三四五六七八九十]{1,3})\s*月\s*"
    r"(?:[0-9]{1,2}|[零〇一二两三四五六七八九十]{1,3})\s*日\s*$"
)


def chinese_number_to_int(value: str) -> Optional[int]:
    """把阿拉伯数字或简单中文数字转换为整数。

    传入数据是日期月日或附件序号中的数字文本。返回值是可识别整数；
    无法安全识别时返回 `None`，调用方据此保留原文。
    """
    if not value:
        return None
    text = value.strip()
    if text.isdigit():
        return int(text)
    if text in _CN_NUM2:
        return _CN_NUM2[text]
    total = 0
    current = 0
    used_unit = False
    for character in text:
        if character in _CN_NUM2:
            current = _CN_NUM2[character]
            continue
        unit = {"十": 10, "百": 100, "千": 1000}.get(character)
        if unit is None:
            return None
        used_unit = True
        total += (current or 1) * unit
        current = 0
    return total + current if used_unit else None


def chinese_year_to_int(value: str) -> Optional[int]:
    """把四位阿拉伯年份或四字中文年份转换为整数。

    传入数据是成文日期正则捕获到的年份。返回值是数字年份；不支持的
    年份形态返回 `None`，避免静默改写。
    """
    if not value:
        return None
    text = value.strip()
    if text.isdigit():
        return int(text)
    digits = "".join(_CN_YEAR_DIGITS.get(character, "") for character in text)
    return int(digits) if len(digits) == 4 else None


def is_sign_date_text(text: str) -> bool:
    """判断文本是否是可识别的独立成文日期。

    传入数据是段落文本。返回布尔值，只说明日期形态是否匹配，不决定
    该段最终类型。
    """
    return bool(_SIGN_DATE_RE.match(text or ""))


def find_sign_date_suffix_span(text: str) -> Optional[tuple[int, int]]:
    """Return the exact date suffix range inside a combined signature line."""
    value = text or ""
    match = _SIGN_DATE_SUFFIX_RE.search(value)
    if not match:
        return None
    start, end = match.span()
    while end > start and value[end - 1].isspace():
        end -= 1
    return (start, end)


def is_attachment_page_mark(text: str) -> bool:
    """判断文本是否是附件正文页标识。

    传入数据是段落文本。返回布尔值，只说明是否匹配 `附件` 加可选序号
    的形态，不决定附件区域状态。
    """
    return bool(_ATT_PAGE_RE.match((text or "").strip()))


def normalize_sign_date(text: str) -> str:
    """规范化已识别的成文日期。

    传入数据是最终识别为 `sign_date` 的文本。返回值是安全转换后的
    阿拉伯数字日期；不匹配或无法转换时返回原文。
    """
    match = _SIGN_DATE_RE.match(text or "")
    if not match:
        return text
    year = chinese_year_to_int(match.group(1))
    month = chinese_number_to_int(match.group(2))
    day = chinese_number_to_int(match.group(3))
    return f"{year}年{month}月{day}日" if month and day else text


def normalize_attachment_page_mark(text: str) -> str:
    """规范化已识别的附件正文页标识。

    传入数据是最终识别为 `attachment_page_mark` 的文本。返回值是渲染层
    使用的 `附件 N` 或 `附件`，无法识别序号时不擅自扩展。
    """
    match = _ATT_PAGE_RE.match(text or "")
    if not match:
        return text
    number_text = match.group(1)
    normalized_number = chinese_number_to_int(number_text)
    return f"附件 {normalized_number}" if normalized_number is not None else "附件"
