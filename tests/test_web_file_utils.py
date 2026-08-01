from docxtool.web import app as server
from docxtool.web.file_utils import (
    content_disposition_filename,
    is_safe_uuid,
    safe_download_filename,
    safe_file_identifier,
    sanitize_filename,
    sanitize_internal_error_detail,
)


def test_file_utils_sanitize_names_and_download_headers() -> None:
    """文件名工具传入危险名称后，应返回安全文件名和下载响应头。"""
    assert sanitize_filename("../CON?.docx") == "_CON_.docx"
    assert safe_download_filename("") == "download_排版文件.docx"

    header = content_disposition_filename("材料 排版结果.docx")

    assert header.startswith('attachment; filename="')
    assert "filename*=UTF-8''" in header


def test_file_utils_identifiers_and_redaction_are_stable() -> None:
    """文件工具传入文件名和错误文本后，应返回稳定标识和脱敏内容。"""
    assert safe_file_identifier("a.docx") == server._safe_file_identifier("a.docx")
    assert is_safe_uuid("12345678-1234-1234-1234-1234567890ab")
    assert not is_safe_uuid("../bad")

    detail = sanitize_internal_error_detail(r"secret=abc C:\private\file.docx")

    assert "abc" not in detail
    assert "C:\\private" not in detail
    assert "[local-path]" in detail


def test_file_utils_match_app_facade() -> None:
    """新文件工具模块应与 web.app 旧私有入口保持兼容。"""
    name = "../CON?.docx"

    assert sanitize_filename(name) == server._sanitize_filename(name)
    assert safe_download_filename(name) == server._safe_download_filename(name)
    assert content_disposition_filename(name) == server._content_disposition_filename(name)
