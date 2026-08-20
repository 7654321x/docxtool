"""Soft line-break decisions for physical-to-logical segmentation."""

from __future__ import annotations

import re
from typing import Callable, Tuple

from ..role_shape import has_compact_role_name_shape, has_role_hint
from ..text.front_matter import is_front_title_date_meeting_profile


_HEADER_DATE_LINE_RE = re.compile(r"^[（(]\s*(?:19|20)\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日")
_DISPATCH_NUMBER_LINE_RE = re.compile(
    r"^(?:[\u4e00-\u9fffA-Za-z0-9]{0,20})[〔\[]\d{4}[〕\]]\s*\d+\s*号$"
)


def is_dispatch_number_line(text: str) -> bool:
    """判断软换行中的单行文本是否为结构化发文字号。

    传入数据是一行可见文本。返回值为布尔值，只用于证明文首软换行
    边界；不判断版头是否存在，也不决定最终 `dispatch_number` 类型。
    """
    return bool(_DISPATCH_NUMBER_LINE_RE.fullmatch(re.sub(r"\s+", "", text or "")))


def is_role_name_line(text: str) -> bool:
    """判断软换行中的单行文本是否具备文首职务姓名形态。

    传入数据是一行可见文本。返回值为布尔值，只表示它可作为拆段边界
    的结构事实；不维护具体姓名名单，也不决定最终 `role_name` 类型。
    """
    value = text or ""
    return bool(
        re.fullmatch(r"[\u4e00-\u9fff、，,·]{2,28}\s{2,}[\u4e00-\u9fff·]{2,6}", value)
        or (
            has_role_hint(value)
            and re.search(r"\s{2,}", value)
        )
        or has_compact_role_name_shape(value)
    )


def is_header_role_date_pair(role_line: str, date_line: str) -> bool:
    """判断相邻软换行是否是文首职务姓名和括号日期组合。

    传入数据是相邻两行文本。返回值为布尔值，只用于证明两行应拆成
    独立逻辑结构，不判断标题区最终类型。
    """
    return bool(
        has_role_hint(role_line)
        and _HEADER_DATE_LINE_RE.match(date_line or "")
    )


def is_structural_key_value_line(
    text: str,
    *,
    is_responsibility_line_func: Callable[[str], bool],
    colon_bold_match_func: Callable[[str], int],
) -> bool:
    """判断软换行中的一行文本是否能作为键值结构边界。

    传入数据是一行文本，以及责任单位识别和冒号标签识别回调。返回值
    只表示该行足以支持软换行拆段，不决定最终段落类型或段内格式。
    """
    value = text or ""
    return bool(is_responsibility_line_func(value) or colon_bold_match_func(value) >= 0)


def split_standalone_addressing_spans(
    source: str,
    source_spans: list[Tuple[int, int]],
    *,
    is_standalone_addressing_func: Callable[[str], bool],
) -> list[Tuple[int, int]]:
    """只在独立称呼所在的软换行处建立局部 source 边界。

    传入物理段原文、可见软行范围和已有称呼语义回调。返回合并普通相邻
    软行后的范围；称呼行保持独立，范围之间只允许跳过不可见换行字符。
    """
    if len(source_spans) < 2:
        return list(source_spans)

    addressing_indexes = {
        index
        for index, (start, end) in enumerate(source_spans[1:], start=1)
        if is_standalone_addressing_func(source[start:end].strip())
    }
    if not addressing_indexes:
        return list(source_spans)

    result: list[Tuple[int, int]] = []
    group_start = source_spans[0][0]
    group_end = source_spans[0][1]
    for index, (start, end) in enumerate(source_spans[1:], start=1):
        if index in addressing_indexes:
            if group_start is not None:
                result.append((group_start, group_end))
            result.append((start, end))
            group_start = None
            group_end = end
            continue
        if group_start is None:
            group_start = start
        group_end = end

    if group_start is not None:
        result.append((group_start, group_end))
    return result


def should_split_structural_line_breaks(
    parts: list[str],
    next_text: str,
    *,
    detect_numbering_prefix_func: Callable[[str], str],
    is_dispatch_number_line_func: Callable[[str], bool],
    is_key_value_line_func: Callable[[str], bool],
    is_sign_date_func: Callable[[str], bool],
    is_attachment_boundary_func: Callable[[str], bool],
    is_tail_signature_org_func: Callable[[str], bool],
    is_role_name_line_func: Callable[[str], bool],
    is_header_role_date_pair_func: Callable[[str, str], bool],
    is_standalone_addressing_func: Callable[[str], bool],
) -> bool:
    """判断一个物理段内的软换行是否应拆成逻辑段。

    传入数据是软换行切出的可见行、下一物理段文本，以及 importer 注入的
    结构证据函数。返回值为布尔值，只决定边界是否成立，不决定最终类型。
    """
    nonempty = [part.strip() for part in parts if part.strip()]
    if len(nonempty) < 2:
        return False
    if is_front_title_date_meeting_profile(nonempty):
        return True
    if any(detect_numbering_prefix_func(part) for part in nonempty[1:]):
        return True
    if detect_numbering_prefix_func(nonempty[0]) and len(nonempty) >= 2:
        return True
    if is_dispatch_number_line_func(nonempty[0]) and len(nonempty) >= 2:
        return True
    key_value_lines = sum(1 for part in nonempty if is_key_value_line_func(part))
    if key_value_lines >= 2:
        return True
    if (
        any(is_sign_date_func(part) for part in nonempty[:2])
        and any(is_attachment_boundary_func(part) for part in nonempty[1:])
    ):
        return True

    first_line = nonempty[0]
    last_line = nonempty[-1]
    if (
        len(nonempty) == 2
        and is_tail_signature_org_func(first_line)
        and is_sign_date_func(nonempty[1])
    ):
        return True
    if is_role_name_line_func(last_line):
        return True
    if len(nonempty) >= 2 and is_header_role_date_pair_func(nonempty[0], nonempty[1]):
        return True
    if any(is_standalone_addressing_func(part) for part in nonempty[1:]):
        return True

    next_visible_line = next(
        (part.strip() for part in (next_text or "").splitlines() if part.strip()),
        "",
    )
    return bool(
        is_sign_date_func(next_visible_line)
        and len(last_line) <= 30
        and not any(mark in last_line for mark in "。；;：:")
    )
