"""Body/tail boundary helpers for logical segmentation."""

from __future__ import annotations

from typing import Callable, Sequence


def find_last_body_candidate_index(
    lines: Sequence[str],
    *,
    is_attachment_start_func: Callable[[str], bool],
    is_sign_date_func: Callable[[str], bool],
    is_attachment_item_func: Callable[[str], bool],
    is_attachment_page_mark_func: Callable[[str], bool],
) -> int:
    """查找最后一个可能属于正文或标题的逻辑行序号。

    传入数据是按文档顺序排列的逻辑行文本，以及由 importer 注入的尾部
    结构判断函数。返回值是最后一个正文候选行下标；没有候选时返回 -1。
    本函数只提供尾部边界事实，不判断最终段落类型。
    """
    last_body_index = -1
    for index, text in enumerate(lines):
        line_text = text or ""
        if not line_text:
            continue
        if is_attachment_start_func(line_text):
            continue
        if is_sign_date_func(line_text):
            continue
        if is_attachment_item_func(line_text):
            continue
        if is_attachment_page_mark_func(line_text):
            continue
        last_body_index = index
    return last_body_index
