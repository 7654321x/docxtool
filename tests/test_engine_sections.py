from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from docxtool.document.engine.sections import (
    apply_page_settings,
    copy_paragraph_sectPr,
    doc_grid_char_space,
    line_spacing_twips,
    replace_body_sectPr,
    section_margins_cm,
    sectPr_is_landscape,
    set_sectPr_page_layout,
)
from docxtool.document.style_config import PageSettings


def _settings() -> PageSettings:
    """构造测试页面设置，返回带标准公文页边距和网格的 PageSettings。"""
    return PageSettings()


def test_section_margins_rotate_physical_edges_for_landscape() -> None:
    """横向分节应按物理边旋转页边距，而不是只交换页面宽高。"""
    settings = _settings()

    assert section_margins_cm(settings, False) == (3.7, 3.5, 2.8, 2.6)
    assert section_margins_cm(settings, True) == (2.8, 2.6, 3.5, 3.7)


def test_doc_grid_char_space_uses_ooxml_point_delta_units() -> None:
    """docGrid 字距应使用磅差值乘 4096，保证 WPS 28 字版心稳定。"""
    settings = _settings()
    content_width_twips = (
        int(round(settings.page_width_cm * 567))
        - int(round(settings.margin_left_cm * 567))
        - int(round(settings.margin_right_cm * 567))
    )

    assert doc_grid_char_space(content_width_twips, settings.chars_per_line) == -842
    assert line_spacing_twips(settings) == 560


def test_set_sectPr_page_layout_writes_portrait_page_and_grid() -> None:
    """纵向分节布局应写入页面尺寸、页边距和文档网格。"""
    sect_pr = OxmlElement("w:sectPr")

    set_sectPr_page_layout(sect_pr, _settings())

    pg_sz = sect_pr.find(qn("w:pgSz"))
    pg_mar = sect_pr.find(qn("w:pgMar"))
    doc_grid = sect_pr.find(qn("w:docGrid"))
    assert pg_sz.get(qn("w:orient")) is None
    assert pg_mar.get(qn("w:top")) == str(int(round(3.7 * 567)))
    assert pg_mar.get(qn("w:left")) == str(int(round(2.8 * 567)))
    assert doc_grid.get(qn("w:charsPerLine")) == "28"
    assert doc_grid.get(qn("w:linePitch")) == "560"


def test_set_sectPr_page_layout_preserves_landscape_size_and_rotates_margins() -> None:
    """横向分节应保留源页面尺寸，设置横向标记并旋转页边距。"""
    sect_pr = OxmlElement("w:sectPr")
    pg_sz = OxmlElement("w:pgSz")
    pg_sz.set(qn("w:w"), "16838")
    pg_sz.set(qn("w:h"), "11906")
    sect_pr.append(pg_sz)

    assert sectPr_is_landscape(sect_pr) is True
    set_sectPr_page_layout(sect_pr, _settings())

    pg_mar = sect_pr.find(qn("w:pgMar"))
    assert pg_sz.get(qn("w:orient")) == "landscape"
    assert pg_sz.get(qn("w:w")) == "16838"
    assert pg_sz.get(qn("w:h")) == "11906"
    assert pg_mar.get(qn("w:top")) == str(int(round(2.8 * 567)))
    assert pg_mar.get(qn("w:right")) == str(int(round(3.7 * 567)))
    assert sect_pr.find(qn("w:docGrid")).get(qn("w:charsPerLine")) == "28"


def test_copy_and_replace_section_properties_keep_single_sectPr() -> None:
    """段落和正文替换分节属性时应先移除旧 sectPr，再写入新副本。"""
    document = Document()
    paragraph = document.add_paragraph("正文")
    source_sect_pr = OxmlElement("w:sectPr")
    source_pg_mar = OxmlElement("w:pgMar")
    source_pg_mar.set(qn("w:top"), "123")
    source_sect_pr.append(source_pg_mar)

    copy_paragraph_sectPr(paragraph, source_sect_pr)
    copy_paragraph_sectPr(paragraph, source_sect_pr)

    paragraph_sections = paragraph._element.findall(".//" + qn("w:sectPr"))
    assert len(paragraph_sections) == 1
    assert paragraph_sections[0].find(qn("w:pgMar")).get(qn("w:top")) == "123"

    replace_body_sectPr(document, source_sect_pr)
    replace_body_sectPr(document, source_sect_pr)
    body_sections = document._body._element.findall(qn("w:sectPr"))
    assert len(body_sections) == 1
    assert body_sections[0].find(qn("w:pgMar")).get(qn("w:top")) == "123"


def test_apply_page_settings_writes_defaults_compat_and_grid() -> None:
    """页面设置入口应写入默认字体、兼容网格设置和正文 sectPr。"""
    document = Document()

    apply_page_settings(document, _settings())

    styles = document.styles._element
    defaults = styles.find(qn("w:docDefaults"))
    r_fonts = defaults.find(".//" + qn("w:rFonts"))
    assert r_fonts.get(qn("w:eastAsia")) == "仿宋_GB2312"
    assert r_fonts.get(qn("w:ascii")) == "Times New Roman"

    compat = document.settings._element.find(qn("w:compat"))
    names = {item.get(qn("w:name")) for item in compat.findall(qn("w:compatSetting"))}
    assert "useFELayout" in names
    assert "doNotExpand" in names

    sect_pr = document.sections[0]._sectPr
    assert sect_pr.find(qn("w:docGrid")).get(qn("w:charsPerLine")) == "28"
