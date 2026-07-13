import base64
import logging
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.text import WD_BREAK
from docx.oxml.ns import qn
from docx.shared import Cm

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import export_doc
from importer import DocxImporter
from style_config import PageSettings, StyleRule, logger


def _rules():
    return [StyleRule.default_for_row(i) for i in range(10)]


def _body_order(path):
    doc = Document(path)
    order = []
    for child in doc._body._element.iterchildren():
        if child.tag == qn("w:p"):
            text = "".join(t.text or "" for t in child.findall(".//" + qn("w:t")))
            has_image = bool(child.findall(".//" + qn("a:blip")))
            if has_image:
                order.append(("image", ""))
            elif text:
                order.append(("paragraph", text))
        elif child.tag == qn("w:tbl"):
            text = "".join(t.text or "" for t in child.findall(".//" + qn("w:t")))
            order.append(("table", text))
    return order


def _document_xml_root(path):
    with zipfile.ZipFile(path) as zf:
        return zf.read("word/document.xml")


def _replace_document_xml(source, target, transform):
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "word/document.xml":
                data = transform(data.decode("utf-8")).encode("utf-8")
            dst.writestr(item, data)


def _inline_counts(path):
    from xml.etree import ElementTree as ET

    root = ET.fromstring(_document_xml_root(path))
    breaks = root.findall(".//" + qn("w:br"))
    page_breaks = [br for br in breaks if br.get(qn("w:type")) == "page"]
    line_breaks = [br for br in breaks if br.get(qn("w:type")) != "page"]
    tabs = root.findall(".//" + qn("w:tab"))
    rendered = root.findall(".//" + qn("w:lastRenderedPageBreak"))
    return {
        "line_breaks": len(line_breaks),
        "page_breaks": len(page_breaks),
        "rendered_page_breaks": len(rendered),
        "tabs": len(tabs),
    }


def _section_summary(path):
    from xml.etree import ElementTree as ET

    root = ET.fromstring(_document_xml_root(path))
    sections = root.findall(".//" + qn("w:sectPr"))
    summary = []
    for sect in sections:
        section_type = sect.find(qn("w:type"))
        page_size = sect.find(qn("w:pgSz"))
        margins = sect.find(qn("w:pgMar"))
        summary.append({
            "orient": page_size.get(qn("w:orient")) if page_size is not None else "",
            "type": section_type.get(qn("w:val")) if section_type is not None else "",
            "width": page_size.get(qn("w:w")) if page_size is not None else "",
            "height": page_size.get(qn("w:h")) if page_size is not None else "",
            "margin_left": margins.get(qn("w:left")) if margins is not None else "",
        })
    return summary


class BodyOrderExportTest(unittest.TestCase):
    def setUp(self):
        logger.setLevel(logging.ERROR)

    def test_keeps_table_once_at_original_body_position(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            source = tmp / "source.docx"
            output = tmp / "output.docx"

            doc = Document()
            doc.add_paragraph("before")
            table = doc.add_table(rows=1, cols=1)
            table.cell(0, 0).text = "cell"
            doc.add_paragraph("after")
            doc.save(source)

            data = DocxImporter().load(str(source), _rules())
            export_doc(data, _rules(), PageSettings(), str(output))

            self.assertEqual(
                _body_order(output),
                [("paragraph", "before"), ("table", "cell"), ("paragraph", "after")],
            )

    def test_keeps_image_at_original_body_position(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            source = tmp / "source.docx"
            output = tmp / "output.docx"
            image = tmp / "tiny.png"
            image.write_bytes(base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
            ))

            doc = Document()
            doc.add_paragraph("before")
            doc.add_picture(str(image))
            doc.add_paragraph("after")
            doc.save(source)

            data = DocxImporter().load(str(source), _rules())
            export_doc(data, _rules(), PageSettings(), str(output))

            self.assertEqual(
                _body_order(output),
                [("paragraph", "before"), ("image", ""), ("paragraph", "after")],
            )

    def test_preserves_manual_page_breaks_line_breaks_and_tabs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            source = tmp / "source.docx"
            output = tmp / "output.docx"

            doc = Document()
            p = doc.add_paragraph()
            run = p.add_run("文本前")
            run.add_break(WD_BREAK.PAGE)
            p.add_run("文本后")
            doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
            p = doc.add_paragraph()
            run = p.add_run()
            run.add_break(WD_BREAK.PAGE)
            run.add_break(WD_BREAK.PAGE)
            p = doc.add_paragraph()
            run = p.add_run("第一行")
            run.add_break()
            p.add_run("第二行")
            p = doc.add_paragraph()
            run = p.add_run("甲")
            run.add_tab()
            p.add_run("乙")
            doc.save(source)

            data = DocxImporter().load(str(source), _rules())
            export_doc(data, _rules(), PageSettings(), str(output))

            counts = _inline_counts(output)
            self.assertEqual(counts["page_breaks"], 4)
            self.assertEqual(counts["line_breaks"], 1)
            self.assertEqual(counts["tabs"], 1)

    def test_last_rendered_page_break_is_not_rewritten_as_manual_break(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            source = tmp / "source.docx"
            rendered_source = tmp / "rendered-source.docx"
            output = tmp / "output.docx"

            doc = Document()
            doc.add_paragraph("甲乙")
            doc.save(source)
            _replace_document_xml(
                source,
                rendered_source,
                lambda xml: xml.replace(
                    "<w:t>甲乙</w:t>",
                    "<w:t>甲</w:t><w:lastRenderedPageBreak/><w:t>乙</w:t>",
                ),
            )

            data = DocxImporter().load(str(rendered_source), _rules())
            export_doc(data, _rules(), PageSettings(), str(output))

            counts = _inline_counts(output)
            self.assertEqual(counts["page_breaks"], 0)
            self.assertEqual(counts["rendered_page_breaks"], 0)

    def test_preserves_multi_section_orientation_and_page_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            source = tmp / "source.docx"
            output = tmp / "output.docx"

            doc = Document()
            doc.add_paragraph("纵向第一页")
            landscape = doc.add_section(WD_SECTION.NEW_PAGE)
            landscape.orientation = WD_ORIENT.LANDSCAPE
            landscape.page_width = Cm(29.7)
            landscape.page_height = Cm(21.0)
            doc.add_paragraph("横向页面")
            portrait = doc.add_section(WD_SECTION.NEW_PAGE)
            portrait.orientation = WD_ORIENT.PORTRAIT
            portrait.page_width = Cm(21.0)
            portrait.page_height = Cm(29.7)
            doc.add_paragraph("纵向末页")
            doc.save(source)

            data = DocxImporter().load(str(source), _rules())
            export_doc(data, _rules(), PageSettings(), str(output))

            sections = _section_summary(output)
            self.assertGreaterEqual(len(sections), 3)
            self.assertTrue(any(section["orient"] == "landscape" for section in sections), sections)
            self.assertGreaterEqual(len({(section["width"], section["height"]) for section in sections}), 2)


if __name__ == "__main__":
    unittest.main()
