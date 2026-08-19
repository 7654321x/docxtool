"""Tests split from test_recognition_decoder.py by responsibility."""


import pytest
from docxtool.document.recognition import (
    DocumentMode,
    ParagraphType,
    RecognitionConfig,
    apply_recognition,
    diagnostics_to_json,
    extract_blocks,
    extract_features,
)
from docxtool.document.recognition.features import BlockKind
from docxtool.document.recognition.candidates import Candidate
from docxtool.document.recognition.decoding.pipeline import (
    apply_recognition as apply_recognition_with_providers,
)



from tests.support.recognition_helpers import _document, _paragraph


def test_dispatch_number_vetoes_title_continuation():
    data = _document(
        _paragraph("关于推进公共服务工作的通知", "title", 0),
        _paragraph("内政发〔2026〕23号", "title_cont", 1),
    )

    apply_recognition(data)

    assert data.paragraphs[1].type_id == "dispatch_number"
    assert data.paragraphs[1].meta["recognition_provider"].startswith("structural:")

def test_numbered_meeting_label_is_heading_with_inline_body():
    data = _document(
        _paragraph("2026年第一次党委会会议纪要", "title", 0),
        _paragraph("（一）缺席：无", "heading2", 1),
    )

    apply_recognition(data)

    assert data.doc_mode == "MEETING_MINUTES"
    assert data.paragraphs[1].type_id == "heading2"
    assert data.paragraphs[1].meta["numbered_heading2_colon_inline_body"] is True

@pytest.mark.parametrize(
    "text",
    (
        "（一）出席人员：正文内容",
        "（二）工作安排：具体内容",
        "（三）会议时间：11:00",
        "（四）比例说明：1:2，具体要求如下",
        "（五）英文冒号:正文内容",
    ),
)
def test_numbered_heading2_colon_inline_body_is_shape_based(text):
    paragraph = _paragraph(text, "body", 0)
    data = _document(paragraph)

    apply_recognition(data)

    assert paragraph.type_id == "heading2"
    assert paragraph.meta["numbered_heading2_colon_inline_body"] is True
    assert "numbered-heading2-colon-inline-body" in paragraph.meta[
        "recognition_evidence"
    ]

def test_numbered_heading2_colon_requires_nonempty_body():
    paragraph = _paragraph("（一）标题：", "body", 0)
    data = _document(paragraph)

    apply_recognition(data)

    assert paragraph.meta.get("numbered_heading2_colon_inline_body") is not True

def test_unnumbered_meeting_metadata_keeps_existing_type():
    paragraph = _paragraph("出席：甲、乙", "body", 1)
    data = _document(
        _paragraph("2026年第一次党委会会议纪要", "title", 0),
        paragraph,
    )

    apply_recognition(data)

    assert paragraph.type_id == "meeting_meta"
    assert paragraph.meta.get("numbered_heading2_colon_inline_body") is not True
    trace = data.recognition_diagnostics["candidate_trace"][1]
    meeting = next(item for item in trace["candidates"] if item["type"] == "meeting_meta")
    assert meeting["hard"] is False


def test_meeting_label_competes_with_key_value_in_normal_document() -> None:
    time = _paragraph("时间：8月20日上午", "body", 1)
    place = _paragraph("地点：第一会议室", "body", 2)
    data = _document(
        _paragraph("活动安排", "title", 0),
        time,
        place,
    )

    apply_recognition(data)

    assert data.doc_mode != "MEETING_MINUTES"
    assert [time.type_id, place.type_id] == ["responsibility_line", "responsibility_line"]
    for index in (1, 2):
        candidate_types = {
            item["type"]
            for item in data.recognition_diagnostics["candidate_trace"][index]["candidates"]
        }
        assert {"key_value", "meeting_meta"} <= candidate_types


def test_meeting_mode_prior_selects_meeting_meta_from_competing_candidates() -> None:
    time = _paragraph("时间：8月20日上午", "body", 1)
    place = _paragraph("地点：第一会议室", "body", 2)
    host = _paragraph("主持：张某", "body", 3)
    data = _document(
        _paragraph("2026年第一次党委会会议纪要", "title", 0),
        time,
        place,
        host,
    )

    apply_recognition(data)

    assert data.doc_mode == "MEETING_MINUTES"
    assert [time.type_id, place.type_id, host.type_id] == [
        "meeting_meta", "meeting_meta", "meeting_meta",
    ]
    for index in (1, 2, 3):
        candidate_types = {
            item["type"]
            for item in data.recognition_diagnostics["candidate_trace"][index]["candidates"]
        }
        assert {"key_value", "meeting_meta"} <= candidate_types


