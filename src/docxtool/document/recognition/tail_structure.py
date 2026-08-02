"""Legacy-compatible tail structure recognition state machine.

This module owns the old importer tail decisions for attachments, signature
blocks, dates, and attachment body pages.  It accepts helper callbacks so the
recognition layer can be tested without importing importer or normalization
modules directly.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

from docxtool.document.models import ParagraphFeatures


def detect_legacy_tail_structural_type(
    line: str,
    next_line: str,
    ctx: Any,
    feats: Optional[ParagraphFeatures] = None,
    next_feats: Optional[ParagraphFeatures] = None,
    *,
    is_responsibility_line_func: Callable[[str], bool],
    normalize_responsibility_line_func: Callable[[str], str],
    match_attachment_note_func: Callable[[str], Any],
    can_start_attachment_note_func: Callable[[Any], bool],
    match_attachment_item_func: Callable[[str], Any],
    is_auto_numbered_item_func: Callable[[Optional[ParagraphFeatures]], bool],
    looks_like_sign_org_func: Callable[[str, str, Any], bool],
    normalize_sign_org_func: Callable[[str], str],
    is_sign_date_func: Callable[[str], bool],
    normalize_sign_date_func: Callable[[str], str],
    is_attachment_boundary_func: Callable[[str], bool],
    blocks_independent_sign_date_func: Callable[[Any], bool],
    is_attachment_page_mark_func: Callable[[str], bool],
    normalize_attachment_page_mark_func: Callable[[str], str],
    contains_colon_func: Callable[[str], bool],
    match_numbering_func: Callable[[str], tuple[str | None, str]],
    record_structural_func: Callable[[Any, str, str], None],
) -> tuple[str | None, dict, str, str]:
    """识别尾部固定结构并更新旧上下文。

    传入当前行、下一行、旧 DetectionContext、段落特征和一组形态/规范化
    回调。返回 `(type_id, meta, prefix, fixed_text)`；无法识别时返回
    `(None, {}, "", 原始去空白文本)`。本函数保留旧 importer 行为，
    但不直接依赖 importer、normalizer 或 renderer。
    """
    text = line.strip()
    next_text = next_line.strip() if next_line else ""

    if is_responsibility_line_func(text):
        return "responsibility_line", {"colon_bold": True}, "", normalize_responsibility_line_func(text)

    note_match = match_attachment_note_func(text)
    if note_match and can_start_attachment_note_func(ctx):
        return _detect_attachment_note(
            text,
            next_text,
            ctx,
            next_feats,
            note_match,
            match_attachment_item_func=match_attachment_item_func,
            is_auto_numbered_item_func=is_auto_numbered_item_func,
            record_structural_func=record_structural_func,
        )

    item_match = match_attachment_item_func(text)
    is_auto_item = is_auto_numbered_item_func(feats)
    if ctx.attachment_note_mode and ctx.attachment_note_seen and (item_match or is_auto_item):
        if item_match:
            fixed = re.sub(r"^\s*\d+[.．、]\s*", f"{ctx.attachment_note_next_no}. ", text, count=1)
        else:
            fixed = f"{ctx.attachment_note_next_no}. {text.strip()}"
        ctx.attachment_note_next_no += 1
        record_structural_func(ctx, "attachment_note_item", fixed)
        return "attachment_note_item", {}, "", fixed

    if ctx.last_structural_type in ("body", "attachment_note", "attachment_note_item"):
        if looks_like_sign_org_func(text, next_text, ctx):
            ctx.attachment_note_mode = False
            ctx.signature_seen = True
            fixed = normalize_sign_org_func(text)
            record_structural_func(ctx, "sign_org", fixed)
            return "sign_org", {}, "", fixed

    if ctx.last_structural_type == "sign_org" and is_sign_date_func(text):
        ctx.signature_complete = True
        fixed = normalize_sign_date_func(text)
        record_structural_func(ctx, "sign_date", fixed)
        return "sign_date", {}, "", fixed

    if (
        ctx.has_seen_real_body
        and not ctx.attachment_page_mode
        and is_sign_date_func(text)
        and (not next_text or is_attachment_boundary_func(next_text))
        and not blocks_independent_sign_date_func(ctx)
    ):
        ctx.attachment_note_mode = False
        ctx.signature_seen = True
        ctx.signature_complete = True
        fixed = normalize_sign_date_func(text)
        record_structural_func(ctx, "sign_date", fixed)
        return "sign_date", {}, "", fixed

    if (
        (ctx.attachment_note_seen or ctx.signature_complete or ctx.attachment_page_mode)
        and ctx.last_structural_type in (
            "sign_date",
            "attachment_note",
            "attachment_note_item",
            "attachment_body",
            "attachment_title",
        )
        and is_attachment_page_mark_func(text)
    ):
        ctx.attachment_page_mode = True
        fixed = normalize_attachment_page_mark_func(text)
        record_structural_func(ctx, "attachment_page_mark", fixed)
        return "attachment_page_mark", {}, "", fixed

    if (
        ctx.last_structural_type == "attachment_page_mark"
        and ctx.attachment_page_mode
        and len(text) <= 28
        and not contains_colon_func(text)
    ):
        type_id, _prefix = match_numbering_func(text)
        if not type_id:
            record_structural_func(ctx, "attachment_title", text)
            return "attachment_title", {}, "", text

    if (
        ctx.attachment_page_mode
        and ctx.last_structural_type in ("attachment_title", "attachment_body", "attachment_page_mark")
    ):
        ctx.has_seen_real_body = True

    return None, {}, "", text


def _detect_attachment_note(
    text: str,
    next_text: str,
    ctx: Any,
    next_feats: Optional[ParagraphFeatures],
    note_match: Any,
    *,
    match_attachment_item_func: Callable[[str], Any],
    is_auto_numbered_item_func: Callable[[Optional[ParagraphFeatures]], bool],
    record_structural_func: Callable[[Any, str, str], None],
) -> tuple[str | None, dict, str, str]:
    """识别附件说明首行并更新旧上下文。

    传入附件说明文本、下一行、上下文、下一段特征和附件说明匹配对象。
    返回旧 importer 兼容的结构识别结果；空附件且无续项时返回未识别。
    """
    had_signature_complete = ctx.signature_complete
    body = note_match.group(1).strip()
    first_no = re.match(r"^(\d+)[.．、]\s*", body)
    next_is_item = bool(match_attachment_item_func(next_text)) or is_auto_numbered_item_func(next_feats)

    if not body and not next_is_item:
        return None, {}, "", text

    if first_no and next_is_item:
        is_multi = True
        ctx.attachment_note_next_no = int(first_no.group(1)) + 1
        fixed_text = re.sub(
            r"^\s*附件\s*[:：]\s*(\d+)[.．、]\s*",
            lambda match: f"附件：{match.group(1)}. ",
            text,
            count=1,
        )
    elif first_no and not next_is_item:
        is_multi = False
        ctx.attachment_note_next_no = 1
        body_no = re.sub(r"^\d+[.．、]\s*", "", body, count=1).strip()
        fixed_text = f"附件：{body_no}"
    elif not first_no and next_is_item:
        is_multi = True
        ctx.attachment_note_next_no = 2
        fixed_text = f"附件：1. {body}"
    else:
        is_multi = False
        ctx.attachment_note_next_no = 1
        fixed_text = text

    ctx.attachment_note_seen = True
    ctx.attachment_note_mode = is_multi
    ctx.signature_seen = had_signature_complete
    ctx.signature_complete = had_signature_complete
    record_structural_func(ctx, "attachment_note", fixed_text)
    return "attachment_note", {
        "attachment_single": not is_multi,
        "attachment_multi": is_multi,
    }, "", fixed_text
