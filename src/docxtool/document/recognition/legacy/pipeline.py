"""Legacy paragraph-stream context advancement."""

from __future__ import annotations

from typing import Any, Callable


def advance_legacy_context(
    ctx: Any,
    type_id: str,
    text: str,
    meta: dict,
    *,
    record_structural_func: Callable[[Any, str, str], None],
) -> str:
    """Apply the importer Legacy heading cap and structural state updates."""

    if type_id.startswith("heading") and type_id != "heading1_report":
        level = int(type_id[-1])
        previous_level = ctx.current_level
        if level == getattr(ctx, "_last_detected_lvl", 0):
            capped = previous_level
        else:
            capped = min(level, previous_level + 1)
        if capped != level:
            type_id = "heading{0}".format(capped)
        ctx.current_level = capped
        ctx._last_detected_lvl = level
    elif type_id == "heading1_report":
        ctx.current_level = 1
    ctx.prev_type_id = type_id

    if type_id in ("body", "addressing", "responsibility_line"):
        ctx.has_seen_real_body = True
        record_structural_func(ctx, "body", text)
    elif type_id.startswith("heading") or type_id in ("title", "title2"):
        if meta.get("heading_inline_body"):
            ctx.has_seen_real_body = True
            record_structural_func(ctx, "body", text)
        else:
            record_structural_func(ctx, type_id, text)
    else:
        record_structural_func(ctx, type_id, text)
    if type_id == "sign_date":
        ctx.signature_complete = True
        ctx.attachment_page_mode = False
    return type_id
