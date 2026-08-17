"""Legacy single-paragraph classifier orchestration."""

from __future__ import annotations

import hashlib
from typing import Any, Callable, List, Tuple

from docxtool.document.models import ParagraphFeatures
from docxtool.document.configuration.models import StyleRule


def classify_legacy_paragraph(
    text: str,
    feats: ParagraphFeatures,
    ctx: Any,
    rules: List[StyleRule],
    *,
    is_object_caption_text_func: Callable[[str], bool],
    opening_speech_title_text_func: Callable[[str, Any], str | None],
    match_style_or_level_func: Callable[[str, ParagraphFeatures], tuple],
    select_scored_type_func: Callable[..., tuple],
    structure_scorers: tuple,
    mode_scorers: tuple,
    fallback_scorers: tuple,
    detect_doc_type_func: Callable[[Any], str],
    flow_allows_func: Callable[[str, Any], bool],
    repair_heading4_colon_func: Callable[[str, str, ParagraphFeatures, Any], str],
    repair_level_func: Callable[[str, ParagraphFeatures, Any], str],
    repair_ocr_heading_func: Callable[..., str],
    looks_like_heading_func: Callable[[str], bool],
    repair_heading2_continuation_func: Callable[..., str],
    enrich_type_metadata_func: Callable[..., dict],
    heading_has_inline_body_func: Callable[[str], bool],
    find_numbered_bold_pos_func: Callable[[str], int],
    colon_bold_match_func: Callable[[str], Any],
    update_context_after_type_func: Callable[..., None],
    logger: Any,
) -> Tuple[str, dict, str]:
    """Run the existing Legacy scorer, Flow, Repair and context sequence."""

    ctx.para_index = feats.paragraph_index
    meta: dict = {}
    prefix = ""
    from_word_structure = False
    score_log = []
    unbound_object_label = is_object_caption_text_func(text)

    if unbound_object_label:
        type_id = "body"
        score_log.append("unbound_object_label:100")
    elif opening_speech_title := opening_speech_title_text_func(text, ctx):
        type_id = "title"
        meta["is_title"] = True
        if opening_speech_title != text.strip():
            meta["strip_inferred_speech_numbering"] = True
        score_log.append("opening_speech_title:100")
    else:
        style_tid, style_prefix = match_style_or_level_func(text, feats)
        if style_tid:
            type_id = style_tid
            prefix = style_prefix
            from_word_structure = True
        else:
            type_id, meta, prefix, score_log = select_scored_type_func(
                text,
                feats,
                ctx,
                structure_scorers=structure_scorers,
                mode_scorers=mode_scorers,
                fallback_scorers=fallback_scorers,
                detect_doc_type_func=detect_doc_type_func,
                flow_allows_func=flow_allows_func,
            )

    type_id = repair_heading4_colon_func(type_id, text, feats, ctx)
    if not from_word_structure:
        type_id = repair_level_func(type_id, feats, ctx)

    repaired_type_id = repair_ocr_heading_func(
        type_id,
        text,
        has_seen_body=ctx.has_seen_body,
        unbound_object_label=unbound_object_label,
        looks_like_heading_func=looks_like_heading_func,
    )
    if repaired_type_id != type_id:
        type_id = repaired_type_id
        logger.debug("[修复] OCR 标题升级 chars=%s", len(text))

    scores_str = " → ".join(score_log) if score_log else "by_style"
    logger.info(
        "[打分] chars=%s text_sha256=%s | %s → %s",
        len(text),
        hashlib.sha256(text.encode("utf-8")).hexdigest()[:12],
        scores_str,
        type_id,
    )

    repaired_type_id = repair_heading2_continuation_func(
        type_id,
        text,
        ctx.prev_type_id,
        meta,
    )
    if repaired_type_id != type_id:
        type_id = repaired_type_id
        logger.debug("[修复] heading2 续行 chars=%s", len(text))

    meta = enrich_type_metadata_func(
        text,
        type_id,
        feats,
        ctx,
        meta,
        heading_has_inline_body_func=heading_has_inline_body_func,
        find_numbered_bold_pos_func=find_numbered_bold_pos_func,
        colon_bold_match_func=colon_bold_match_func,
    )
    update_context_after_type_func(
        ctx,
        type_id,
        text,
        meta,
        detect_doc_type_func=detect_doc_type_func,
    )
    logger.debug("[决策] para=%s → %s meta=%s", ctx.para_index, type_id, meta)
    return type_id, meta, prefix
