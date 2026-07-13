import logging
import unittest

from docxtool.document.importer import DetectionContext, ParagraphFeatures, detect_paragraph_type
from docxtool.document.style_config import StyleRule, logger


def _rules():
    return [StyleRule.default_for_row(i) for i in range(10)]


class ReportHeadingKeywordsTest(unittest.TestCase):
    def setUp(self):
        logger.setLevel(logging.ERROR)

    def test_five_years_report_heading_matches_one_year_behavior(self):
        ctx = DetectionContext(doc_mode="REPORT", has_seen_body=True, prev_type_id="addressing")
        type_id, meta, prefix = detect_paragraph_type(
            "五年来。测试正文", ParagraphFeatures(text="五年来。测试正文"), ctx, _rules()
        )

        self.assertEqual(type_id, "heading1_report")
        self.assertEqual(prefix, "")
        self.assertTrue(meta["heading1_report_split"])

    def test_numbered_five_years_report_heading_keeps_prefix_for_stripping(self):
        ctx = DetectionContext(doc_mode="REPORT", has_seen_body=True, prev_type_id="addressing")
        type_id, meta, prefix = detect_paragraph_type(
            "一、五年来。测试正文", ParagraphFeatures(text="一、五年来。测试正文"), ctx, _rules()
        )

        self.assertEqual(type_id, "heading1_report")
        self.assertEqual(prefix, "一、")
        self.assertTrue(meta["heading1_report_split"])


if __name__ == "__main__":
    unittest.main()