def test_vetoed_hard_candidate_does_not_hide_valid_soft_candidate():
    class MixedProvider:
        name = "mixed-provider"

        def propose(self, block, features, context):
            return [
                Candidate(ParagraphType.BODY, 0.85, self.name),
                Candidate(
                    ParagraphType.TITLE2,
                    0.98,
                    self.name,
                    hard=True,
                ),
            ]

    paragraph = _paragraph(
        "下一步工作安排；",
        "body",
        0,
        classification_kind="title2",
        classification_confidence=0.95,
    )
    data = _document(paragraph)

    apply_recognition_with_providers(
        data,
        RecognitionConfig(mode="authoritative"),
        providers=(MixedProvider(),),
    )

    assert paragraph.type_id == "body"
    assert paragraph.meta["recognition_provider"].startswith("mixed-provider")


def test_valid_hard_candidate_still_has_priority_over_soft_candidate():
    class MixedProvider:
        name = "mixed-provider"

        def propose(self, block, features, context):
            return [
                Candidate(ParagraphType.BODY, 0.99, self.name),
                Candidate(
                    ParagraphType.SOURCE_NOTE,
                    0.40,
                    self.name,
                    hard=True,
                ),
            ]

    paragraph = _paragraph("来源：公开资料", "body", 0)
    data = _document(paragraph)

    apply_recognition_with_providers(
        data,
        RecognitionConfig(mode="authoritative"),
        providers=(MixedProvider(),),
    )

    assert paragraph.type_id == "note"


def test_authoritative_recognition_fails_when_all_candidates_are_vetoed():
    class InvalidProvider:
        name = "invalid-provider"

        def propose(self, block, features, context):
            return [Candidate(ParagraphType.BODY, 0.9, self.name)]

    data = _document(_paragraph("国发〔2026〕23号", "body", 0))

    with pytest.raises(RuntimeError, match="RECOGNITION_ALL_CANDIDATES_VETOED"):
        apply_recognition_with_providers(
            data,
            RecognitionConfig(mode="authoritative"),
            providers=(InvalidProvider(),),
        )


def test_shadow_recognition_reports_all_veto_without_changing_legacy_type():
    class InvalidProvider:
        name = "invalid-provider"

        def propose(self, block, features, context):
            return [Candidate(ParagraphType.BODY, 0.9, self.name)]

    paragraph = _paragraph("国发〔2026〕23号", "title_cont", 0)
    data = _document(paragraph)

    apply_recognition_with_providers(
        data,
        RecognitionConfig(mode="shadow"),
        providers=(InvalidProvider(),),
    )

    assert paragraph.type_id == "title_cont"
    diagnostic = data.recognition_diagnostics["paragraphs"][0]
    assert diagnostic["review_level"] == "critical_review"
    assert diagnostic["review_reasons"] == ["ALL_CANDIDATES_VETOED"]
    assert diagnostic["provider"].startswith("candidate-conflict:")

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
    assert "embedded_document_title" in [item["type"] for item in trace["candidates"]]
    assert data.recognition_diagnostics["paragraphs"][2]["provider"].startswith("embedded-document:")

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

def test_multiline_date_and_attachment_is_not_a_fabricated_key_value():
    paragraph = _paragraph("2026年7月21日\n附件：1.材料", "body", 0)
    block = extract_blocks(_document(paragraph))[0]

    features = extract_features(block)

    assert features.key_value_label is None
    assert features.key_value_value is None

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
    assert "structure_tree" not in data.recognition_diagnostics

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

def test_authoritative_can_disable_core_and_legacy_candidates() -> None:
    paragraph = _paragraph(
        "国发〔2026〕23号",
        "title",
        0,
        classification_kind="body",
        classification_confidence=0.95,
    )
    data = _document(paragraph)

    apply_recognition(
        data,
        RecognitionConfig(
            mode="authoritative",
            enable_core_candidates=False,
            enable_legacy_candidates=False,
        ),
    )

    assert paragraph.type_id == "dispatch_number"
    trace = data.recognition_diagnostics["candidate_trace"][0]["candidates"]
    assert {item["source"] for item in trace}.isdisjoint({"core", "legacy"})


