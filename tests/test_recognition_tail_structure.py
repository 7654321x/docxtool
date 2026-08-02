from __future__ import annotations

from docxtool.document.importing.numbering import is_auto_numbered_item
from docxtool.document.models import ParagraphFeatures
from docxtool.document.normalization.dates import (
    is_attachment_page_mark,
    is_sign_date_text,
    normalize_attachment_page_mark,
    normalize_sign_date,
)
from docxtool.document.normalization.responsibility import (
    is_responsibility_line,
    normalize_responsibility_line,
)
from docxtool.document.normalization.signature import normalize_sign_org
from docxtool.document.recognition.attachment import (
    can_start_attachment_note,
    is_attachment_boundary_text,
    match_attachment_item,
    match_attachment_note,
)
from docxtool.document.recognition.colon import contains_colon
from docxtool.document.recognition.legacy import DetectionContext
from docxtool.document.recognition.numbering import match_numbering
from docxtool.document.recognition.state import legacy_record_structural
from docxtool.document.recognition.tail_structure import detect_legacy_tail_structural_type


def _record_structural(ctx: DetectionContext, type_id: str, text: str) -> None:
    """测试辅助：传入上下文、类型和文本，模拟 importer 记录结构状态。"""
    legacy_record_structural(ctx, type_id, text)
    ctx.prev_type_id = type_id
    if type_id in ("body", "heading1", "heading2", "heading3", "heading4"):
        ctx.has_seen_body = True
    if type_id == "body":
        ctx.has_seen_real_body = True


def _can_start_note(ctx: DetectionContext) -> bool:
    """测试辅助：传入旧上下文，返回附件说明是否可作为尾部起点。"""
    return can_start_attachment_note(
        has_seen_real_body=ctx.has_seen_real_body,
        attachment_page_mode=ctx.attachment_page_mode,
        signature_complete=ctx.signature_complete,
        last_structural_type=ctx.last_structural_type,
    )


def _is_attachment_boundary(text: str) -> bool:
    """测试辅助：传入文本，返回是否具备附件说明或附件页边界形态。"""
    return is_attachment_boundary_text(text, is_attachment_page_mark=is_attachment_page_mark)


def _looks_like_sign_org(text: str, next_text: str, _ctx: DetectionContext) -> bool:
    """测试辅助：传入当前行和下一行，返回是否可作为落款单位。"""
    return text.endswith(("委员会", "办公室")) and is_sign_date_text(next_text)


def _detect(
    line: str,
    next_line: str,
    ctx: DetectionContext,
    feats: ParagraphFeatures | None = None,
    next_feats: ParagraphFeatures | None = None,
) -> tuple[str | None, dict, str, str]:
    """测试辅助：传入文本、上下文和特征，返回尾部结构状态机结果。"""
    return detect_legacy_tail_structural_type(
        line,
        next_line,
        ctx,
        feats,
        next_feats,
        is_responsibility_line_func=is_responsibility_line,
        normalize_responsibility_line_func=normalize_responsibility_line,
        match_attachment_note_func=match_attachment_note,
        can_start_attachment_note_func=_can_start_note,
        match_attachment_item_func=match_attachment_item,
        is_auto_numbered_item_func=is_auto_numbered_item,
        looks_like_sign_org_func=_looks_like_sign_org,
        normalize_sign_org_func=normalize_sign_org,
        is_sign_date_func=is_sign_date_text,
        normalize_sign_date_func=normalize_sign_date,
        is_attachment_boundary_func=_is_attachment_boundary,
        blocks_independent_sign_date_func=lambda _ctx: False,
        is_attachment_page_mark_func=is_attachment_page_mark,
        normalize_attachment_page_mark_func=normalize_attachment_page_mark,
        contains_colon_func=contains_colon,
        match_numbering_func=match_numbering,
        record_structural_func=_record_structural,
    )


def _tail_context() -> DetectionContext:
    """测试辅助：返回已进入正文尾部的旧识别上下文。"""
    return DetectionContext(
        has_seen_body=True,
        has_seen_real_body=True,
        prev_type_id="body",
        last_structural_type="body",
    )


def test_tail_structure_keeps_responsibility_line_contract() -> None:
    """尾部状态机接收责任单位文本，返回责任单位结构和规范化文本。"""
    type_id, meta, prefix, fixed = _detect("责任单位：办公室", "", _tail_context())

    assert type_id == "responsibility_line"
    assert meta == {"colon_bold": True}
    assert prefix == ""
    assert fixed == "责任单位：办公室"


def test_tail_structure_detects_attachment_note_and_auto_numbered_item() -> None:
    """尾部状态机接收附件说明和 Word 自动编号续项，返回兼容附件类型。"""
    ctx = _tail_context()

    note_type, note_meta, _, note_text = _detect(
        "附件：基本情况",
        "具体情况",
        ctx,
        ParagraphFeatures(paragraph_index=0),
        ParagraphFeatures(numbering_prefix="@lvl_0", paragraph_index=1),
    )
    item_type, _, _, item_text = _detect(
        "具体情况",
        "测试委员会",
        ctx,
        ParagraphFeatures(numbering_prefix="@lvl_0", paragraph_index=1),
        ParagraphFeatures(paragraph_index=2),
    )

    assert note_type == "attachment_note"
    assert note_meta == {"attachment_single": False, "attachment_multi": True}
    assert note_text == "附件：1. 基本情况"
    assert item_type == "attachment_note_item"
    assert item_text == "2. 具体情况"


def test_tail_structure_detects_signature_date_and_attachment_title() -> None:
    """尾部状态机接收落款、日期和附件页行，返回旧兼容结构序列。"""
    ctx = _tail_context()

    sign_org, _, _, org_text = _detect("测试委员会", "2025年十月15日", ctx)
    sign_date, _, _, date_text = _detect("2025年十月15日", "附件1", ctx)
    page_mark, _, _, mark_text = _detect("附件1", "附件标题", ctx)
    title, _, _, title_text = _detect("附件标题", "附件正文。", ctx)

    assert sign_org == "sign_org"
    assert org_text == "测试委员会"
    assert sign_date == "sign_date"
    assert date_text == "2025年10月15日"
    assert page_mark == "attachment_page_mark"
    assert mark_text == "附件 1"
    assert title == "attachment_title"
    assert title_text == "附件标题"


def test_tail_structure_rejects_empty_attachment_without_item() -> None:
    """尾部状态机接收空附件说明且无续项，返回未识别并保留原文本。"""
    type_id, meta, prefix, fixed = _detect("附件：", "普通正文", _tail_context())

    assert type_id is None
    assert meta == {}
    assert prefix == ""
    assert fixed == "附件："
