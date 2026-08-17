"""附件说明和附件项的通用形态证据。"""

from __future__ import annotations

import re
from typing import Callable, Optional

ATTACHMENT_NOTE_RE = re.compile(r"^\s*附件\s*[:：]\s*(.*)$")
ATTACHMENT_ITEM_RE = re.compile(r"^\s*\d+[.．、]\s*\S+")


def match_attachment_note(text: str):
    """传入段落文本，返回附件说明正则匹配对象；不匹配返回 None。"""
    return ATTACHMENT_NOTE_RE.match(text or "")


def match_attachment_item(text: str):
    """传入段落文本，返回附件续项正则匹配对象；不匹配返回 None。"""
    return ATTACHMENT_ITEM_RE.match(text or "")


def is_attachment_note_text(text: str) -> bool:
    """传入段落文本，返回是否具备“附件：...”说明形态。"""
    return bool(match_attachment_note(text))


def is_attachment_item_text(text: str) -> bool:
    """传入段落文本，返回是否具备数字附件续项形态。"""
    return bool(match_attachment_item(text))


def is_attachment_boundary_text(
    text: str,
    *,
    is_attachment_page_mark: Optional[Callable[[str], bool]] = None,
) -> bool:
    """传入段落文本和可选附件页标识判断器，返回是否具备附件边界形态。"""
    value = (text or "").strip()
    return bool(
        is_attachment_note_text(value)
        or (is_attachment_page_mark(value) if is_attachment_page_mark else False)
    )


def can_start_attachment_note(
    *,
    has_seen_real_body: bool,
    attachment_page_mode: bool,
    signature_complete: bool,
    last_structural_type: str,
) -> bool:
    """传入文档结构状态，返回当前行是否允许成为附件说明起点。"""
    if not has_seen_real_body:
        return False
    if attachment_page_mode:
        return False
    if signature_complete and last_structural_type != "sign_date":
        return False
    return last_structural_type in (
        "body", "addressing", "heading1", "heading2", "heading3", "heading4",
        "heading1_report", "title2", "glossary_item", "sign_date",
        "attachment_note_item",
    )
