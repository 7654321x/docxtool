import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from docx import Document

from docxtool.document.engine import export_doc
from docxtool.document.importer import DocxImporter, DocumentData, ParagraphData, ParagraphFeatures
from docxtool.document.style_config import PageSettings, StyleRule


def _rules():
    return [StyleRule.default_for_row(i) for i in range(10)]


class ProcessingFlagsTest(unittest.TestCase):
    def test_punctuation_disabled_keeps_original_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "source.docx"
            doc = Document()
            doc.add_paragraph("甲:乙,丙.丁")
            doc.save(src)

            data = DocxImporter().load(str(src), _rules(), features={"punctuation_enabled": False})

            self.assertEqual(data.paragraphs[0].text, "甲:乙,丙.丁")

    def test_punctuation_enabled_removes_fullwidth_space(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "source.docx"
            doc = Document()
            doc.add_paragraph("甲　乙,丙")
            doc.save(src)

            data = DocxImporter().load(str(src), _rules(), features={"punctuation_enabled": True})

            self.assertEqual(data.paragraphs[0].text, "甲乙，丙")

    def test_page_number_disabled_skips_footer_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.docx"
            data = DocumentData(
                paragraphs=[
                    ParagraphData("正文内容", "body", "正文内容", ParagraphFeatures()),
                ],
                filepath="input.docx",
            )
            export_doc(data, _rules(), PageSettings(), str(out), page_number_enabled=False)

            with ZipFile(out) as zf:
                names = zf.namelist()
                footer_names = [name for name in names if name.startswith("word/footer")]
                self.assertEqual(footer_names, [])


if __name__ == "__main__":
    unittest.main()
