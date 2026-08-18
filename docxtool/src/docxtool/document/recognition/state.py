"""旧 importer 兼容识别链路的状态流约束。"""

from __future__ import annotations

from typing import Any

LEGACY_FLOW: dict[str | None, tuple[str, ...]] = {
    None: ("title", "addressing", "heading1", "body"),
    "title": ("title_cont", "date_line", "meeting_title_meta", "author_line", "role_name", "addressing", "heading1"),
    "title_cont": ("title_cont", "date_line", "meeting_title_meta", "author_line", "role_name", "addressing", "heading1", "title2"),
    "meeting_title_meta": ("meeting_title_meta", "addressing", "heading1", "heading2", "title2", "body"),
    "date_line": ("author_line", "addressing", "heading1", "heading2", "title2", "body"),
    "author_line": ("addressing", "heading1", "heading2", "title2", "body"),
    "role_name": ("date_line", "addressing", "heading1", "heading2", "title2", "body"),
    "heading1": ("heading1", "heading2", "heading3", "body", "addressing", "title2"),
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
    return False


def legacy_repair_heading_level(type_id: str, current_level: int) -> str:
    """传入候选类型和当前标题层级，返回旧 importer 跳级修复后的类型。"""
    if not type_id.startswith("heading"):
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


def legacy_repair_ocr_heading(
    type_id: str,
    text: str,
    *,
    has_seen_body: bool,
    unbound_object_label: bool,
    looks_like_heading_func: Any,
) -> str:
    """按旧 OCR 容错规则修复损坏一级标题。

    传入当前候选类型、文本、正文是否开始、是否未绑定对象标签和损坏
    标题判断回调。返回修复后的类型；仅在正文开始前、当前为正文且
    文本像损坏中文编号标题时升级为 `heading1`。
    """
    if (
        type_id == "body"
        and not unbound_object_label
        and not has_seen_body
        and looks_like_heading_func(text)
    ):
        return "heading1"
    return type_id


def legacy_repair_heading2_continuation(
    type_id: str,
    text: str,
    previous_type: str | None,
    meta: dict,
) -> str:
    """按旧规则修复缺编号的二级标题续行。

    传入当前候选类型、文本、上一类型和 meta 字典。返回修复后的类型；
    当前为正文、上一段为 `heading2`、短句以句号结束时改为 `heading2`，
    并在 meta 中写入 `heading2_cont=True` 表示不自动编号。
    """
    if type_id == "body" and previous_type == "heading2" and len(text) <= 30 and text.endswith("。"):
        meta["heading2_cont"] = True
        return "heading2"
    return type_id


def legacy_record_structural(ctx: Any, type_id: str, text: str) -> None:
    """记录旧识别上下文最后一个结构类型和文本。

    传入数据是旧 DetectionContext 兼容对象、最终结构类型和对应文本。
    返回 None；只更新 `last_structural_type` 和 `last_structural_text`，
    不推进正文开始、附件、落款或标题层级状态。
    """
    ctx.last_structural_type = type_id
    ctx.last_structural_text = (text or "").strip()


def legacy_update_context_after_type(
    ctx: Any,
    type_id: str,
    text: str,
    meta: dict | None,
) -> None:
    """按旧 importer 规则推进识别上下文。

    传入旧 DetectionContext 兼容对象、最终类型、文本、meta 和文种检测
    回调。返回 None；更新上一类型、正文开始、标题层级、标题文本缓存、
    glossary 状态以及尾部结构跟踪，不重新打分或改写最终类型。
    """
    metadata = meta or {}
    ctx.prev_type_id = type_id

    if type_id in ("body", "addressing", "responsibility_line"):
        ctx.has_seen_real_body = True
        legacy_record_structural(ctx, "body", text)
    elif type_id in (
        "attachment_note",
        "attachment_note_item",
        "attachment_page_mark",
        "attachment_title",
        "attachment_body",
        "sign_org",
        "sign_date",
    ):
        legacy_record_structural(ctx, type_id, text)
    elif type_id.startswith("heading") or type_id in ("title", "title2"):
        legacy_record_structural(ctx, "body" if metadata.get("heading_inline_body") else type_id, text)

    if type_id == "sign_date":
        ctx.signature_complete = True
        ctx.attachment_page_mode = False

    if not ctx.has_seen_body and type_id in ("title", "title_cont"):
        ctx.title_texts.append(text)

    if type_id.startswith("heading"):
        ctx.has_seen_heading = True
        if not ctx.has_seen_body:
            ctx.has_seen_body = True
        ctx.current_level = int(type_id[-1])
    elif type_id == "title2":
        ctx.has_seen_heading = True
    elif type_id == "glossary_title":
        ctx.glossary_mode = True
        ctx.has_seen_body = True
    elif type_id in ("title", "title_cont", "date_line", "meeting_title_meta", "author_line", "role_name"):
        return
    elif type_id in ("body", "addressing", "responsibility_line"):
        if not ctx.has_seen_body:
            ctx.has_seen_body = True
