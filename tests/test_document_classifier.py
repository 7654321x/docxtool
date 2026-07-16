from dataclasses import dataclass

from docxtool.document.classifier import ParagraphKind, classify_paragraphs


@dataclass
class ParagraphStub:
    text: str
    style_name: str = ""
    alignment: str = ""
    font_size_pt: float | None = None
    bold: bool = False
    first_line_indent: float | None = None


def kinds(paragraphs):
    return [item.kind for item in classify_paragraphs(paragraphs)]


def test_main_title_continuation_and_recipient_are_contextual():
    paragraphs = [
        ParagraphStub("内江市东兴区人民政府办公室", alignment="CENTER", font_size_pt=22),
        ParagraphStub("关于开展基层治理专项工作的通知", alignment="CENTER", font_size_pt=22),
        ParagraphStub("东府办发〔2026〕12号", alignment="CENTER"),
        ParagraphStub("各镇人民政府、街道办事处："),
        ParagraphStub("现将有关事项通知如下。"),
    ]

    result = classify_paragraphs(paragraphs)

    assert result[0].kind == ParagraphKind.MAIN_TITLE
    assert result[1].kind == ParagraphKind.TITLE_CONTINUATION
    assert result[2].kind == ParagraphKind.DISPATCH_NUMBER
    assert result[3].kind == ParagraphKind.RECIPIENT
    assert result[0].auto_format
    assert result[1].auto_format


def test_heading_levels_include_fourth_level_and_inline_body():
    paragraphs = [
        ParagraphStub("一、总体要求"),
        ParagraphStub("（一）工作目标"),
        ParagraphStub("1.重点任务"),
        ParagraphStub("（1）强化组织领导。各单位要认真落实。"),
        ParagraphStub("①细化工作台账。"),
    ]

    assert kinds(paragraphs) == [
        ParagraphKind.HEADING_LEVEL_1,
        ParagraphKind.HEADING_LEVEL_2,
        ParagraphKind.HEADING_LEVEL_3,
        ParagraphKind.HEADING_LEVEL_4,
        ParagraphKind.HEADING_LEVEL_4,
    ]


def test_attachment_signature_date_and_cc_recipient_flow():
    paragraphs = [
        ParagraphStub("一、工作安排"),
        ParagraphStub("请各单位认真贯彻执行。"),
        ParagraphStub("附件：1.任务清单"),
        ParagraphStub("特此通知。"),
        ParagraphStub("内江市东兴区人民政府办公室", alignment="RIGHT"),
        ParagraphStub("2026年7月14日", alignment="RIGHT"),
        ParagraphStub("附件1"),
        ParagraphStub("任务清单", alignment="CENTER", bold=True),
        ParagraphStub("抄送：区委办公室、区人大常委会办公室。"),
    ]

    result = classify_paragraphs(paragraphs)

    assert result[2].kind == ParagraphKind.ATTACHMENT_NOTE
    assert result[3].kind == ParagraphKind.CLOSING
    assert result[4].kind == ParagraphKind.SIGNATURE_ORG
    assert result[5].kind == ParagraphKind.SIGNATURE_DATE
    assert result[6].kind == ParagraphKind.ATTACHMENT_TITLE
    assert result[8].kind == ParagraphKind.CC_RECIPIENT


def test_short_body_is_not_promoted_to_heading_without_supporting_evidence():
    result = classify_paragraphs([ParagraphStub("一、工作安排"), ParagraphStub("按期完成")])

    assert result[1].kind == ParagraphKind.BODY
    assert result[1].confidence < 0.9
    assert not result[1].auto_format


def test_low_confidence_body_policy_keeps_aggressive_format_off():
    result = classify_paragraphs([ParagraphStub("工作要求")])[0]

    assert result.kind == ParagraphKind.BODY
    assert not result.auto_format
    assert any(item.source == "policy" for item in result.evidence)
