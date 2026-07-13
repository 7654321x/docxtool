import base64
import io
import json
import tempfile
import zipfile
import unittest
from pathlib import Path

import server
from security.docx_validator import DocxValidationError, detect_docx_complexity, validate_docx_upload


def _valid_docx_bytes(extra_members=None, document_xml=None):
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<?xml version='1.0' encoding='UTF-8'?><Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'></Types>")
        zf.writestr("_rels/.rels", "<?xml version='1.0' encoding='UTF-8'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'></Relationships>")
        zf.writestr(
            "word/document.xml",
            document_xml or "<?xml version='1.0' encoding='UTF-8'?><w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'></w:document>",
        )
        for name, content in (extra_members or []):
            zf.writestr(name, content)
    return bio.getvalue()


def _format_config_headers(config):
    raw = json.dumps(config, ensure_ascii=False).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return {
        "X-Format-Config": encoded,
        "X-Format-Config-Encoding": "base64url-json",
    }


class UploadSecurityTest(unittest.TestCase):
    def test_sanitize_filename_never_escapes_output_rules(self):
        self.assertEqual(server._sanitize_filename("../CON?.docx"), "_CON_.docx")
        self.assertEqual(server._safe_download_filename(""), "download_排版文件.docx")

    def test_task_output_path_is_task_scoped(self):
        path = server._task_output_path("task-123")
        self.assertIn("task-123", path)
        self.assertTrue(path.endswith("result.docx"))

    def test_validate_docx_upload_accepts_minimal_valid_archive(self):
        validate_docx_upload(
            _valid_docx_bytes(),
            max_upload_bytes=10 * 1024 * 1024,
            max_uncompressed_bytes=100 * 1024 * 1024,
            max_file_count=1000,
            max_xml_bytes=20 * 1024 * 1024,
            max_media_bytes=30 * 1024 * 1024,
            max_compression_ratio=100,
        )

    def test_validate_docx_upload_rejects_path_traversal_members(self):
        with self.assertRaises(DocxValidationError) as ctx:
            validate_docx_upload(
                _valid_docx_bytes([("../evil.txt", "boom")]),
                max_upload_bytes=10 * 1024 * 1024,
                max_uncompressed_bytes=100 * 1024 * 1024,
                max_file_count=1000,
                max_xml_bytes=20 * 1024 * 1024,
                max_media_bytes=30 * 1024 * 1024,
                max_compression_ratio=100,
            )

        self.assertEqual(ctx.exception.code, "INVALID_DOCX")
        self.assertIn("非法路径", ctx.exception.message)

    def test_detect_docx_complexity_reports_headers_and_textbox_risks(self):
        archive = _valid_docx_bytes(
            [("word/header1.xml", "<w:hdr xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'></w:hdr>")],
            document_xml=(
                "<?xml version='1.0' encoding='UTF-8'?>"
                "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>"
                "<w:body><w:p><w:r><w:t>hello</w:t></w:r></w:p>"
                "<w:p><w:r><w:drawing/><w:txbxContent/></w:r></w:p></w:body></w:document>"
            ),
        )
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp.write(archive)
            tmp_path = Path(tmp.name)
        try:
            warnings = detect_docx_complexity(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

        self.assertTrue(any("页眉" in item for item in warnings))
        self.assertTrue(any("文本框" in item or "图片" in item for item in warnings))

    def test_decode_format_config_rejects_invalid_numeric_fields(self):
        headers = _format_config_headers({
            "styles": [],
            "page": {"width_cm": "NaN"},
        })

        with self.assertRaisesRegex(ValueError, "FORMAT_CONFIG_INVALID: page.width_cm"):
            server._decode_format_config(headers)

    def test_decode_format_config_accepts_legacy_valid_numeric_strings(self):
        headers = _format_config_headers({
            "styles": [{"size": "三号", "indent": "2"}],
            "page": {
                "width_cm": "21",
                "height_cm": "29.7",
                "margin_top_cm": "3.7",
                "margin_bottom_cm": "3.5",
                "margin_left_cm": "2.8",
                "margin_right_cm": "2.6",
                "lines_per_page": "22",
                "chars_per_line": "28",
                "line_spacing_pt": "28",
            },
        })

        config = server._decode_format_config(headers)

        self.assertEqual(config["page"]["width_cm"], "21")


if __name__ == "__main__":
    unittest.main()
