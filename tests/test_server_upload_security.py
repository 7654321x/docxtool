import base64
import http.client
import io
import json
import os
import tempfile
import threading
import zipfile
import unittest
from pathlib import Path

from docxtool.web import app as server
from docxtool.security.docx_validator import DocxValidationError, detect_docx_complexity, validate_docx_upload


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


def _validation_limits():
    return {
        "max_upload_bytes": 10 * 1024 * 1024,
        "max_uncompressed_bytes": 100 * 1024 * 1024,
        "max_file_count": 1000,
        "max_xml_bytes": 20 * 1024 * 1024,
        "max_media_bytes": 30 * 1024 * 1024,
        "max_compression_ratio": 100,
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
        validate_docx_upload(_valid_docx_bytes(), **_validation_limits())

    def test_validate_docx_upload_accepts_minimal_valid_archive_path(self):
        archive = _valid_docx_bytes()
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp.write(archive)
            tmp_path = Path(tmp.name)
        try:
            validate_docx_upload(tmp_path, **_validation_limits())
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_validate_docx_upload_rejects_non_zip_bytes_as_invalid_docx(self):
        with self.assertRaises(DocxValidationError) as ctx:
            validate_docx_upload(b"not a zip archive", **_validation_limits())

        self.assertEqual(ctx.exception.code, "INVALID_DOCX")
        self.assertEqual(ctx.exception.status, 400)

    def test_validate_docx_upload_rejects_non_zip_path_as_invalid_docx(self):
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp.write(b"not a zip archive")
            tmp_path = Path(tmp.name)
        try:
            with self.assertRaises(DocxValidationError) as ctx:
                validate_docx_upload(tmp_path, **_validation_limits())
        finally:
            tmp_path.unlink(missing_ok=True)

        self.assertEqual(ctx.exception.code, "INVALID_DOCX")
        self.assertEqual(ctx.exception.status, 400)

    def test_validate_docx_upload_rejects_empty_path_as_invalid_docx(self):
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            with self.assertRaises(DocxValidationError) as ctx:
                validate_docx_upload(tmp_path, **_validation_limits())
        finally:
            tmp_path.unlink(missing_ok=True)

        self.assertEqual(ctx.exception.code, "INVALID_DOCX")
        self.assertEqual(ctx.exception.status, 400)

    def test_validate_docx_upload_rejects_missing_ooxml_members(self):
        bio = io.BytesIO()
        with zipfile.ZipFile(bio, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", "<Types />")

        with self.assertRaises(DocxValidationError) as ctx:
            validate_docx_upload(bio.getvalue(), **_validation_limits())

        self.assertEqual(ctx.exception.code, "INVALID_DOCX")
        self.assertIn("缺少必要文件", ctx.exception.message)

    def test_validate_docx_upload_rejects_path_traversal_members(self):
        with self.assertRaises(DocxValidationError) as ctx:
            validate_docx_upload(_valid_docx_bytes([("../evil.txt", "boom")]), **_validation_limits())

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

    def test_detect_docx_complexity_ignores_invalid_zip_path(self):
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp.write(b"not a zip archive")
            tmp_path = Path(tmp.name)
        try:
            warnings = detect_docx_complexity(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

        self.assertEqual(warnings, [])

    def test_upload_non_zip_docx_returns_400_and_cleans_temp_dir(self):
        old_db = server._DB_PATH
        old_runtime_tmp = server.RUNTIME_TMP_DIR
        old_log_dir = server.LOG_DIR
        old_output_dir = server.OUTPUT_DIR
        old_proxy_secret = server.PROXY_SECRET
        old_admin_token = server.ADMIN_TOKEN
        httpd = None
        thread = None
        conn = None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_tmp = root / "runtime" / "tmp"
            runtime_tmp.mkdir(parents=True)
            server._DB_PATH = str(root / "stats.db")
            server.RUNTIME_TMP_DIR = str(runtime_tmp)
            server.LOG_DIR = str(root / "logs")
            server.OUTPUT_DIR = str(root / "outputs")
            server.PROXY_SECRET = ""
            server.ADMIN_TOKEN = ""
            os.makedirs(server.LOG_DIR, exist_ok=True)
            os.makedirs(server.OUTPUT_DIR, exist_ok=True)
            server._sql_init()
            with server.RATE_LOCK:
                server.RATE_LIMIT.clear()
            try:
                httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
                thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                thread.start()
                port = httpd.server_address[1]
                body = b"not a zip archive"
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request(
                    "PUT",
                    "/upload",
                    body=body,
                    headers={
                        "Content-Length": str(len(body)),
                        "Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        "Host": f"127.0.0.1:{port}",
                        "X-Filename": "bad.docx",
                    },
                )
                response = conn.getresponse()
                payload = json.loads(response.read().decode("utf-8"))

                self.assertEqual(response.status, 400)
                self.assertEqual(payload["code"], "INVALID_DOCX")
                self.assertNotEqual(payload["code"], "INTERNAL_ERROR")
                self.assertFalse(any(runtime_tmp.iterdir()))
            finally:
                if conn is not None:
                    conn.close()
                if httpd is not None:
                    httpd.shutdown()
                    httpd.server_close()
                if thread is not None:
                    thread.join(timeout=5)
                server._DB_PATH = old_db
                server.RUNTIME_TMP_DIR = old_runtime_tmp
                server.LOG_DIR = old_log_dir
                server.OUTPUT_DIR = old_output_dir
                server.PROXY_SECRET = old_proxy_secret
                server.ADMIN_TOKEN = old_admin_token
                with server.RATE_LOCK:
                    server.RATE_LIMIT.clear()

    def test_upload_invalid_format_config_returns_field_and_reason(self):
        old_db = server._DB_PATH
        old_runtime_tmp = server.RUNTIME_TMP_DIR
        old_log_dir = server.LOG_DIR
        old_output_dir = server.OUTPUT_DIR
        old_proxy_secret = server.PROXY_SECRET
        old_admin_token = server.ADMIN_TOKEN
        httpd = None
        thread = None
        conn = None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_tmp = root / "runtime" / "tmp"
            runtime_tmp.mkdir(parents=True)
            server._DB_PATH = str(root / "stats.db")
            server.RUNTIME_TMP_DIR = str(runtime_tmp)
            server.LOG_DIR = str(root / "logs")
            server.OUTPUT_DIR = str(root / "outputs")
            server.PROXY_SECRET = ""
            server.ADMIN_TOKEN = ""
            os.makedirs(server.LOG_DIR, exist_ok=True)
            os.makedirs(server.OUTPUT_DIR, exist_ok=True)
            server._sql_init()
            with server.RATE_LOCK:
                server.RATE_LIMIT.clear()
            try:
                httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
                thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                thread.start()
                port = httpd.server_address[1]
                body = _valid_docx_bytes()
                config = {"styles": [{} for _ in range(6)] + [{"name": "数字", "size": ""}], "page": {}}
                headers = {
                    "Content-Length": str(len(body)),
                    "Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "Host": f"127.0.0.1:{port}",
                    "X-Filename": "format-config.docx",
                    **_format_config_headers(config),
                }
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("PUT", "/upload", body=body, headers=headers)
                response = conn.getresponse()
                payload = json.loads(response.read().decode("utf-8"))

                self.assertEqual(response.status, 400)
                self.assertEqual(payload["code"], "FORMAT_CONFIG_INVALID")
                self.assertEqual(payload["field"], "styles[6].size")
                self.assertEqual(payload["reason"], "不能为空")
                self.assertEqual(payload["error"], "styles[6].size: 不能为空")
                self.assertNotIn("Traceback", json.dumps(payload, ensure_ascii=False))
                self.assertNotIn(str(root), json.dumps(payload, ensure_ascii=False))
            finally:
                if conn is not None:
                    conn.close()
                if httpd is not None:
                    httpd.shutdown()
                    httpd.server_close()
                if thread is not None:
                    thread.join(timeout=5)
                server._DB_PATH = old_db
                server.RUNTIME_TMP_DIR = old_runtime_tmp
                server.LOG_DIR = old_log_dir
                server.OUTPUT_DIR = old_output_dir
                server.PROXY_SECRET = old_proxy_secret
                server.ADMIN_TOKEN = old_admin_token
                with server.RATE_LOCK:
                    server.RATE_LIMIT.clear()

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