def test_core_title2_with_trailing_punctuation_is_globally_vetoed() -> None:
    paragraph = _paragraph(
        "下一步工作安排；",
        "body",
        1,
        classification_kind="title2",
        classification_confidence=0.95,
    )
    data = _document(
        _paragraph("前一段正文已经完整说明当前工作情况。", "body", 0),
        paragraph,
        _paragraph("后一段正文继续说明下一阶段重点任务。", "body", 2),
    )

    apply_recognition(data)

    assert paragraph.type_id != "title2"


def test_legacy_title2_with_trailing_punctuation_is_globally_vetoed() -> None:
    paragraph = _paragraph(
        "下一步工作安排）",
        "title2",
        1,
        classification_kind="body",
        classification_confidence=0.9,
    )
    data = _document(
        _paragraph("前一段正文已经完整说明当前工作情况。", "body", 0),
        paragraph,
        _paragraph("后一段正文继续说明下一阶段重点任务。", "body", 2),
    )

    apply_recognition(data)

    assert paragraph.type_id != "title2"

def test_unverified_legacy_attachment_note_does_not_force_final_type() -> None:
    paragraph = _paragraph("相关附件另行发送，后续仍继续说明正文事项。", "attachment_note", 1)
    data = _document(
        _paragraph("前段正文已经开始，并完整说明有关工作情况。", "body", 0),
        paragraph,
        _paragraph("后一段正文继续说明工作安排。", "body", 2),
    )

    apply_recognition(data)

    assert paragraph.type_id == "body"
    diagnostic = data.recognition_diagnostics["paragraphs"][1]
    assert diagnostic["legacy_type"] == "attachment_note"
    assert diagnostic["final_type"] == "body"

def test_previous_title_changes_ambiguous_centered_line_decision():
    after_title = _document(
        _paragraph("主标题", "title", 0, alignment="CENTER"),
        _paragraph("补充说明", "body", 1, alignment="CENTER", bold_char_ratio=1.0),
    )
    after_body = _document(
        _paragraph("正文开头", "body", 0),
        _paragraph("补充说明", "body", 1, alignment="CENTER"),
    )

    apply_recognition(after_title)
    apply_recognition(after_body)

    assert after_title.paragraphs[1].meta["recognition_type"] == "title_continuation"
    assert after_body.paragraphs[1].meta["recognition_type"] == "body"

def test_front_matter_context_overrides_misused_heading_style_without_keywords():
    data = _document(
        _paragraph("关于推进基层治理重点工作的通知", "heading1", 0, alignment="CENTER", style_name="Heading 1"),
        _paragraph("区政协办公室主任  张三", "role_name", 1),
        _paragraph("2026年7月27日", "date_line", 2),
        _paragraph("各有关单位：", "addressing", 3),
        _paragraph("现将有关事项通知如下。", "body", 4),
    )

    apply_recognition(data)

    assert [item.type_id for item in data.paragraphs[:4]] == [
        "title", "role_name", "date_line", "addressing",
    ]
    context = data.recognition_diagnostics["document_context"]
    assert context["front_matter_positions"] == [0, 1, 2, 3]
    assert context["body_start"] == 4
    assert context["body_start_reason"] == "recipient-following-body"

def test_wrong_legacy_front_metadata_cannot_veto_structural_title() -> None:
    title = _paragraph(
        "关于推进基层治理重点工作的通知",
        "role_name",
        0,
        alignment="CENTER",
        style_name="Heading 1",
        legacy_type_id="role_name",
    )
    data = _document(
        title,
        _paragraph("各有关单位：", "body", 1),
        _paragraph("现将有关事项通知如下，请结合实际抓好落实。", "body", 2),
    )

    apply_recognition(data)

    assert title.type_id == "title"
    diagnostic = data.recognition_diagnostics["paragraphs"][0]
    assert diagnostic["final_type"] == "title"
    assert "legacy-reclassified" in diagnostic["evidence_summary"]

