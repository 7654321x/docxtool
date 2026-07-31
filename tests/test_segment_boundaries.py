from __future__ import annotations

from docx import Document
from docx.enum.text import WD_BREAK
from docx.shared import Pt

from docxtool.document.importer import (
    ParagraphFeatures,
    SourceRun,
    _segment_boundary_candidates,
    _split_inline_heading_body_spans,
)
from docxtool.sdk import recognize_docx


def _features_for_visual_boundary(source: str, boundary: int) -> ParagraphFeatures:
    return ParagraphFeatures(
        source_physical_text=source,
        source_run_spans=(
            SourceRun(
                start=0, end=boundary, font_name="SimHei", east_asia_font_name="SimHei",
                ascii_font_name="Arial", font_size_pt=16.0, bold=True, italic=False,
                underline=False, explicit=True, inherited=False, known=True,
                format_sources=("direct_run",),
            ),
            SourceRun(
                start=boundary, end=len(source), font_name="FangSong",
                east_asia_font_name="FangSong", ascii_font_name="Times New Roman",
                font_size_pt=12.0, bold=False, italic=False, underline=False,
                explicit=True, inherited=False, known=True, format_sources=("direct_run",),
            ),
        ),
    )


def test_visual_title_terminator_can_split_without_numbering() -> None:
    source = "关于推进工作的要求。各单位应当结合实际认真执行。"
    boundary = source.index("。") + 1

    candidates = _segment_boundary_candidates(
        source, 0, len(source), _features_for_visual_boundary(source, boundary)
    )
    spans = _split_inline_heading_body_spans(
        source, 0, len(source), _features_for_visual_boundary(source, boundary)
    )

    assert candidates[0].left_type_hint == "title_or_heading"
    assert "VISUAL_TITLE_TERMINATOR" in candidates[0].evidence
    assert [source[start:end] for start, end in spans] == [
        "关于推进工作的要求。", "各单位应当结合实际认真执行。",
    ]


def test_plain_prose_sentence_is_not_split_without_structure_evidence() -> None:
    source = "这是普通正文第一句。后面仍然是同一段普通正文内容。"

    assert _segment_boundary_candidates(source, 0, len(source)) == ()
    assert _split_inline_heading_body_spans(source, 0, len(source)) == [(0, len(source))]


def test_short_label_colon_uses_label_shape_or_visual_transition() -> None:
    source = "责任单位：办公室负责统筹落实相关工作。"
    candidates = _segment_boundary_candidates(source, 0, len(source))

    assert len(candidates) == 1
    assert candidates[0].left_type_hint == "label"
    assert candidates[0].right_type_hint == "content"
    assert "LABEL_SHAPE" in candidates[0].evidence


def test_attachment_note_is_not_split_as_a_short_label() -> None:
    source = "附件：1.基本情况"

    assert _segment_boundary_candidates(source, 0, len(source)) == ()
    assert _split_inline_heading_body_spans(source, 0, len(source)) == [(0, len(source))]


def test_one_physical_paragraph_can_emit_three_ordered_segments(tmp_path) -> None:
    source = tmp_path / "three-segments.docx"
    document = Document()
    paragraph = document.add_paragraph()
    heading = paragraph.add_run("一、总体要求。")
    heading.font.bold = True
    heading.font.size = Pt(16)
    paragraph.add_run("正文第一部分应当独立识别。")
    trailing = paragraph.add_run()
    trailing.add_break(WD_BREAK.LINE)
    trailing.add_text("正文第二部分保持为单独逻辑片段。")
    document.save(source)

    plan = recognize_docx(source, recognition_mode="legacy", include_text=True)
    blocks = [block for block in plan.blocks if block.physical_paragraph_index == 0]

    assert len(blocks) == 3
    assert [block.segment_index for block in blocks] == [0, 1, 2]
    assert {block.segment_count_total for block in blocks} == {3}
    assert all(block.source_locator_status == "confirmed" for block in blocks)
    assert [block.recognized_text for block in blocks] == [
        "一、总体要求。", "正文第一部分应当独立识别。", "正文第二部分保持为单独逻辑片段。",
    ]
