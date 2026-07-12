import logging
import tempfile
import unittest
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

from engine import export_doc
from importer import DocumentData, ParagraphData, ParagraphFeatures
from style_config import PageSettings, StyleRule, logger


def _rules():
    return [StyleRule.default_for_row(i) for i in range(10)]


def _body_font(run):
    rPr = run._element.rPr
    rFonts = rPr.rFonts if rPr is not None else None
    return rFonts.get(qn("w:eastAsia")) if rFonts is not None else None


def _spacing_after_lines(paragraph):
    spacing = paragraph._element.get_or_add_pPr().find(qn("w:spacing"))
    return spacing.get(qn("w:afterLines")) if spacing is not None else None


class EngineHeadingSpacingTest(unittest.TestCase):
    def setUp(self):
        logger.setLevel(logging.ERROR)
        self.tmp = tempfile.TemporaryDirectory()
        self.out = str(Path(self.tmp.name) / "out.docx")

    def tearDown(self):
        self.tmp.cleanup()

    def _export(self, paragraphs):
        doc_data = DocumentData(paragraphs=paragraphs, filepath="input.docx")
        export_doc(doc_data, _rules(), PageSettings(), self.out)
        return Document(self.out)

    def test_heading1_period_splits_body_to_next_paragraph(self):
        doc = self._export([
            ParagraphData(
                text="一级标题。这里是正文内容这里是正文内容",
                type_id="heading1",
                original_text="一、一级标题。这里是正文内容这里是正文内容",
                features=ParagraphFeatures(),
                meta={"numbering": "一、"},
            )
        ])

        heading = doc.paragraphs[0]
        body = doc.paragraphs[1]

        self.assertEqual(heading.text, "一、一级标题")
        self.assertNotIn("。", heading.text)
        self.assertEqual(body.text, "这里是正文内容这里是正文内容")
        self.assertFalse(body.runs[-1].bold)
        self.assertEqual(_body_font(body.runs[-1]), "仿宋_GB2312")

    def test_head_area_inserts_blank_line_before_body_or_heading1(self):
        cases = [
            ("title", "正文内容正文内容。"),
            ("title_cont", "一、一级标题"),
            ("author_line", "一、一级标题"),
            ("role_name", "正文内容正文内容。"),
        ]
        for head_type, next_text in cases:
            with self.subTest(head_type=head_type, next_text=next_text):
                next_type = "heading1" if next_text.startswith("一、") else "body"
                doc = self._export([
                    ParagraphData(
                        text="总题目" if head_type != "author_line" else "姓名",
                        type_id=head_type,
                        original_text="总题目",
                        features=ParagraphFeatures(),
                        meta={"is_title": head_type == "title"},
                    ),
                    ParagraphData(
                        text=next_text.replace("一、", ""),
                        type_id=next_type,
                        original_text=next_text,
                        features=ParagraphFeatures(),
                        meta={"numbering": "一、"} if next_type == "heading1" else {},
                    ),
                ])

                self.assertEqual(doc.paragraphs[1].text, "")

    def test_date_line_uses_spacing_after_without_blank_paragraph(self):
        doc = self._export([
            ParagraphData(
                text="（2026年7月  日）",
                type_id="date_line",
                original_text="（2026年7月  日）",
                features=ParagraphFeatures(),
                meta={},
            ),
            ParagraphData(
                text="正文内容正文内容。",
                type_id="body",
                original_text="正文内容正文内容。",
                features=ParagraphFeatures(),
                meta={},
            ),
        ])

        self.assertEqual([p.text for p in doc.paragraphs[:2]], ["（2026年7月  日）", "正文内容正文内容。"])
        self.assertEqual(_spacing_after_lines(doc.paragraphs[0]), "100")

    def test_role_name_and_date_line_are_adjacent(self):
        doc = self._export([
            ParagraphData(
                text="区政协副主席   杨明远",
                type_id="role_name",
                original_text="区政协副主席   杨明远",
                features=ParagraphFeatures(),
                meta={},
            ),
            ParagraphData(
                text="（2026年7月  日）",
                type_id="date_line",
                original_text="（2026年7月  日）",
                features=ParagraphFeatures(),
                meta={},
            ),
            ParagraphData(
                text="正文内容正文内容。",
                type_id="body",
                original_text="正文内容正文内容。",
                features=ParagraphFeatures(),
                meta={},
            ),
        ])

        self.assertEqual(
            [p.text for p in doc.paragraphs[:3]],
            ["区政协副主席   杨明远", "（2026年7月  日）", "正文内容正文内容。"],
        )
        self.assertIn(_spacing_after_lines(doc.paragraphs[0]), (None, "0"))
        self.assertEqual(_spacing_after_lines(doc.paragraphs[1]), "100")

    def test_overlapping_numbered_and_report_bold_does_not_duplicate_text(self):
        text = (
            "一是加强理论武装，把牢正确履职方向。"
            "坚持把学习贯彻习近平总书记关于树立和践行正确政绩观的重要论述作为重要政治任务。"
        )

        doc = self._export([
            ParagraphData(
                text=text,
                type_id="body",
                original_text=text,
                features=ParagraphFeatures(),
                meta={"numbered_bold": True, "report_first_sentence_bold": True},
            )
        ])

        self.assertEqual(doc.paragraphs[0].text, text)
        self.assertEqual(doc.paragraphs[0].text.count("一是加强理论武装"), 1)


if __name__ == "__main__":
    unittest.main()