def test_disabling_legacy_ignores_legacy_context_and_candidates() -> None:
    title = _paragraph(
        "关于推进基层治理重点工作的通知",
        "role_name",
        0,
        alignment="CENTER",
        style_name="Heading 1",
        legacy_type_id="role_name",
    )
    data = _document(
        title,
        _paragraph("各有关单位：", "body", 1),
        _paragraph("现将有关事项通知如下，请结合实际抓好落实。", "body", 2),
    )

    apply_recognition(
        data,
        RecognitionConfig(enable_legacy_candidates=False),
    )

    assert title.type_id == "title"
    diagnostic = data.recognition_diagnostics["paragraphs"][0]
    assert all(
        "legacy" not in evidence
        for evidence in [*diagnostic["evidence_summary"], *diagnostic["title_context_evidence"]]
    )
    assert {item["source"] for item in data.recognition_diagnostics["candidate_trace"][0]["candidates"]}.isdisjoint({"legacy"})

def test_body_empty_colon_label_is_not_a_recipient_or_key_value() -> None:
    label = _paragraph("某某学院：", "body", 2, no_indent=True)
    data = _document(
        _paragraph("工作情况", "title", 0, alignment="CENTER"),
        _paragraph("现将有关情况报告如下，供审阅。", "body", 1),
        label,
        _paragraph("调研发现有关工作正在有序推进。", "body", 3),
    )

    apply_recognition(data)

    assert label.type_id == "body"
    assert label.meta["no_indent"] is True
    assert label.meta["recognition_section"] == "body"

def test_standalone_salutation_remains_addressing_after_body_started() -> None:
    salutation = _paragraph("各位委员、同志们！", "body", 2)
    data = _document(
        _paragraph("工作情况", "title", 0, alignment="CENTER"),
        _paragraph("前段正文已经开始，并完整说明有关工作情况。", "body", 1),
        salutation,
        _paragraph("后续正文继续正常排版。", "body", 3),
    )

    apply_recognition(data)

    assert salutation.type_id == "addressing"
    assert "standalone-addressing" in salutation.meta["recognition_evidence"]

def test_personal_title_salutation_remains_addressing_after_body_started() -> None:
    salutation = _paragraph("余书记：", "body", 2)
    data = _document(
        _paragraph("工作情况", "title", 0, alignment="CENTER"),
        _paragraph("前段正文已经开始，并完整说明有关工作情况。", "body", 1),
        salutation,
        _paragraph("后续正文继续正常排版。", "body", 3),
    )

    apply_recognition(data)

    assert salutation.type_id == "addressing"
    assert "standalone-addressing" in salutation.meta["recognition_evidence"]

def test_organization_label_is_not_a_personal_title_salutation() -> None:
    label = _paragraph("某某学院：", "body", 2, no_indent=True)
    data = _document(
        _paragraph("工作情况", "title", 0, alignment="CENTER"),
        _paragraph("前段正文已经开始，并完整说明有关工作情况。", "body", 1),
        label,
        _paragraph("后续正文继续正常排版。", "body", 3),
    )

    apply_recognition(data)

    assert label.type_id == "body"

def test_organization_label_with_inline_content_is_not_a_key_value() -> None:
    paragraph = _paragraph("某某职业学院：调研工作正在有序推进。", "body", 2)
    data = _document(
        _paragraph("工作情况", "title", 0, alignment="CENTER"),
        _paragraph("前段正文已经开始，并完整说明有关工作情况。", "body", 1),
        paragraph,
    )

    apply_recognition(data)

    assert paragraph.type_id == "body"
    assert paragraph.meta["recognition_section"] == "body"

def test_front_recipient_is_structural_without_legacy_metadata() -> None:
    recipient = _paragraph("某某学院：", "body", 1)
    data = _document(
        _paragraph("关于开展专项调研的通知", "body", 0, alignment="CENTER"),
        recipient,
        _paragraph("现将有关事项通知如下，请结合实际抓好落实。", "body", 2),
    )

    apply_recognition(data)

    assert recipient.type_id == "addressing"
    assert data.recognition_diagnostics["document_context"]["body_start"] == 2
    assert "front-recipient" in recipient.meta["recognition_evidence"]

def test_explanatory_colon_sentence_remains_body_not_key_value() -> None:
    paragraph = _paragraph("主要原因如下：第一阶段已经完成。", "body", 2)
    data = _document(
        _paragraph("工作情况", "title", 0, alignment="CENTER"),
        _paragraph("前段正文已经开始，并完整说明有关工作情况。", "body", 1),
        paragraph,
    )

    apply_recognition(data)

    assert paragraph.type_id == "body"
    assert paragraph.meta["recognition_section"] == "body"
    assert "colon-explanatory-body" in paragraph.meta["recognition_evidence"]

