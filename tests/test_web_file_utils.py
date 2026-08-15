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

def test_safe_download_filename_output_suffix_defaults() -> None:
    """输出后缀缺失、空值或纯空白时保持历史默认 _排版文件。"""
    assert safe_download_filename("工作报告.docx") == "工作报告_排版文件.docx"
    assert safe_download_filename("工作报告.docx", "") == "工作报告_排版文件.docx"
    assert safe_download_filename("工作报告.docx", None) == "工作报告_排版文件.docx"
    assert safe_download_filename("工作报告.docx", "   ") == "工作报告_排版文件.docx"
    assert safe_download_filename("工作报告.docx", ".") == "工作报告_排版文件.docx"


def test_safe_download_filename_output_suffix_custom() -> None:
    """显式输出后缀追加在文件 stem 之后，最终固定为 .docx。"""
    assert safe_download_filename("工作报告.docx", "_最终版") == "工作报告_最终版.docx"
    assert safe_download_filename("工作报告.docx", "（修订稿）") == "工作报告（修订稿）.docx"
    assert safe_download_filename("工作报告.docx", "_排版") == "工作报告_排版.docx"


def test_safe_download_filename_output_suffix_sanitized() -> None:
    """输出后缀中的危险字符与目录穿越必须被安全处理。"""
    assert safe_download_filename("a.docx", 'a<b:c>d*e?f|g\\h/i') == "aa_b_c_d_e_f_g_h_i.docx"
    assert safe_download_filename("a.docx", "../evil") == "a_evil.docx"
    assert safe_download_filename("a.docx", "..\\evil") == "a_evil.docx"
    assert safe_download_filename("a.docx", "final.docx") == "afinal.docx"
    assert safe_download_filename("a.docx", "x" * 300) == sanitize_filename("a" + "x" * 300 + ".docx")


def test_safe_download_filename_output_suffix_stem_fallback() -> None:
    """原文件名为空时使用 download 作为 stem，后缀仍然生效。"""
    assert safe_download_filename("", "_最终版") == "download_最终版.docx"
