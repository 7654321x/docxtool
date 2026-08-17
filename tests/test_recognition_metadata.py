from __future__ import annotations

from docxtool.document.models import ParagraphFeatures
from docxtool.document.recognition.legacy import DetectionContext
from docxtool.document.recognition.metadata import enrich_legacy_type_metadata


def _enrich(
    text: str,
    type_id: str,
    ctx: DetectionContext | None = None,
    features: ParagraphFeatures | None = None,
    meta: dict | None = None,
) -> dict:
    """测试辅助：传入文本、类型和上下文，返回旧 meta 补充结果。"""
    return enrich_legacy_type_metadata(
        text,
        type_id,
        features or ParagraphFeatures(),
        ctx or DetectionContext(),
        meta,
        heading_has_inline_body_func=lambda value: "。" in value and value.startswith(("一、", "（一）")),
        find_numbered_bold_pos_func=lambda value: 0 if value.startswith(("一是", "一要")) else -1,
        colon_bold_match_func=lambda value: value.find("：") if "：" in value and not value.endswith("：") else -1,
    )


def test_enrich_legacy_type_metadata_marks_heading_inline_body() -> None:
    """meta 补充接收标题正文粘连文本，返回 heading_inline_body 标记。"""
    meta = _enrich("一、标题。正文不少于五字", "heading1")

    assert meta["heading_inline_body"] is True


def test_enrich_legacy_type_metadata_keeps_scheme_heading2_unsplit() -> None:
    """meta 补充接收方案模式二级标题，返回不设置 heading_inline_body。"""
    ctx = DetectionContext(doc_mode="SCHEME")

    meta = _enrich("（一）标题。正文不少于五字", "heading2", ctx)

    assert "heading_inline_body" not in meta


def test_enrich_legacy_type_metadata_marks_body_inline_effects() -> None:
    """meta 补充接收正文文本和特征，返回正文引导句、冒号和无缩进标记。"""
    numbered = _enrich("一是加强统筹。后续正文。", "body")
    inline = _enrich("推动工作。后续正文。", "body", features=ParagraphFeatures(inline_lead_bold=True))
    colon = _enrich("联系人：张三", "body")
    no_indent = _enrich("各单位：", "body")

    assert numbered["numbered_bold"] is True
    assert "inline_lead_bold" not in numbered
    assert inline["inline_lead_bold"] is True
    assert colon["colon_bold"] is True
    assert no_indent["no_indent"] is True


def test_enrich_legacy_type_metadata_keeps_short_report_body_plain() -> None:
    """报告模式不继承源文档的首句粗体作为正文引导句。"""
    ctx = DetectionContext(doc_mode="REPORT", current_level=1)

    meta = _enrich(
        "推动工作。后续正文保持普通格式。",
        "body",
        ctx,
        features=ParagraphFeatures(inline_lead_bold=True),
    )

    assert meta == {}


def test_enrich_legacy_type_metadata_preserves_existing_meta_object() -> None:
    """meta 补充接收已有 meta 字典，返回同一对象并保留既有字段。"""
    existing = {"source": "legacy"}

    meta = _enrich("联系人：张三", "body", meta=existing)

    assert meta is existing
    assert meta["source"] == "legacy"
    assert meta["colon_bold"] is True
