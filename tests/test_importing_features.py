from __future__ import annotations

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

from docxtool.document.importer import extract_features
from docxtool.document.importing.features import extract_paragraph_features
from docxtool.document.importing.numbering import detect_numbering_prefix


def _set_east_asia_font(run, name: str, ascii_name: str = "Arial") -> None:
    """给测试 run 写入中英文字体，传入 run 和字体名，无返回值。"""
    rpr = run._element.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.append(fonts)
    fonts.set(qn("w:eastAsia"), name)
    fonts.set(qn("w:ascii"), ascii_name)
    fonts.set(qn("w:hAnsi"), ascii_name)


def test_importing_features_extracts_physical_run_and_locator_facts() -> None:
    """验证物理导入层只提取格式和定位事实，不依赖 importer 分类链。"""
    document = Document()
    paragraph = document.add_paragraph()
    run = paragraph.add_run("一、测试标题")
    _set_east_asia_font(run, "SimHei", "Calibri")
    run.font.size = Pt(16)
    run.bold = True

    features = extract_paragraph_features(
        paragraph,
        3,
        detect_numbering_prefix_func=detect_numbering_prefix,
    )

    assert features.text == "一、测试标题"
    assert features.paragraph_index == 3
    assert features.source_locator_status == "confirmed"
    assert features.numbering_prefix == "一、"
    assert features.source_run_spans[0].east_asia_font_name == "SimHei"
    assert features.source_run_spans[0].ascii_font_name == "Calibri"
    assert features.source_run_spans[0].font_size_pt == 16.0
    assert features.source_run_spans[0].bold is True


def test_importer_extract_features_keeps_legacy_facade() -> None:
    """验证旧 `document.importer.extract_features` 入口仍转发并返回同等事实。"""
    document = Document()
    paragraph = document.add_paragraph("正文内容")

    direct = extract_paragraph_features(
        paragraph,
        0,
        detect_numbering_prefix_func=detect_numbering_prefix,
    )
    legacy = extract_features(paragraph, 0)

    assert legacy.text == direct.text
    assert legacy.source_physical_text == direct.source_physical_text
    assert legacy.source_locator_status == direct.source_locator_status
    assert legacy.source_run_spans == direct.source_run_spans
