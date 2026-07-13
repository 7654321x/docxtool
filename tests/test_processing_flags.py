import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

from engine import export_doc
import engine._core as core
from importer import DocxImporter, DocumentData, ParagraphData, ParagraphFeatures
from style_config import PageSettings, StyleRule


def _rules():
    return [StyleRule.default_for_row(i) for i in range(10)]


def _xml_attr(element, attr):
    return element.get(qn(attr)) if element is not None else None


def _run_ascii_font(run):
    r_pr = run._element.rPr
    r_fonts = r_pr.rFonts if r_pr is not None else None
    return _xml_attr(r_fonts, 'w:ascii')


def _run_size_half_points(run):
    r_pr = run._element.rPr
    size = r_pr.find(qn('w:sz')) if r_pr is not None else None
    return _xml_attr(size, 'w:val')


class ProcessingFlagsTest(unittest.TestCase):
    def test_punctuation_disabled_keeps_original_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'source.docx'
            doc = Document()
            doc.add_paragraph('“引用”测试')
            doc.save(src)

            data = DocxImporter().load(str(src), _rules(), features={'punctuation_enabled': False})

            self.assertEqual(data.paragraphs[0].text, '“引用”测试')

    def test_page_number_disabled_skips_footer_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out.docx'
            data = DocumentData(
                paragraphs=[
                    ParagraphData('正文内容', 'body', '正文内容', ParagraphFeatures()),
                ],
                filepath='input.docx',
            )
            export_doc(data, _rules(), PageSettings(), str(out), page_number_enabled=False)

            with ZipFile(out) as zf:
                footer_names = [name for name in zf.namelist() if name.startswith('word/footer')]
                self.assertEqual(footer_names, [])

    def test_page_number_pattern_uses_page_and_numpages_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out.docx'
            rules = _rules()
            rules[8].numbering_pattern = '第 1 页 / 共 n 页'
            rules[8].alignment = '左对齐'
            data = DocumentData(
                paragraphs=[ParagraphData('正文内容', 'body', '正文内容', ParagraphFeatures())],
                filepath='input.docx',
            )

            export_doc(data, rules, PageSettings(), str(out), page_number_enabled=True)

            doc = Document(out)
            self.assertEqual(doc.sections[0].footer.paragraphs[0].alignment, WD_ALIGN_PARAGRAPH.LEFT)

            with ZipFile(out) as zf:
                footer_xml = zf.read('word/footer1.xml').decode('utf-8')
                self.assertIn(' PAGE ', footer_xml)
                self.assertIn(' NUMPAGES ', footer_xml)
                self.assertIn('第 ', footer_xml)
                self.assertIn(' / 共 ', footer_xml)
                self.assertIn(' 页', footer_xml)

    def test_digit_and_latin_rules_apply_distinct_fonts_and_sizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out.docx'
            rules = _rules()
            rules[6].font = 'Arial'
            rules[6].font_size_label = '小四'
            rules[6].font_size_pt = 12.0
            rules[7].font = 'Calibri'
            rules[7].font_size_label = '五号'
            rules[7].font_size_pt = 10.5
            data = DocumentData(
                paragraphs=[ParagraphData('A1测试B2', 'body', 'A1测试B2', ParagraphFeatures())],
                filepath='input.docx',
            )

            export_doc(data, rules, PageSettings(), str(out), page_number_enabled=False)

            doc = Document(out)
            runs = {run.text: run for run in doc.paragraphs[0].runs if run.text}
            self.assertEqual(_run_ascii_font(runs['1']), 'Arial')
            self.assertEqual(_run_size_half_points(runs['1']), '24')
            self.assertEqual(_run_ascii_font(runs['A']), 'Calibri')
            self.assertEqual(_run_size_half_points(runs['A']), '21')
            self.assertEqual(_run_ascii_font(runs['B']), 'Calibri')
            self.assertEqual(_run_ascii_font(runs['2']), 'Arial')

    def test_export_does_not_rewrite_superscript_runs_to_brackets(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out.docx'
            data = DocumentData(
                paragraphs=[ParagraphData('正文内容', 'body', '正文内容', ParagraphFeatures())],
                filepath='input.docx',
            )

            with patch.object(core, '_apply_universal_superscript', side_effect=AssertionError('unexpected call')):
                export_doc(data, _rules(), PageSettings(), str(out), page_number_enabled=False)

            self.assertTrue(out.exists())


if __name__ == '__main__':
    unittest.main()
