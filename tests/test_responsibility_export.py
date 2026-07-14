import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from docx import Document
from docx.oxml.ns import qn

from docxtool.document.engine import export_doc
from docxtool.document.engine.core import _apply_responsibility_line
from docxtool.document.importer import DocumentData, ParagraphData, ParagraphFeatures
from docxtool.document.style_config import PageSettings, StyleRule
from docxtool.security.docx_integrity import validate_docx_integrity


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}


def _rules() -> list[StyleRule]:
    return [StyleRule.default_for_row(index) for index in range(24)]


def _document_xml(path: Path) -> ET.Element:
    with zipfile.ZipFile(path) as archive:
        return ET.fromstring(archive.read("word/document.xml"))


def _paragraphs(root: ET.Element) -> list[ET.Element]:
    return root.findall(".//w:body/w:p", NS)


def _text(paragraph: ET.Element) -> str:
    return "".join(element.text or "" for element in paragraph.findall(".//w:t", NS))


def _lines(paragraph: ET.Element) -> list[str]:
    lines = [""]
    for element in paragraph.iter():
        if element.tag == qn("w:t"):
            lines[-1] += element.text or ""
        elif element.tag == qn("w:br"):
            lines.append("")
    return lines


def _pstyle(paragraph: ET.Element) -> str:
    p_style = paragraph.find("w:pPr/w:pStyle", NS)
    return p_style.get(qn("w:val")) if p_style is not None else ""


def _run_text_and_bold(paragraph: ET.Element) -> list[tuple[str, bool]]:
    result = []
    for run in paragraph.findall("w:r", NS):
        text = "".join(element.text or "" for element in run.findall("w:t", NS))
        if not text:
            continue
        bold = run.find("w:rPr/w:b", NS)
        bold_value = bold.get(qn("w:val")) if bold is not None else None
        result.append((text, bold is not None and bold_value not in {"0", "false", "False"}))
    return result


def _export_responsibility(tmp_path: Path, text: str) -> tuple[Path, dict]:
    output = tmp_path / "responsibility.docx"
    data = DocumentData(
        paragraphs=[
            ParagraphData("主标题", "title", "主标题", ParagraphFeatures()),
            ParagraphData("正文内容", "body", "正文内容", ParagraphFeatures()),
            ParagraphData(text, "responsibility_line", text, ParagraphFeatures(), meta={"colon_bold": True}),
            ParagraphData("附件 1", "attachment_page_mark", "附件 1", ParagraphFeatures()),
        ],
        filepath="generated.docx",
    )
    stats = export_doc(data, _rules(), PageSettings(), str(output))
    return output, stats


@pytest.mark.parametrize(
    ("source_text", "expected_lines"),
    [
        ("责任单位：区政府", ["责任单位：区政府"]),
        ("责任单位：区政府\n责任单位：商务局", ["责任单位：区政府", "责任单位：商务局"]),
        ("责任单位：区政府责任单位：商务局责任单位：区政府", ["责任单位：区政府", "责任单位：商务局", "责任单位：区政府"]),
        ("责 任 单 位 ：区政府", ["责任单位：区政府"]),
    ],
)
def test_responsibility_export_splits_and_normalizes_labels(
    tmp_path: Path,
    source_text: str,
    expected_lines: list[str],
) -> None:
    output, stats = _export_responsibility(tmp_path, source_text)

    assert stats["fallback_count"] == 0
    assert validate_docx_integrity(output).ok is True
    root = _document_xml(output)
    responsibility = next(paragraph for paragraph in _paragraphs(root) if "责任单位" in _text(paragraph))

    assert _pstyle(responsibility) == "DCT-Responsibility"
    assert _lines(responsibility) == expected_lines
    assert len(responsibility.findall(".//w:br", NS)) == len(expected_lines) - 1
    assert all(line.count("责任单位：") == 1 for line in expected_lines)
    assert root.findall(".//w:numPr", NS) == []


def test_responsibility_runs_format_label_only_and_direct_paragraph_format(tmp_path: Path) -> None:
    output, _stats = _export_responsibility(tmp_path, "责 任 单 位 ：区政府责任单位：商务局")
    root = _document_xml(output)
    responsibility = next(paragraph for paragraph in _paragraphs(root) if "责任单位" in _text(paragraph))

    assert _run_text_and_bold(responsibility) == [
        ("责任单位：", True),
        ("区政府", False),
        ("责任单位：", True),
        ("商务局", False),
    ]
    assert _lines(responsibility) == ["责任单位：区政府", "责任单位：商务局"]
    assert responsibility.find("w:pPr/w:jc", NS).get(qn("w:val")) == "left"
    indent = responsibility.find("w:pPr/w:ind", NS)
    assert indent is not None
    assert indent.get(qn("w:firstLineChars")) == "0"
    assert indent.get(qn("w:firstLine")) == "0"


def test_responsibility_renderer_is_idempotent() -> None:
    document = Document()
    paragraph = document.add_paragraph("责任单位：区政府责任单位：区政府")

    _apply_responsibility_line(paragraph, paragraph.text)
    first = paragraph.text
    _apply_responsibility_line(paragraph, paragraph.text)

    assert paragraph.text == first
    assert paragraph.text == "责任单位：区政府\n责任单位：区政府"


def test_heading1_report_split_body_has_dct_body_and_structural_invariants(tmp_path: Path) -> None:
    output = tmp_path / "heading1-report.docx"
    data = DocumentData(
        paragraphs=[
            ParagraphData(
                "政协报告标题。正文内容正文内容正文内容",
                "heading1_report",
                "政协报告标题。正文内容正文内容正文内容",
                ParagraphFeatures(),
                meta={"heading1_report_split": True},
            ),
            ParagraphData("责任单位：区政府责任单位：商务局", "responsibility_line", "责任单位：区政府责任单位：商务局", ParagraphFeatures()),
            ParagraphData("附件 1", "attachment_page_mark", "附件 1", ParagraphFeatures()),
        ],
        filepath="generated.docx",
    )

    stats = export_doc(data, _rules(), PageSettings(), str(output))

    assert stats["fallback_count"] == 0
    assert validate_docx_integrity(output).ok is True
    root = _document_xml(output)
    paragraphs = [paragraph for paragraph in _paragraphs(root) if _text(paragraph).strip()]
    style_by_text = {_text(paragraph): _pstyle(paragraph) for paragraph in paragraphs}

    assert style_by_text["政协报告标题。"] == "DCT-Heading1"
    assert style_by_text["正文内容正文内容正文内容"] == "DCT-Body"
    assert style_by_text["责任单位：区政府责任单位：商务局"] == "DCT-Responsibility"
    assert style_by_text["附件 1"] == "DCT-AttachmentMark"
    assert all(_pstyle(paragraph).startswith("DCT-") for paragraph in paragraphs)
    assert root.findall(".//w:numPr", NS) == []
