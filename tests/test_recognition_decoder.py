from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from docx import Document
from docxtool.document.engine import export_doc
from docxtool.document.recognition import (
    DocumentMode,
    ParagraphType,
    RecognitionConfig,
    apply_recognition,
    diagnostics_to_json,
    extract_blocks,
    extract_features,
    resolve_render_mapping,
)
from docxtool.document.recognition.features import BlockKind
from docxtool.document.style_config import PageSettings, StyleRule


def _paragraph(text, type_id="body", index=0, **meta):
    return SimpleNamespace(
        text=text,
        original_text=text,
        type_id=type_id,
        features=SimpleNamespace(paragraph_index=index, alignment=meta.pop("alignment", ""), style_name=meta.pop("style_name", ""), bold=False, font_size_pt=None),
        meta=meta,
    )


def _document(*paragraphs, mode="NORMAL"):
    return SimpleNamespace(paragraphs=list(paragraphs), doc_mode=mode)


def _rules():
    return [StyleRule.default_for_row(index) for index in range(10)]


def test_dispatch_number_vetoes_title_continuation():
    data = _document(
        _paragraph("关于推进公共服务工作的通知", "title", 0),
        _paragraph("内政发〔2026〕23号", "title_cont", 1),
    )

    apply_recognition(data)

    assert data.paragraphs[1].type_id == "dispatch_number"
    assert data.paragraphs[1].meta["recognition_provider"].startswith("structural:")


def test_numbered_meeting_label_is_metadata_not_heading():
    data = _document(
        _paragraph("2026年第一次党委会会议纪要", "title", 0),
        _paragraph("（一）缺席：无", "heading2", 1),
    )

    apply_recognition(data)

    assert data.doc_mode == "MEETING_MINUTES"
    assert data.paragraphs[1].type_id == "meeting_meta"


def test_embedded_document_title_after_signature_note():
    data = _document(
        _paragraph("2026年7月21日", "sign_date", 0),
        _paragraph("（本文有删减）", "body", 1),
        _paragraph("公共服务提升规划", "body", 2),
        _paragraph("第一章 总则", "heading1", 3),
    )

    apply_recognition(data)

    assert data.paragraphs[2].type_id == "embedded_document_title"
    trace = data.recognition_diagnostics["candidate_trace"][2]
    local_best = max(trace["candidates"], key=lambda item: item["score"])["type"]
    assert local_best != "embedded_document_title"


def test_report_bold_metadata_removed_outside_report_mode():
    paragraph = _paragraph("这是正文。后续内容。", "body", 0, report_first_sentence_bold=True)
    data = _document(paragraph, mode="NORMAL")

    apply_recognition(data)

    assert "report_first_sentence_bold" not in paragraph.meta


def test_shared_features_preserve_raw_text_and_extract_numbered_key_value():
    paragraph = _paragraph("（一）缺  席：无", "heading2", 0)
    data = _document(paragraph)
    block = extract_blocks(data)[0]

    features = extract_features(block)

    assert features.raw_text == "（一）缺  席：无"
    assert features.normalized_text == "(一)缺 席:无"
    assert features.compact_text == "(一)缺席:无"
    assert features.optional_numbering_before_label == "(一)"
    assert features.key_value_label == "缺席"


def test_non_text_blocks_remain_in_original_sequence():
    table = _paragraph("", "__table__", 1)
    image = _paragraph("", "__image__", 2)
    data = _document(_paragraph("标题", "title", 0), table, image, _paragraph("正文", "body", 3))

    blocks = extract_blocks(data)

    assert [block.kind for block in blocks] == [BlockKind.PARAGRAPH, BlockKind.TABLE, BlockKind.IMAGE, BlockKind.PARAGRAPH]
    assert blocks[1].paragraph_index is None
    assert blocks[1].table_index == 0


def test_mode_and_result_are_deterministic_and_idempotent():
    data = _document(
        _paragraph("2026年第一次党委会会议纪要", "title", 0),
        _paragraph("出席：甲、乙", "body", 1),
        _paragraph("（一）缺席：无", "heading2", 2),
    )

    apply_recognition(data)
    first = [(item.type_id, dict(item.meta)) for item in data.paragraphs]
    first_diagnostics = dict(data.recognition_diagnostics)
    apply_recognition(data)

    assert data.doc_mode == "MEETING_MINUTES"
    assert first == [(item.type_id, dict(item.meta)) for item in data.paragraphs]
    assert first_diagnostics == data.recognition_diagnostics
    assert data.recognition_diagnostics["validation"]["ok"] is True


def test_public_model_vocabulary_is_stable():
    assert DocumentMode.MEETING_MINUTES.value == "meeting_minutes"
    assert ParagraphType.DISPATCH_NUMBER.value == "dispatch_number"


