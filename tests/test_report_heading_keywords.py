from __future__ import annotations

from docx import Document

from docxtool.document.recognition import RecognitionConfig, apply_recognition
from docxtool.sdk import recognize_docx
from tests.support.recognition_helpers import _document, _paragraph


def test_report_numbered_headings_use_the_ordinary_numbering_provider() -> None:
    first = _paragraph("一、过去五年工作回顾", "body", 1)
    second = _paragraph("二、今后五年工作安排", "body", 2)
    data = _document(
        _paragraph("政府工作报告", "title", 0, alignment="CENTER", bold_char_ratio=1.0),
        first,
        second,
    )

    apply_recognition(
        data,
        RecognitionConfig(enable_core_candidates=False, enable_legacy_candidates=False),
    )

    assert [first.type_id, second.type_id] == ["heading1", "heading1"]
    assert all(
        item.meta["recognition_provider"].startswith("numbering:")
        for item in (first, second)
    )


def test_report_salutations_use_the_ordinary_structural_provider() -> None:
    first = _paragraph("各位委员、同志们：", "body", 1)
    second = _paragraph("各位同志：", "body", 2)
    data = _document(
        _paragraph("政府工作报告", "title", 0, alignment="CENTER", bold_char_ratio=1.0),
        first,
        second,
    )

    apply_recognition(
        data,
        RecognitionConfig(enable_core_candidates=False, enable_legacy_candidates=False),
    )

    assert [first.type_id, second.type_id] == ["addressing", "addressing"]
    assert all(
        "standalone-addressing" in item.meta["recognition_evidence"]
        for item in (first, second)
    )


def test_annual_review_inline_heading_is_segmented_into_heading1_and_body(tmp_path) -> None:
    source = tmp_path / "report-inline-heading.docx"
    document = Document()
    document.add_paragraph("政府工作报告")
    document.add_paragraph("五年来。我们持续推进重点工作并取得新的明显成效。")
    document.save(source)

    plan = recognize_docx(source, recognition_mode="authoritative", include_text=True)
    blocks = [block for block in plan.blocks if block.physical_paragraph_index == 1]

    assert [block.type_id for block in blocks] == ["heading1", "body"]
    assert [block.recognized_text for block in blocks] == [
        "五年来。", "我们持续推进重点工作并取得新的明显成效。",
    ]


def test_title2_and_glossary_are_mode_independent() -> None:
    title2 = _paragraph("工作安排", "body", 2, bold_char_ratio=1.0)
    glossary_title = _paragraph("名词解释", "body", 3, bold_char_ratio=1.0)
    glossary_item = _paragraph("术语：说明内容", "body", 4)
    data = _document(
        _paragraph("普通公文", "title", 0, alignment="CENTER", bold_char_ratio=1.0),
        _paragraph("正文已经开始并完整说明工作背景和基本情况。", "body", 1),
        title2,
        glossary_title,
        glossary_item,
    )

    apply_recognition(
        data,
        RecognitionConfig(enable_core_candidates=False, enable_legacy_candidates=False),
    )

    assert [title2.type_id, glossary_title.type_id, glossary_item.type_id] == [
        "title2", "glossary_title", "glossary_item",
    ]
    assert title2.meta["recognition_provider"].startswith("body-title:")
    assert glossary_title.meta["recognition_provider"].startswith("glossary:")
    assert glossary_item.meta["recognition_provider"].startswith("glossary:")
