"""Responsibility-line text normalization helpers."""

from __future__ import annotations

import re

_RESPONSIBILITY_LINE_RE = re.compile(r"^\s*[“”\"'‘’「『]?\s*责\s*任\s*单\s*位\s*[:：]")
_RESPONSIBILITY_LABEL_RE = re.compile(r"\s*责\s*任\s*单\s*位\s*[:：]\s*")
_RESPONSIBILITY_WRAPPER_RE = re.compile(r"^\s*[“”\"'‘’「『]\s*(.*?)\s*[”\"'’」』]?\s*$")


def is_responsibility_line(text: str) -> bool:
    """判断文本是否是责任单位键值行。

    传入数据是一行原始可见文本。返回值为布尔值，只表示文本形态匹配
    `责任单位：` 标签，不决定该段最终类型。
    """
    return bool(_RESPONSIBILITY_LINE_RE.match(text or ""))


def normalize_responsibility_line(text: str) -> str:
    """规范化已识别的责任单位行显示文本。

    传入数据是最终识别为责任单位行的文本。返回值会去除外层引号、
    统一标签为 `责任单位：`，并把重复标签拆为手动换行；不改写具体单位名称。
    """
    unwrapped = _RESPONSIBILITY_WRAPPER_RE.sub(r"\1", text or "")
    normalized = _RESPONSIBILITY_LABEL_RE.sub("责任单位：", unwrapped)
    return re.sub(r"(?<!^)(责任单位：)", r"\n\1", normalized)