def test_structural_key_value_generalizes_after_label_rewording() -> None:
    first = _paragraph("责任单位：综合管理部门", "body", 2)
    second = _paragraph("联系人：张某", "body", 3)
    data = _document(
        _paragraph("工作情况", "title", 0, alignment="CENTER"),
        _paragraph("前段正文已经开始，并完整说明有关工作情况。", "body", 1),
        first,
        second,
    )

    apply_recognition(data)

    assert [first.type_id, second.type_id] == ["responsibility_line", "responsibility_line"]
    assert "explicit-label" in first.meta["recognition_evidence"]
    assert "explicit-label" in second.meta["recognition_evidence"]

def test_mid_body_attachment_keyword_is_body_not_hard_attachment_note() -> None:
    paragraph = _paragraph("附件：材料清单", "body", 2)
    data = _document(
        _paragraph("工作情况", "title", 0, alignment="CENTER"),
        _paragraph("前段正文已经开始，并完整说明有关工作情况。", "body", 1),
        paragraph,
        _paragraph("后续正文继续说明材料将另行发送。", "body", 3),
    )

    apply_recognition(data)

    assert paragraph.type_id == "body"
    candidates = data.recognition_diagnostics["candidate_trace"][2]["candidates"]
    attachment = next(item for item in candidates if item["type"] == "attachment_note")
    assert attachment["hard"] is False
    assert "attachment-keyword-without-tail-context" in paragraph.meta["recognition_evidence"]

def test_empty_attachment_keyword_without_items_stays_body() -> None:
    paragraph = _paragraph("附件：", "body", 2)
    data = _document(
        _paragraph("工作情况", "title", 0, alignment="CENTER"),
        _paragraph("前段正文已经开始，并完整说明有关工作情况。", "body", 1),
        paragraph,
    )

    apply_recognition(data)

    assert paragraph.type_id == "body"

def test_tail_attachment_note_and_items_are_confirmed_by_context() -> None:
    note = _paragraph("附件：1.材料清单", "body", 2)
    item = _paragraph("2.补充材料", "body", 3)
    sign_org = _paragraph("星河治理委员会", "body", 4)
    sign_date = _paragraph("2026年7月20日", "body", 5)
    data = _document(
        _paragraph("工作情况", "title", 0, alignment="CENTER"),
        _paragraph("前段正文已经开始，并完整说明有关工作情况。", "body", 1),
        note,
        item,
        sign_org,
        sign_date,
    )

    apply_recognition(data)

    assert [item.type_id for item in data.paragraphs[2:]] == [
        "attachment_note", "attachment_note_item", "sign_org", "sign_date",
    ]
    note_candidates = data.recognition_diagnostics["candidate_trace"][2]["candidates"]
    attachment = next(item for item in note_candidates if item["type"] == "attachment_note")
    assert attachment["hard"] is True
    assert "attachment-tail-context" in attachment["evidence"]

def test_signature_org_uses_generic_tail_context_without_name_list() -> None:
    sign_org = _paragraph("星河治理委员会", "body", 2)
    sign_date = _paragraph("2026年7月20日", "body", 3)
    data = _document(
        _paragraph("工作情况", "title", 0, alignment="CENTER"),
        _paragraph("前段正文已经开始，并完整说明有关工作情况。", "body", 1),
        sign_org,
        sign_date,
    )

    apply_recognition(data)

    assert [sign_org.type_id, sign_date.type_id] == ["sign_org", "sign_date"]
    assert sign_org.text == "星河治理委员会"
    assert "signature-tail-context" in sign_org.meta["recognition_evidence"]

def test_body_unit_mention_is_not_signature_org_without_tail_context() -> None:
    paragraph = _paragraph("星河治理委员会持续推进相关工作，阶段性成效已经形成。", "body", 1)
    data = _document(
        _paragraph("工作情况", "title", 0, alignment="CENTER"),
        paragraph,
        _paragraph("后续正文继续说明工作安排。", "body", 2),
    )

    apply_recognition(data)

    assert paragraph.type_id == "body"
