from __future__ import annotations

from docxtool.document.models import DocumentData, ParagraphData, ParagraphFeatures
from docxtool.document.normalization.changes import (
    record_applied_normalization_changes,
    record_strict_normalization_suggestions,
)
from docxtool.document.normalization.tail import reorder_attachment_note_before_signature


def _paragraph(text: str, type_id: str) -> ParagraphData:
    """测试辅助：传入文本和类型，返回最小段落数据。"""
    return ParagraphData(text, type_id, text, ParagraphFeatures())


def test_record_strict_normalization_suggestions_records_unapplied_changes() -> None:
    """strict 建议记录接收文档和标点函数，追加未应用的规范化账本。"""
    data = DocumentData(
        paragraphs=[
            _paragraph("甲,乙", "body"),
            _paragraph("单位", "sign_org"),
            _paragraph("2026年1月1日", "sign_date"),
            _paragraph("附件：材料", "attachment_note"),
            _paragraph("一、标题", "heading1"),
            _paragraph("续行标题", "heading1"),
        ],
        filepath="input.docx",
    )

    record_strict_normalization_suggestions(
        data,
        normalize_punctuation_func=lambda text: text.replace(",", "，"),
    )

    assert [change.action for change in data.normalization_changes] == [
        "normalize_punctuation",
        "reorder_tail_structure",
        "merge_sibling_heading",
    ]
    assert [change.applied for change in data.normalization_changes] == [False, False, False]


def test_record_applied_normalization_changes_compares_visible_snapshots() -> None:
    """已应用记录接收规范化前快照，追加 normalize 模式变化账本。"""
    data = DocumentData(
        paragraphs=[
            _paragraph("新正文", "body"),
            _paragraph("新标题", "heading1"),
        ],
        filepath="input.docx",
    )

    record_applied_normalization_changes(
        data,
        before=[
            ("旧正文", "旧正文", "body"),
            ("新标题", "新标题", "heading1"),
        ],
    )

    assert len(data.normalization_changes) == 1
    change = data.normalization_changes[0]
    assert change.paragraph_index == 0
    assert change.action == "normalize_structure"
    assert change.before == "旧正文"
    assert change.after == "新正文"
    assert change.applied is True


def test_reorder_attachment_note_before_signature_keeps_tail_canonical_order() -> None:
    """尾部重排接收段落列表，将落款后的附件说明块移到落款前。"""
    paragraphs = [
        _paragraph("正文", "body"),
        _paragraph("单位", "sign_org"),
        _paragraph("2026年1月1日", "sign_date"),
        _paragraph("附件：材料", "attachment_note"),
        _paragraph("1.清单", "attachment_note_item"),
    ]

    reorder_attachment_note_before_signature(paragraphs)

    assert [paragraph.type_id for paragraph in paragraphs] == [
        "body",
        "attachment_note",
        "attachment_note_item",
        "sign_org",
        "sign_date",
    ]
