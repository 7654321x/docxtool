from __future__ import annotations

from docxtool.document.recognition.state import (
    LEGACY_FLOW,
    legacy_flow_allows,
    legacy_record_structural,
    legacy_repair_heading2_continuation,
    legacy_repair_heading4_colon,
    legacy_repair_heading_level,
    legacy_repair_ocr_heading,
    legacy_update_context_after_type,
)
from docxtool.document.recognition.legacy import DetectionContext


def test_legacy_flow_allows_document_opening_candidates() -> None:
    """旧 Flow 判断接收候选和空上一类型，返回文档开头允许的结构。"""
    assert legacy_flow_allows("title", None)
    assert legacy_flow_allows("body", "")
    assert not legacy_flow_allows("sign_date", None)


def test_legacy_flow_keeps_heading1_report_alias() -> None:
    """旧 Flow 判断接收报告标题候选，返回与 heading1 相同的兼容放行结果。"""
    assert legacy_flow_allows("heading1_report", "title")
    assert legacy_flow_allows("heading1_report", "body")
    assert not legacy_flow_allows("heading1_report", "sign_org")


def test_legacy_flow_rejects_disallowed_known_transition() -> None:
    """旧 Flow 判断接收已知上一类型，返回是否拒绝不合法的下一类型。"""
    assert legacy_flow_allows("sign_date", "sign_org")
    assert not legacy_flow_allows("attachment_title", "sign_org")
    assert not legacy_flow_allows("sign_date", "body")


def test_legacy_flow_preserves_unknown_previous_type_fallback() -> None:
    """旧 Flow 判断接收未知上一类型时，返回兼容旧 importer 的默认放行结果。"""
    assert "body" in LEGACY_FLOW
    assert legacy_flow_allows("body", "unknown_legacy_type")


def test_legacy_repair_heading_level_caps_skipped_levels() -> None:
    """标题层级修复接收候选类型和当前层级，返回跳级修正后的类型。"""
    assert legacy_repair_heading_level("heading4", 1) == "heading2"
    assert legacy_repair_heading_level("heading3", 2) == "heading3"
    assert legacy_repair_heading_level("body", 1) == "body"


def test_legacy_repair_heading_level_keeps_report_heading() -> None:
    """标题层级修复接收报告标题类型，返回不参与普通跳级修复的原类型。"""
    assert legacy_repair_heading_level("heading1_report", 0) == "heading1_report"


def test_legacy_repair_heading4_colon_demotes_only_colon_heading4() -> None:
    """四级标题冒号修复接收类型和冒号事实，返回正文或原类型。"""
    assert legacy_repair_heading4_colon("heading4", contains_colon=True) == "body"
    assert legacy_repair_heading4_colon("heading4", contains_colon=False) == "heading4"
    assert legacy_repair_heading4_colon("heading3", contains_colon=True) == "heading3"


def test_legacy_repair_ocr_heading_upgrades_only_front_body_heading_shape() -> None:
    """OCR 标题修复接收类型和上下文事实，只在正文前升级损坏标题。"""
    assert legacy_repair_ocr_heading(
        "body",
        "一，加强领导",
        has_seen_body=False,
        unbound_object_label=False,
        looks_like_heading_func=lambda _text: True,
    ) == "heading1"
    assert legacy_repair_ocr_heading(
        "body",
        "一，加强领导",
        has_seen_body=True,
        unbound_object_label=False,
        looks_like_heading_func=lambda _text: True,
    ) == "body"
    assert legacy_repair_ocr_heading(
        "body",
        "一，加强领导",
        has_seen_body=False,
        unbound_object_label=True,
        looks_like_heading_func=lambda _text: True,
    ) == "body"


def test_legacy_repair_heading2_continuation_marks_meta_without_numbering() -> None:
    """heading2 续行修复接收上一类型和短句，返回 heading2 并写 meta。"""
    meta: dict = {}

    repaired = legacy_repair_heading2_continuation("body", "继续说明。", "heading2", meta)

    assert repaired == "heading2"
    assert meta == {"heading2_cont": True}
    assert legacy_repair_heading2_continuation("body", "继续说明。", "body", {}) == "body"


def test_legacy_record_structural_only_updates_last_structure_fact() -> None:
    """结构记录 helper 接收上下文、类型和文本，只更新最后结构事实。"""
    ctx = DetectionContext(has_seen_body=False, has_seen_real_body=False)

    legacy_record_structural(ctx, "body", "  正文内容  ")

    assert ctx.last_structural_type == "body"
    assert ctx.last_structural_text == "正文内容"
    assert not ctx.has_seen_body
    assert not ctx.has_seen_real_body


def test_legacy_update_context_collects_front_titles_before_body() -> None:
    """上下文推进接收文首标题类型，返回 None 并只缓存标题文本。"""
    ctx = DetectionContext()

    legacy_update_context_after_type(ctx, "title", "测试标题", {}, detect_doc_type_func=lambda _ctx: "NORMAL")

    assert ctx.prev_type_id == "title"
    assert ctx.title_texts == ["测试标题"]
    assert ctx.last_structural_type == "title"
    assert not ctx.has_seen_body


def test_legacy_update_context_starts_body_and_locks_doc_mode() -> None:
    """上下文推进接收正文类型，返回 None 并启动正文区及文种锁定。"""
    ctx = DetectionContext(title_texts=["测试工作报告"])

    legacy_update_context_after_type(ctx, "body", "正文内容", {}, detect_doc_type_func=lambda _ctx: "REPORT")

    assert ctx.prev_type_id == "body"
    assert ctx.has_seen_body
    assert ctx.has_seen_real_body
    assert ctx.doc_mode == "REPORT"
    assert ctx.last_structural_type == "body"


def test_legacy_update_context_tracks_heading_level_and_inline_body() -> None:
    """上下文推进接收标题类型，返回 None 并更新标题层级和结构跟踪。"""
    heading_ctx = DetectionContext()
    inline_ctx = DetectionContext(has_seen_body=True)

    legacy_update_context_after_type(heading_ctx, "heading2", "（一）标题", {}, detect_doc_type_func=lambda _ctx: "NORMAL")
    legacy_update_context_after_type(
        inline_ctx,
        "heading1",
        "一、标题。正文内容",
        {"heading_inline_body": True},
        detect_doc_type_func=lambda _ctx: "NORMAL",
    )

    assert heading_ctx.has_seen_heading
    assert heading_ctx.current_level == 2
    assert heading_ctx.has_seen_body
    assert inline_ctx.last_structural_type == "body"


def test_legacy_update_context_resets_attachment_page_after_sign_date() -> None:
    """上下文推进接收成文日期类型，返回 None 并完成落款日期状态。"""
    ctx = DetectionContext(attachment_page_mode=True)

    legacy_update_context_after_type(ctx, "sign_date", "2026年8月2日", {}, detect_doc_type_func=lambda _ctx: "NORMAL")

    assert ctx.signature_complete
    assert not ctx.attachment_page_mode
    assert ctx.last_structural_type == "sign_date"
