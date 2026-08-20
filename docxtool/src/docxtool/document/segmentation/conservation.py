"""Visible-text and source-span conservation checks."""

from __future__ import annotations

from typing import Tuple

from docxtool.document.segmentation.source_locator import visible_character_count


def validate_source_span_partition(source: str, spans: list[Tuple[int, int]]) -> None:
    """校验 source span 是否覆盖所有可见文字且不重叠。

    传入数据是源文本和拆分后的范围列表。函数返回 `None`；发现遗漏、
    重叠或越界时抛出 `ValueError`。
    """
    if not spans:
        return
    previous_end = 0
    for start, end in spans:
        if start < previous_end or start >= end or end > len(source):
            raise ValueError("结构分段范围重叠或越界")
        if visible_character_count(source[previous_end:start]):
            raise ValueError("结构分段遗漏了原始可见文字")
        previous_end = end
    if visible_character_count(source[previous_end:]):
        raise ValueError("结构分段遗漏了原始可见文字")
