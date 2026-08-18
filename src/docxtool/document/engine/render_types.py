"""Renderer paragraph type mappings and flow groups."""

from __future__ import annotations


TYPE_TO_RULE_INDEX: dict[str, int] = {
    "title": 0,
    "title_cont": 0,
    "embedded_document_title": 0,
    "heading1": 1,
    "heading2": 2,
    "heading3": 3,
    "heading4": 4,
    "body": 5,
    "attachment": 5,
    "responsibility_line": 5,
    "dispatch_number": 5,
    "meeting_meta": 5,
    "meeting_title_meta": 12,
    "addressing": 10,
    "date_line": 11,
    "author_line": 12,
    "role_name": 13,
    "title2": 14,
    "sign_off": 15,
    "glossary_title": 0,
    "glossary_item": 16,
    "attachment_note": 17,
    "attachment_note_item": 18,
    "attachment_page_mark": 19,
    "attachment_title": 20,
    "attachment_body": 21,
    "sign_org": 22,
    "sign_date": 23,
    "number": 6,
    "letter": 7,
    "page_number": 8,
    "superscript": 9,
}

HEAD_TYPES_REQUIRING_GAP = ("title", "title_cont", "date_line", "meeting_title_meta", "author_line", "role_name")
HEAD_GAP_FOLLOW_TYPES = ("body", "attachment_body", "heading1")
BODY_FLOW_TYPES = frozenset({
    "body",
    "heading1",
    "heading2",
    "heading3",
    "heading4",
    "title2",
    "responsibility_line",
    "attachment_note",
    "attachment_note_item",
    "attachment_page_mark",
    "attachment_title",
    "attachment_body",
    "sign_org",
    "sign_date",
})
STRUCTURE_SENSITIVE_TYPES = frozenset({
    "title", "title_cont", "embedded_document_title",
    "heading1", "heading2", "heading3", "heading4",
    "attachment_note", "attachment_note_item", "attachment_page_mark",
    "attachment_title", "attachment_body", "sign_org", "sign_date",
})


def rule_index_for_type(type_id: str) -> int | None:
    """查询样式规则行；传入 type_id，返回行号或 None。"""
    return TYPE_TO_RULE_INDEX.get(type_id)


def is_head_type_requiring_gap(type_id: str) -> bool:
    """判断头部类型是否影响后续留白；传入 type_id，返回布尔值。"""
    return type_id in HEAD_TYPES_REQUIRING_GAP


def is_head_gap_follow_type(type_id: str) -> bool:
    """判断类型是否可跟随头部留白；传入 type_id，返回布尔值。"""
    return type_id in HEAD_GAP_FOLLOW_TYPES


def is_body_flow_type(type_id: str) -> bool:
    """判断类型是否表示进入正文流；传入 type_id，返回布尔值。"""
    return type_id in BODY_FLOW_TYPES


def is_structure_sensitive_type(type_id: str) -> bool:
    """Return whether a render failure would corrupt established structure."""
    return type_id in STRUCTURE_SENSITIVE_TYPES
