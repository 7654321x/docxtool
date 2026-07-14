import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from docx import Document
from docx.enum.section import WD_SECTION
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm

from docxtool.document.engine.page_number import apply_page_number, apply_page_numbers
from docxtool.security.docx_integrity import validate_docx_integrity

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


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


def _footer_roots(path: Path) -> dict[str, ET.Element]:
    with zipfile.ZipFile(path) as archive:
        return {
            name: ET.fromstring(archive.read(name))
            for name in archive.namelist()
            if name.startswith("word/footer") and name.endswith(".xml")
        }


def _field_instructions(root: ET.Element) -> list[str]:
    return ["".join(element.itertext()).strip() for element in root.findall(f".//{{{W_NS}}}instrText")]


def _field_char_types(root: ET.Element) -> list[str]:
    return [
        element.get(qn("w:fldCharType"), "")
        for element in root.findall(f".//{{{W_NS}}}fldChar")
    ]


def _assert_complex_fields_are_paired(root: ET.Element) -> None:
    open_fields = 0
    waiting_for_end = 0
    for field_type in _field_char_types(root):
        if field_type == "begin":
            open_fields += 1
        elif field_type == "separate":
            assert open_fields > 0
            waiting_for_end += 1
        elif field_type == "end":
            assert open_fields > 0
            assert waiting_for_end > 0
            open_fields -= 1
            waiting_for_end -= 1
    assert open_fields == 0
    assert waiting_for_end == 0


def _visible_text(root: ET.Element) -> str:
    return "".join(element.text or "" for element in root.findall(f".//{{{W_NS}}}t"))


def test_page_number_fields_outside_position_and_first_page_hidden(tmp_path: Path) -> None:
    document = Document()
    first = document.sections[0]
    first.bottom_margin = Cm(3.5)
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

    apply_page_number(
        document,
        {
            "style": "cn_total",
            "position": "outside",
            "first_page": False,
            "section_starts": [1, None],
            "offset_from_text_mm": 7,
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
    assert "<w:t>1</w:t>" not in combined_footer_xml
    assert "AlternateContent" not in combined_footer_xml
    assert "txbxContent" not in combined_footer_xml
    assert "textbox" not in combined_footer_xml
    first_page_footer_xml = next(xml for xml in footers.values() if "First page legal notice" in xml)
    assert "PAGE" not in first_page_footer_xml
    assert "NUMPAGES" not in first_page_footer_xml
    for root in _footer_roots(output).values():
        instructions = _field_instructions(root)
        assert instructions.count("PAGE") <= 1
        assert instructions.count("NUMPAGES") <= 1
        _assert_complex_fields_are_paired(root)
    assert any('w:val="right"' in xml for xml in footers.values())
    assert any('w:val="left"' in xml for xml in footers.values())
    with zipfile.ZipFile(output) as archive:
        settings_xml = archive.read("word/settings.xml").decode("utf-8")
    assert "evenAndOddHeaders" in settings_xml
    assert "updateFields" in settings_xml
    assert abs(first.footer_distance.cm - 2.8) < 0.02
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


def test_page_number_formats_create_standard_fields(tmp_path: Path) -> None:
    cases = [
        ("dash", "— ", " —", ["PAGE"]),
        ("plain", "", "", ["PAGE"]),
        ("cn", "第 ", " 页", ["PAGE"]),
        ("cn_total", "第 ", " 页 共 ", ["PAGE", "NUMPAGES"]),
    ]

    for style, prefix, suffix, instructions in cases:
        document = Document()
        document.add_paragraph(style)
        apply_page_number(document, {"style": style, "position": "center"})
        output = tmp_path / f"{style}.docx"
        document.save(output)

        assert validate_docx_integrity(output).ok is True
        roots = _footer_roots(output)
        assert len(roots) == 1
        root = next(iter(roots.values()))
        assert _field_instructions(root) == instructions
        _assert_complex_fields_are_paired(root)
        text = _visible_text(root)
        assert prefix in text
        assert suffix in text
        assert "1" not in text
        footer_xml = next(iter(_footer_xml(output).values()))
        assert "AlternateContent" not in footer_xml
        assert "txbxContent" not in footer_xml
        assert "textbox" not in footer_xml


def test_page_number_preserves_non_page_footer_content_when_replacing_old_field(tmp_path: Path) -> None:
    document = Document()
    footer = document.sections[0].footer
    footer.is_linked_to_previous = False
    paragraph = footer.paragraphs[0]
    paragraph.text = "Confidential"
    paragraph.add_run(" — ")
    _add_field(paragraph, "PAGE")
    paragraph.add_run(" — ")
    footer.add_paragraph("Prepared by office")
    document.add_paragraph("body")

    apply_page_number(document, {"style": "plain", "position": "center"})
    output = tmp_path / "preserve-footer.docx"
    document.save(output)

    assert validate_docx_integrity(output).ok is True
    root = next(iter(_footer_roots(output).values()))
    assert _field_instructions(root) == ["PAGE"]
    assert "Confidential" in _visible_text(root)
    assert "Prepared by office" in _visible_text(root)
    assert "Confidential —" not in _visible_text(root)
    _assert_complex_fields_are_paired(root)


def test_page_number_can_apply_first_and_even_centered_footers(tmp_path: Path) -> None:
    document = Document()
    section = document.sections[0]
    section.different_first_page_header_footer = True
    section.first_page_footer.is_linked_to_previous = False
    section.first_page_footer.paragraphs[0].text = "First note"
    document.settings._element.append(OxmlElement("w:evenAndOddHeaders"))
    section.even_page_footer.is_linked_to_previous = False
    section.even_page_footer.paragraphs[0].text = "Even note"
    document.add_paragraph("body")

    apply_page_number(document, {"style": "cn", "position": "center", "first_page": True})
    output = tmp_path / "first-even.docx"
    document.save(output)

    assert validate_docx_integrity(output).ok is True
    footers = _footer_roots(output)
    assert len(footers) == 3
    for root in footers.values():
        assert _field_instructions(root) == ["PAGE"]
        _assert_complex_fields_are_paired(root)
    footer_xml = "\n".join(_footer_xml(output).values())
    assert "First note" in footer_xml
    assert "Even note" in footer_xml
    assert footer_xml.count('w:val="center"') == 3