def test_diagnostics_json_is_safe_and_configurable():
    data = _document(_paragraph("标题", "title", 0), _paragraph("正文", "body", 1))
    apply_recognition(data)
    serialized = diagnostics_to_json(data.recognition_diagnostics)

    assert "标题" not in serialized
    assert '"beam_width": 12' in serialized
    assert data.recognition_diagnostics["structure_tree"] in {"built", "unavailable"}


def test_dispatch_has_multiple_candidates_before_hard_veto():
    data = _document(
        _paragraph("关于推进公共服务工作的通知", "title", 0),
        _paragraph("内政发〔2026〕23号", "title_cont", 1),
    )
    apply_recognition(data)

    trace = data.recognition_diagnostics["candidate_trace"][1]
    assert trace["candidate_count"] >= 2
    candidate_types = [item["type"] for item in trace["candidates"]]
    assert "dispatch_number" in candidate_types
    assert "title_continuation" in candidate_types


def test_previous_title_changes_ambiguous_centered_line_decision():
    after_title = _document(
        _paragraph("主标题", "title", 0),
        _paragraph("补充说明", "body", 1, alignment="CENTER"),
    )
    after_body = _document(
        _paragraph("正文开头", "body", 0),
        _paragraph("补充说明", "body", 1, alignment="CENTER"),
    )

    apply_recognition(after_title)
    apply_recognition(after_body)

    assert after_title.paragraphs[1].meta["recognition_type"] == "title_continuation"
    assert after_body.paragraphs[1].meta["recognition_type"] == "body"


def test_table_boundary_blocks_title_continuation():
    data = _document(
        _paragraph("主标题", "title", 0),
        _paragraph("", "__table__", 1),
        _paragraph("表后说明", "body", 2, alignment="CENTER"),
    )

    apply_recognition(data)

    assert data.recognition_diagnostics["candidate_trace"][1]["boundary_before"] is True
    assert data.paragraphs[2].meta["recognition_type"] != "title_continuation"


def test_wrong_legacy_and_docxtool_style_do_not_override_dispatch():
    paragraph = _paragraph("国发〔2026〕23号", "title", 0, style_name="DCT-Title", legacy_type_id="title")
    data = _document(paragraph)

    apply_recognition(data)

    assert paragraph.type_id == "dispatch_number"
    assert paragraph.meta["legacy_type_id"]["value"] == "title"


def test_wrong_heading_legacy_does_not_override_meeting_metadata():
    paragraph = _paragraph("（一）缺席：李四", "heading2", 1, style_name="DCT-Heading2", legacy_type_id="heading2")
    data = _document(_paragraph("党委会会议纪要", "title", 0), paragraph)

    apply_recognition(data)

    assert paragraph.type_id == "meeting_meta"


def test_every_paragraph_type_has_explicit_render_mapping():
    for paragraph_type in ParagraphType:
        type_id, rule_index, style_id = resolve_render_mapping(paragraph_type)
        assert type_id
        if paragraph_type is ParagraphType.UNKNOWN:
            assert rule_index is None and style_id is None
        else:
            assert isinstance(rule_index, int)
            assert style_id and style_id.startswith("DCT-")


def test_real_docx_round_trip_preserves_semantics_and_layout(tmp_path):
    source = tmp_path / "source.docx"
    first = tmp_path / "first.docx"
    second = tmp_path / "second.docx"
    document = Document()
    document.add_paragraph("国务院关于印发规划的通知")
    document.add_paragraph("国发〔2026〕23号")
    document.add_paragraph("各有关单位：")
    document.add_paragraph("正文内容。")
    document.add_paragraph("国务院")
    document.add_paragraph("2026年3月18日")
    document.add_paragraph("（本文有删减）")
    document.add_paragraph("公共服务提升规划")
    document.add_paragraph("第一章 总则")
    document.save(source)

    importer = __import__("docxtool.document.importer", fromlist=["DocxImporter"]).DocxImporter()
    first_data = importer.load(str(source), _rules())
    export_doc(first_data, _rules(), PageSettings(), str(first))
    second_data = importer.load(str(first), _rules())
    export_doc(second_data, _rules(), PageSettings(), str(second))
    third_data = importer.load(str(second), _rules())

    def signature(data):
        return [(item.type_id, item.text, item.meta.get("recognition_type"), item.meta.get("recognition_section")) for item in data.paragraphs]

    assert signature(second_data) == signature(third_data)
    assert [item.type_id for item in second_data.paragraphs].count("dispatch_number") == 1
    assert [item.type_id for item in second_data.paragraphs].count("embedded_document_title") == 1
    assert len(second_data.paragraphs) == len(third_data.paragraphs)
    assert second_data.recognition_diagnostics["validation"]["ok"] is True


def test_recognition_config_rejects_invalid_values():
    for kwargs in (
        {"beam_width": 1},
        {"max_candidates_per_paragraph": 1},
        {"legacy_score": 1.1},
        {"text_preview_length": -1},
        {"unknown_render_type": "silent"},
    ):
        try:
            RecognitionConfig(**kwargs)
        except ValueError:
            continue
        raise AssertionError(f"invalid config accepted: {kwargs}")


