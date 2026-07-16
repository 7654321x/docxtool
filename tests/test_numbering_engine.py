from dataclasses import dataclass

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from docxtool.document.engine.numbering import (
    NumberingStyle,
    analyze_numbering_sequence,
    detect_numbering_token,
    normalize_numbering_text,
    normalize_paragraph_numbering_run,
)


@dataclass
class RunStub:
    text: str


@dataclass
class ParagraphStub:
    text: str
    runs: list[RunStub]
    native_numbering: bool = False


def test_detects_required_numbering_levels():
    cases = [
        ("一、总体要求", 1, NumberingStyle.CHINESE_DUN, 1),
        ("（一）工作目标", 2, NumberingStyle.CHINESE_PAREN, 1),
        ("1.重点任务", 3, NumberingStyle.DIGIT_DOT, 1),
        ("1、重点任务", 3, NumberingStyle.DIGIT_DUN, 1),
        ("（1）具体措施", 4, NumberingStyle.DIGIT_PAREN, 1),
        ("①细化安排", 4, NumberingStyle.CIRCLED, 1),
    ]

    for text, level, style, value in cases:
        token = detect_numbering_token(text)
        assert token is not None
        assert token.level == level
        assert token.style == style
        assert token.value == value


def test_safe_normalization_handles_mixed_plain_text_and_is_idempotent():
    first = normalize_numbering_text("1、重点任务")
    second = normalize_numbering_text(first.text)

    assert first.changed
    assert first.text == "1.重点任务"
    assert not second.changed
    assert second.text == first.text


def test_sequence_reports_gap_and_same_level_mixed_style():
    issues = analyze_numbering_sequence(["一、总体要求", "（一）工作目标", "1.重点任务", "3.跳号任务", "4、混用任务"])

    assert any(issue.kind == "gap" and issue.expected == 2 and issue.actual == 3 for issue in issues)
    assert any(issue.kind == "mixed_style" and issue.level == 3 for issue in issues)


def test_dates_law_articles_and_attachment_numbers_are_protected():
    protected = ["2026年7月14日", "2026.7.14会议记录", "第十二条 本办法自发布之日起施行。", "附件1", "附件：1.任务清单"]

    for text in protected:
        assert detect_numbering_token(text) is None
        result = normalize_numbering_text(text)
        assert not result.changed
        assert result.text == text


def test_normalize_paragraph_text_run_without_rebuilding_paragraph():
    paragraph = ParagraphStub("(1)具体措施", [RunStub("(1)"), RunStub("具体措施")])

    result = normalize_paragraph_numbering_run(paragraph)

    assert result.changed
    assert paragraph.text == "(1)具体措施"
    assert "".join(run.text for run in paragraph.runs) == "（1）具体措施"


def test_word_native_numbering_is_preserved():
    document = Document()
    paragraph = document.add_paragraph("具体措施")
    ppr = paragraph._element.get_or_add_pPr()
    num_pr = OxmlElement("w:numPr")
    ilvl = OxmlElement("w:ilvl")
    ilvl.set(qn("w:val"), "0")
    num_id = OxmlElement("w:numId")
    num_id.set(qn("w:val"), "1")
    num_pr.append(ilvl)
    num_pr.append(num_id)
    ppr.append(num_pr)

    before = paragraph._element.xml
    result = normalize_paragraph_numbering_run(paragraph)

    assert not result.changed
    assert result.reason == "native_numbering"
    assert paragraph._element.xml == before
