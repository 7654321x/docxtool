"""Soft line-break decisions for physical-to-logical segmentation."""

from __future__ import annotations

from typing import Callable


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
) -> bool:
    """判断一个物理段内的软换行是否应拆成逻辑段。

    传入数据是软换行切出的可见行、下一物理段文本，以及 importer 注入的
    结构证据函数。返回值为布尔值，只决定边界是否成立，不决定最终类型。
    """
    nonempty = [part.strip() for part in parts if part.strip()]
    if len(nonempty) < 2:
        return False
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

    next_visible_line = next(
        (part.strip() for part in (next_text or "").splitlines() if part.strip()),
        "",
    )
    return bool(
        is_sign_date_func(next_visible_line)
        and len(last_line) <= 30
        and not any(mark in last_line for mark in "。；;：:")
    )
