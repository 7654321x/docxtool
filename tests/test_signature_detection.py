import logging
import tempfile
import unittest
from pathlib import Path

from docx import Document

from docxtool.document.importer import DocxImporter
from docxtool.document.style_config import StyleRule, logger


def _rules():
    return [StyleRule.default_for_row(i) for i in range(10)]


class SignatureDetectionTest(unittest.TestCase):
    def setUp(self):
        logger.setLevel(logging.ERROR)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _load_lines(self, lines):
        doc = Document()
        for line in lines:
            doc.add_paragraph(line)
        path = self.root / "input.docx"
        doc.save(path)
        return DocxImporter().load(str(path), _rules())

    def test_normal_document_signature_after_body(self):
        data = self._load_lines([
            "总题目",
            "一、一级标题",
            "这里是正文内容这里是正文内容这里是正文内容。",
            "区政府人才保障工作组",
            "2025年十月15日",
        ])

        self.assertEqual([p.type_id for p in data.paragraphs[-2:]], ["sign_org", "sign_date"])
        self.assertEqual(data.paragraphs[-2].text, "区政府人才保障工作组")
        self.assertEqual(data.paragraphs[-1].text, "2025年10月15日")

    def test_attachment_note_signature_and_attachment_page_flow(self):
        data = self._load_lines([
            "总题目",
            "一、一级标题",
            "这里是正文内容这里是正文内容这里是正文内容。",
            "附件：1. 基本情况",
            "2. 具体情况",
            "区政府人才保障工作组",
            "2025年10月15日",
            "附件1",
            "标题",
            "测试正文测试正文。",
        ])

        self.assertEqual(
            [p.type_id for p in data.paragraphs[-7:]],
            [
                "attachment_note",
                "attachment_note_item",
                "sign_org",
                "sign_date",
                "attachment_page_mark",
                "attachment_title",
                "attachment_body",
            ],
        )
        self.assertEqual(data.paragraphs[-4].text, "2025年10月15日")
        self.assertEqual(data.paragraphs[-3].text, "附件 1")

    def test_chinese_year_signature_date_is_normalized(self):
        data = self._load_lines([
            "总题目",
            "一、一级标题",
            "这里是正文内容这里是正文内容这里是正文内容。",
            "内江市东兴区人民政府办公室",
            "二〇二五年十月十五日",
        ])

        self.assertEqual([p.type_id for p in data.paragraphs[-2:]], ["sign_org", "sign_date"])
        self.assertEqual(data.paragraphs[-1].text, "2025年10月15日")

    def test_long_role_and_name_line_is_detected_in_head_area(self):
        data = self._load_lines([
            "2026年度测试材料",
            "区政协办公室党组书记、主任  李弟弟",
            "（2026年7月14日）",
            "一、一级标题",
            "这里是正文内容这里是正文内容这里是正文内容。",
        ])

        self.assertEqual(data.paragraphs[1].type_id, "role_name")
        self.assertEqual(data.paragraphs[1].text, "区政协办公室党组书记、主任  李弟弟")

    def test_office_director_and_name_line_is_detected_in_head_area(self):
        data = self._load_lines([
            "2026年度测试材料",
            "区政协办公室主任  李弟弟",
            "（2026年7月14日）",
            "一、一级标题",
            "这里是正文内容这里是正文内容这里是正文内容。",
        ])

        self.assertEqual(data.paragraphs[1].type_id, "role_name")
        self.assertEqual(data.paragraphs[1].text, "区政协办公室主任  李弟弟")

    def test_contact_line_before_date_is_not_signature(self):
        data = self._load_lines([
            "总题目",
            "一、一级标题",
            "这里是正文内容这里是正文内容这里是正文内容。",
            "联系人：张三",
            "2025年10月15日",
        ])

        self.assertNotEqual(data.paragraphs[-2].type_id, "sign_org")
        self.assertNotEqual(data.paragraphs[-1].type_id, "sign_date")

    def test_unpunctuated_body_summary_before_date_is_not_signature(self):
        data = self._load_lines([
            "总题目",
            "一、一级标题",
            "这里是正文内容这里是正文内容这里是正文内容。",
            "以上情况请审阅",
            "2025年10月15日",
        ])

        self.assertNotEqual(data.paragraphs[-2].type_id, "sign_org")
        self.assertNotEqual(data.paragraphs[-1].type_id, "sign_date")

    def test_signature_date_before_attachment_note_is_reordered(self):
        data = self._load_lines([
            "总题目",
            "一、存在的问题",
            "（一）带头强化政治忠诚、提高政治能力方面。",
            "这里是正文内容这里是正文内容这里是正文内容。",
            "（五）扛牢政治责任，推进全面从严治党。坚决扛起管党治党主体责任，严格落实全面从严治党相关规定。",
            "六、区政协办",
            "2025年十月15日",
            "附件：1. 基本情况",
            "2. 具体情况",
            "3. 超级情况",
            "附件1",
            "标题",
            "测试正文测试正文。",
        ])

        self.assertEqual(
            [p.type_id for p in data.paragraphs[-8:]],
            [
                "attachment_note",
                "attachment_note_item",
                "attachment_note_item",
                "sign_org",
                "sign_date",
                "attachment_page_mark",
                "attachment_title",
                "attachment_body",
            ],
        )
        self.assertEqual(data.paragraphs[-5].text, "区政协办")
        self.assertEqual(data.paragraphs[-4].text, "2025年10月15日")


if __name__ == "__main__":
    unittest.main()
