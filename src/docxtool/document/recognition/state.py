"""旧 importer 兼容识别链路的状态流约束。"""

from __future__ import annotations

LEGACY_FLOW: dict[str | None, tuple[str, ...]] = {
    None: ("title", "addressing", "heading1", "body"),
    "title": ("title_cont", "date_line", "author_line", "role_name", "addressing", "heading1"),
    "title_cont": ("title_cont", "date_line", "author_line", "role_name", "addressing", "heading1", "title2"),
    "date_line": ("author_line", "addressing", "heading1", "heading2", "title2", "body"),
    "author_line": ("addressing", "heading1", "heading2", "title2", "body"),
    "role_name": ("date_line", "addressing", "heading1", "heading2", "title2", "body"),
    "heading1": ("heading1", "heading2", "heading3", "body", "addressing", "title2"),
    "heading1_report": ("heading2", "heading3", "body", "addressing", "title2"),
    "heading2": ("heading1", "heading2", "heading3", "heading4", "body", "addressing", "title2", "glossary_title"),
    "heading3": ("heading1", "heading2", "heading3", "heading4", "body", "addressing", "title2", "glossary_title"),
    "heading4": ("heading1", "heading2", "heading3", "heading4", "body", "addressing", "title2", "glossary_title"),
    "addressing": ("heading1", "heading2", "title2", "body"),
    "title2": ("heading1", "heading2", "body", "addressing", "title2"),
    "glossary_title": ("glossary_item", "body"),
    "glossary_item": ("glossary_item", "body", "title2"),
    "body": (
        "heading1",
        "heading2",
        "heading3",
        "heading4",
        "title2",
        "glossary_title",
        "addressing",
        "body",
        "attachment_note",
        "sign_org",
    ),
    "attachment_note": ("attachment_note_item", "sign_org"),
    "attachment_note_item": ("attachment_note_item", "sign_org"),
    "attachment_page_mark": ("attachment_title",),
    "attachment_title": ("attachment_body",),
    "attachment_body": ("attachment_body", "attachment_page_mark", "heading1", "heading2", "heading3", "heading4"),
    "sign_org": ("sign_date",),
    "sign_date": ("attachment_page_mark", "body"),
}


def legacy_flow_allows(candidate: str, previous_type: str | None) -> bool:
    """传入候选类型和上一段类型，返回旧 importer 状态机是否允许该候选。"""
    previous = previous_type if previous_type else None
    allowed = LEGACY_FLOW.get(previous, ())
    if not allowed:
        return True
    if candidate in allowed:
        return True
    return candidate in ("heading1", "heading1_report") and "heading1" in allowed


def legacy_repair_heading_level(type_id: str, current_level: int) -> str:
    """传入候选类型和当前标题层级，返回旧 importer 跳级修复后的类型。"""
    if not type_id.startswith("heading"):
        return type_id
    if type_id == "heading1_report":
        return type_id
    level = int(type_id[-1])
    expected = current_level + 1
    if level > expected:
        return f"heading{expected}" if expected <= 4 else type_id
    return type_id


def legacy_repair_heading4_colon(type_id: str, *, contains_colon: bool) -> str:
    """传入候选类型和冒号事实，返回旧 importer heading4 冒号修复后的类型。"""
    if type_id == "heading4" and contains_colon:
        return "body"
    return type_id
