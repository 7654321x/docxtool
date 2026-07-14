import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from docx import Document
from docx.enum.section import WD_SECTION
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from docxtool.document.engine.page_number import apply_page_numbers
from docxtool.security.docx_integrity import validate_docx_integrity


def _add_field(paragraph, instruction: str) -> None:
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    paragraph.add_run()._r.append(begin)
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" {instruction} "
    paragraph.add_run()._r.append(instr)
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    paragraph.add_run()._r.append(separate)
    paragraph.add_run("1")
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    paragraph.add_run()._r.append(end)


def _footer_xml(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as archive:
        return {
            name: archive.read(name).decode("utf-8")
            for name in archive.namelist()
            if name.startswith("word/footer") and name.endswith(".xml")
        }


def _document_xml(path: Path) -> ET.Element:
    with zipfile.ZipFile(path) as archive:
        return ET.fromstring(archive.read("word/document.xml"))


def test_page_number_fields_outside_position_and_first_page_hidden(tmp_path: Path) -> None:
    document = Document()
    first = document.sections[0]
    first.footer.is_linked_to_previous = False
    first.footer.paragraphs[0].text = "Confidential footer"
    old_page = first.footer.add_paragraph("old ")
    _add_field(old_page, "PAGE")
    first.even_page_footer.is_linked_to_previous = False
    first.even_page_footer.paragraphs[0].text = "Even footer note"
    document.add_paragraph("section one")
    second = document.add_section(WD_SECTION.NEW_PAGE)
    second.footer.is_linked_to_previous = False
    second.footer.paragraphs[0].text = "Section two footer note"
    document.add_paragraph("section two")
    first = document.sections[0]
    first.different_first_page_header_footer = True
    first.first_page_footer.is_linked_to_previous = False
    first.first_page_footer.paragraphs[0].text = "First page legal notice"

    apply_page_numbers(
        document,
        {
            "style": "cn_total",
            "position": "outside",
            "first_page": "hide",
            "section_starts": [1, None],
            "font_name": "SimSun",
            "font_size_pt": 10.5,
        },
    )
    output = tmp_path / "page-numbered.docx"
    document.save(output)

    assert validate_docx_integrity(output).ok is True
    footers = _footer_xml(output)
    combined_footer_xml = "\n".join(footers.values())
    assert "Confidential footer" in combined_footer_xml
    assert "Section two footer note" in combined_footer_xml
    assert "First page legal notice" in combined_footer_xml
    assert "PAGE" in combined_footer_xml
    assert "NUMPAGES" in combined_footer_xml
    assert "<w:t>PAGE</w:t>" not in combined_footer_xml
    assert "<w:t>NUMPAGES</w:t>" not in combined_footer_xml
    first_page_footer_xml = next(xml for xml in footers.values() if "First page legal notice" in xml)
    assert "PAGE" not in first_page_footer_xml
    assert "NUMPAGES" not in first_page_footer_xml
    assert any('w:val="right"' in xml for xml in footers.values())
    assert any('w:val="left"' in xml for xml in footers.values())
    with zipfile.ZipFile(output) as archive:
        settings_xml = archive.read("word/settings.xml").decode("utf-8")
    assert "evenAndOddHeaders" in settings_xml
    sections = _document_xml(output).findall(".//" + qn("w:sectPr"))
    assert any(section.find(qn("w:titlePg")) is not None for section in sections)
    starts = [pg_num_type.get(qn("w:start")) for section in sections if (pg_num_type := section.find(qn("w:pgNumType"))) is not None]
    assert starts == ["1"]


def test_page_number_styles_and_section_restart_policy(tmp_path: Path) -> None:
    document = Document()
    document.add_paragraph("first")
    document.add_section(WD_SECTION.NEW_PAGE)
    document.add_paragraph("second")

    apply_page_numbers(document, {"style": "dash", "position": "center", "section_numbering": "restart"})
    output = tmp_path / "restart.docx"
    document.save(output)

    validate_docx_integrity(output)
    footer_xml = "\n".join(_footer_xml(output).values())
    assert "— " in footer_xml
    assert " —" in footer_xml
    assert footer_xml.count("PAGE") == 2
    assert "NUMPAGES" not in footer_xml
    assert 'w:val="center"' in footer_xml
    sections = _document_xml(output).findall(".//" + qn("w:sectPr"))
    starts = [section.find(qn("w:pgNumType")).get(qn("w:start")) for section in sections]
    assert starts == ["1", "1"]
