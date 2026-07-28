import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from docx.enum.text import WD_BREAK

from docxtool.document.engine import export_doc
from docxtool.document.importer import DocxImporter, DocumentData, ParagraphData, ParagraphFeatures
from docxtool.document.style_config import PageSettings, StyleRule, load_rules_and_settings


def _rules():
    return [StyleRule.default_for_row(i) for i in range(10)]


class ProcessingFlagsTest(unittest.TestCase):
    def test_punctuation_disabled_keeps_original_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "source.docx"
            doc = Document()
            doc.add_paragraph("甲:乙,丙.丁")
            doc.save(src)

            data = DocxImporter().load(
                str(src), _rules(), features={"punctuation_enabled": False},
                strict_preservation=False,
            )

            self.assertEqual(data.paragraphs[0].text, "甲:乙,丙.丁")

    def test_punctuation_enabled_removes_fullwidth_space(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "source.docx"
            doc = Document()
            doc.add_paragraph("甲　乙,丙")
            doc.save(src)

            data = DocxImporter().load(
                str(src), _rules(), features={"punctuation_enabled": True},
                strict_preservation=False,
            )

            self.assertEqual(data.paragraphs[0].text, "甲乙，丙")

    def test_smart_mode_applies_only_enabled_punctuation_repairs(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "punctuation.docx"
            document = Document()
            document.add_paragraph("甲:乙,丙.")
            document.save(src)

            enabled = DocxImporter().load(
                str(src),
                _rules(),
                features={
                    "processing": {"strategy": "structural"},
                    "punctuation_enabled": True,
                    "punctuation": {"enabled": True, "mode": "safe"},
                },
            )
            disabled = DocxImporter().load(
                str(src),
                _rules(),
                features={
                    "processing": {"strategy": "structural"},
                    "punctuation_enabled": False,
                    "punctuation": {"enabled": False, "mode": "safe"},
                },
            )

            self.assertEqual(enabled.paragraphs[0].text, "甲：乙，丙。")
            self.assertEqual(disabled.paragraphs[0].text, "甲:乙,丙.")

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

    def test_smart_mode_splits_reliable_structure_without_rewriting_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "fused-structure.docx"
            doc = Document()
            header = doc.add_paragraph()
            for index, text in enumerate((
                "内测发〔2026〕1号",
                "中共内江市东兴区政协党组班子",
                "2025年度民主生活会对照检查材料",
                "区政协办公室主任  李弟弟",
            )):
                header.add_run(text)
                if index < 3:
                    header.add_run().add_break(WD_BREAK.LINE)
            doc.add_paragraph("一、一级标题。这里是应当作为正文保留的完整说明文字。")
            tail = doc.add_paragraph()
            for index, text in enumerate((
                "区政协办公室",
                "2025年十月15日",
                "附件：1.基本情况",
                "2.具体情况",
            )):
                tail.add_run(text)
                if index < 3:
                    tail.add_run().add_break(WD_BREAK.LINE)
            doc.save(src)

            rules, _, features = load_rules_and_settings({"mode": "smart"})
            data = DocxImporter().load(str(src), rules, features=features)

            self.assertEqual(data.processing_strategy, "structural")
            self.assertFalse(data.strict_preservation)
            self.assertEqual(
                [(item.type_id, item.text) for item in data.paragraphs[:6]],
                [
                    ("dispatch_number", "内测发〔2026〕1号"),
                    ("title_cont", "中共内江市东兴区政协党组班子"),
                    ("title_cont", "2025年度民主生活会对照检查材料"),
                    ("role_name", "区政协办公室主任  李弟弟"),
                    ("heading1", "一、一级标题。"),
                    ("body", "这里是应当作为正文保留的完整说明文字。"),
                ],
            )
            self.assertEqual(
                [(item.type_id, item.text) for item in data.paragraphs[-4:]],
                [
                    ("attachment_note", "附件：1.基本情况"),
                    ("attachment_note_item", "2.具体情况"),
                    ("sign_org", "区政协办公室"),
                    ("sign_date", "2025年10月15日"),
                ],
            )

    def test_smart_mode_recovers_speech_title_and_soft_line_body_from_heading_style(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "speech.docx"
            document = Document()
            document.add_paragraph("在区政协九届一次会议闭幕大会上的讲话", style="Heading 1")
            byline = document.add_paragraph()
            byline.add_run("区政协党组书记、主席张三")
            byline.add_run().add_break(WD_BREAK.LINE)
            byline.add_run("（2026年8月27日10:00，会议中心）")
            document.add_paragraph("各位委员、同志们：")
            fused = document.add_paragraph()
            fused.add_run("一、始终坚持党的全面领导")
            fused.add_run().add_break(WD_BREAK.LINE)
            fused.add_run().add_break(WD_BREAK.LINE)
            fused.add_run("要全面加强党的领导，切实提升履职质量。")
            document.save(source)

            rules, _, features = load_rules_and_settings({"mode": "smart"})
            data = DocxImporter().load(str(source), rules, features=features)

            self.assertEqual(
                [(item.type_id, item.text) for item in data.paragraphs],
                [
                    ("title", "在区政协九届一次会议闭幕大会上的讲话"),
                    ("role_name", "区政协党组书记、主席张三"),
                    ("date_line", "（2026年8月27日10:00，会议中心）"),
                    ("addressing", "各位委员、同志们："),
                    ("heading1", "一、始终坚持党的全面领导"),
                    ("body", "要全面加强党的领导，切实提升履职质量。"),
                ],
            )

    def test_smart_mode_removes_only_an_inferred_heading_prefix_from_speech_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "speech-output.docx"
            document = Document()
            document.add_paragraph("一、在区政协九届一次会议闭幕大会上的讲话", style="Heading 1")
            document.add_paragraph("各位委员、同志们：")
            document.save(source)

            rules, _, features = load_rules_and_settings({"mode": "smart"})
            data = DocxImporter().load(str(source), rules, features=features)

            self.assertEqual(data.paragraphs[0].type_id, "title")
            self.assertEqual(data.paragraphs[0].text, "在区政协九届一次会议闭幕大会上的讲话")
            self.assertEqual(data.paragraphs[0].original_text, "一、在区政协九届一次会议闭幕大会上的讲话")

    def test_smart_mode_renumbers_headings_only_when_numbering_is_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "numbering.docx"
            output = Path(tmp) / "numbering-output.docx"
            document = Document()
            for text in (
                "测试材料",
                "一、第一部分",
                "（六）第二层",
                "5.第三层",
                "（6）第四层",
                "正文内容正文内容正文内容。",
            ):
                document.add_paragraph(text)
            document.save(source)

            rules, settings, features = load_rules_and_settings(
                {"mode": "smart", "numbering": {"enabled": True}}
            )
            data = DocxImporter().load(str(source), rules, features=features)
            export_doc(
                data,
                rules,
                settings,
                str(output),
                numbering_options=features["numbering"],
            )

            headings = [
                paragraph.text
                for paragraph in Document(output).paragraphs
                if paragraph.style.style_id in {
                    "DCT-Heading1", "DCT-Heading2", "DCT-Heading3", "DCT-Heading4"
                }
            ]
            self.assertEqual(headings, ["一、第一部分", "（一）第二层", "1.第三层", "（1）第四层"])


if __name__ == "__main__":
    unittest.main()