def test_disabling_diagnostics_does_not_change_decisions():
    enabled = _document(_paragraph("主标题", "title", 0), _paragraph("国发〔2026〕23号", "title_cont", 1))
    disabled = _document(_paragraph("主标题", "title", 0), _paragraph("国发〔2026〕23号", "title_cont", 1))

    apply_recognition(enabled, RecognitionConfig(enable_diagnostics=True))
    apply_recognition(disabled, RecognitionConfig(enable_diagnostics=False))

    assert [item.type_id for item in enabled.paragraphs] == [item.type_id for item in disabled.paragraphs]
    assert enabled.recognition_diagnostics["candidate_trace"]
    assert disabled.recognition_diagnostics["candidate_trace"] == []
    assert disabled.recognition_diagnostics["engine_version"] == "3.0"
    assert disabled.recognition_diagnostics["schema_version"] == "1.0"


def test_empty_and_table_only_documents_do_not_create_fake_paragraphs():
    empty = _document()
    table_only = _document(_paragraph("", "__table__", 0))

    apply_recognition(empty)
    apply_recognition(table_only)

    assert empty.recognition_diagnostics["paragraphs"] == []
    assert table_only.recognition_diagnostics["paragraphs"] == []
    assert table_only.recognition_diagnostics["blocks"][0]["kind"] == "table"


def test_long_and_unusual_unicode_text_is_bounded_and_preserved():
    raw = "Ａ：" + "甲\u00a0\u200b" * 25000
    paragraph = _paragraph(raw, "body", 0)
    data = _document(paragraph)

    apply_recognition(data, RecognitionConfig(text_preview_length=10))

    assert paragraph.original_text == raw
    assert len(data.recognition_diagnostics["paragraphs"][0]["text_preview"]) == 10
    assert len(data.recognition_diagnostics["candidate_trace"]) == 1


def test_incomplete_heading_level_is_diagnosed_without_text_loss():
    paragraph = _paragraph("（三）直接出现", "heading2", 0)
    data = _document(paragraph)

    apply_recognition(data)

    assert paragraph.original_text == "（三）直接出现"
    assert data.recognition_diagnostics["paragraphs"][0]["candidate_count"] >= 1


def test_dispatch_variants_are_stable_after_nfkc():
    for index, text in enumerate(("国发〔2026〕23号", "市府[2027]1号", "ＡＢ〔２０２８〕１２３号", "国发〔 2026 〕 23 号")):
        paragraph = _paragraph(text, "title_cont", index)
        data = _document(paragraph)
        apply_recognition(data)
        assert paragraph.type_id == "dispatch_number", text


def test_key_value_and_source_variants_do_not_promote_numbering():
    for index, text in enumerate(("（一）缺席：李四", "（二）出 席:张三", "来源：国家卫生健康委员会")):
        paragraph = _paragraph(text, "heading2", index)
        data = _document(_paragraph("党委会会议纪要", "title", 0), paragraph)
        apply_recognition(data)
        if text.startswith("来源"):
            assert paragraph.type_id == "note"
        else:
            assert paragraph.type_id == "meeting_meta"


def test_review_flags_and_safe_summary_do_not_change_final_types():
    clear = _document(_paragraph("国发〔2026〕23号", "title_cont", 0))
    ambiguous = _document(_paragraph("补充说明", "body", 0, alignment="CENTER"))

    apply_recognition(clear)
    apply_recognition(ambiguous, RecognitionConfig(review_low_score=0.9))

    clear_diagnostic = clear.recognition_diagnostics["paragraphs"][0]
    ambiguous_diagnostic = ambiguous.recognition_diagnostics["paragraphs"][0]
    assert clear_diagnostic["needs_review"] is False
    assert ambiguous_diagnostic["needs_review"] is True
    assert ambiguous_diagnostic["review_reasons"]
    assert clear.paragraphs[0].type_id == "dispatch_number"
    summary = ambiguous.recognition_diagnostics["summary"]
    assert summary["needs_review_count"] == 1
    assert "补充说明" not in diagnostics_to_json(ambiguous.recognition_diagnostics)


def test_same_input_is_thread_safe_across_twenty_independent_documents():
    def recognize(_):
        data = _document(
            _paragraph("2026年第一次党委会会议纪要", "title", 0),
            _paragraph("出席：甲、乙", "body", 1),
            _paragraph("（一）缺席：无", "heading2", 2),
        )
        apply_recognition(data)
        return (
            data.doc_mode,
            tuple((item.type_id, item.meta["recognition_section"]) for item in data.paragraphs),
            data.recognition_diagnostics["summary"],
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(recognize, range(20)))

    assert len(results) == 20
    assert all(result == results[0] for result in results)
