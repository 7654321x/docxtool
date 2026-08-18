"""Legacy-compatible recognition metadata enrichment."""

from __future__ import annotations

from typing import Any, Callable


def enrich_legacy_type_metadata(
    text: str,
    type_id: str,
    features: Any,
    ctx: Any,
    meta: dict | None = None,
    *,
    heading_has_inline_body_func: Callable[[str], bool],
    find_numbered_bold_pos_func: Callable[[str], int],
    colon_bold_match_func: Callable[[str], int],
) -> dict:
    """补充旧 importer 兼容识别 meta。

    传入最终类型、段落文本、段落特征、旧识别上下文、已有 meta 和一组
    结构事实回调。返回同一个 meta 字典，用于标记标题正文粘连、正文
    引导句加粗、冒号标签加粗和无缩进等渲染提示。
    """
    metadata = meta if meta is not None else {}

    if (
        type_id == "heading2"
        and getattr(features, "numbered_heading2_colon_inline_body", False)
    ):
        metadata["numbered_heading2_colon_inline_body"] = True
    if (
        type_id == "heading2"
        and getattr(features, "numbered_heading2_period_inline_body", False)
    ):
        metadata["numbered_heading2_period_inline_body"] = True

    if type_id in ("heading1", "heading2") and heading_has_inline_body_func(text):
        metadata["heading_inline_body"] = True

    if type_id == "body":
        numbered_bold = find_numbered_bold_pos_func(text) >= 0
        if numbered_bold:
            metadata["numbered_bold"] = True
        elif getattr(features, "inline_lead_bold", False):
            metadata["inline_lead_bold"] = True

        colon_position = colon_bold_match_func(text)
        if colon_position >= 0:
            metadata["colon_bold"] = True

    if text.endswith(("：", ":")):
        metadata["no_indent"] = True

    return metadata
