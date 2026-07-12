import base64
import logging
import sys
import tempfile
import unittest
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

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


if __name__ == "__main__":
    unittest.main()
