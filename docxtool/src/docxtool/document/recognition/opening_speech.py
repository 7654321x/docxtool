"""Opening speech title recognition helpers."""

from __future__ import annotations

import re
from typing import Callable

_OPENING_SPEECH_TITLE_RE = re.compile(
    r"^在[\u4e00-\u9fffA-Za-z0-9（）()、，,.·\-\s]{3,70}(?:上)?的?讲话$"
)


def opening_speech_title_text(
    text: str,
    *,
    has_seen_body: bool,
    previous_type_id: str,
    contains_colon_func: Callable[[str], bool],
    match_numbering_func: Callable[[str], tuple[str | None, str]],
) -> str | None:
    """识别文首“在……上的讲话”主标题文本。

    传入数据是当前段文本、正文是否已开始、上一段类型、冒号判断函数和
    编号匹配函数。返回值是可作为主标题的文本；证据不足时返回 `None`。
    该函数只提供候选证据，不写入最终类型。
    """
    value = (text or "").strip()
    if has_seen_body or previous_type_id or contains_colon_func(value):
        return None
    numbered, prefix = match_numbering_func(value)
    if numbered == "heading1" and prefix:
        candidate = value[len(prefix):].strip()
        return candidate if _OPENING_SPEECH_TITLE_RE.fullmatch(candidate) else None
    if numbered:
        return None
    return value if _OPENING_SPEECH_TITLE_RE.fullmatch(value) else None


def strip_inferred_speech_numbering(
    text: str,
    *,
    match_numbering_func: Callable[[str], tuple[str | None, str]],
) -> str:
    """移除文首讲话标题上误推断出的中文一级编号。

    传入数据是原始标题文本和编号匹配函数。返回值是在确认为中文一级
    编号前缀时去掉前缀后的文本；其他情况原样返回去除首尾空白后的文本。
    """
    value = (text or "").strip()
    numbered, prefix = match_numbering_func(value)
    if numbered == "heading1" and prefix:
        return value[len(prefix):].strip()
    return value
