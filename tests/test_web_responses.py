from __future__ import annotations

from docxtool.web.responses import (
    auth_error_body,
    docx_download_headers,
    file_expired_error,
    file_not_ready_error,
    incomplete_upload_error,
    internal_server_error,
    invalid_task_id_error,
    json_error_body,
    json_response_headers,
    json_response_bytes,
    log_not_found_error,
    normalize_extra_headers,
    optional_set_cookie_headers,
    queue_full_error,
    queue_full_error_message,
    queued_upload_body,
    redirect_headers,
    retry_after_headers,
    security_headers,
    text_response_headers,
    text_response_bytes,
    upload_failed_error,
    upload_file_too_large_error,
    upload_ip_banned_error,
    upload_limit_exceeded_error,
    upload_rate_limited_error,
    upload_timeout_error,
    task_not_found_error,
)


def test_normalize_extra_headers_accepts_mapping_or_pairs() -> None:
    """附加响应头归一化应支持 dict 和元组序列，并统一转为字符串。"""
    assert normalize_extra_headers({"X-Test": 1}) == [("X-Test", "1")]
    assert normalize_extra_headers([("Set-Cookie", "a=b")]) == [("Set-Cookie", "a=b")]
    assert normalize_extra_headers(None) == []


def test_text_and_json_response_bytes_encode_utf8() -> None:
    """文本和 JSON 响应编码应返回 UTF-8 bytes，JSON 保留中文并兼容非字符串对象。"""
    assert text_response_bytes("公文") == "公文".encode("utf-8")
    assert json_response_bytes({"name": "公文", "value": object()}).startswith(b'{"name":')


def test_security_and_content_headers_are_stable() -> None:
    """默认安全头和基础响应头应保持兼容字段和值。"""
    assert security_headers() == [
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
        ("X-XSS-Protection", "1; mode=block"),
    ]
    assert text_response_headers("text/html", 6, {"X-Test": 1}) == [
        ("Content-Type", "text/html; charset=utf-8"),
        ("Content-Length", "6"),
        ("X-Test", "1"),
    ]
    assert json_response_headers(2) == [("Content-Type", "application/json"), ("Content-Length", "2")]


def test_docx_download_headers_use_word_mime_and_size() -> None:
    """DOCX 下载响应头应包含 Word MIME、Content-Disposition 和字节长度。"""
    assert docx_download_headers("attachment; filename=a.docx", 12) == [
        ("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("Content-Disposition", "attachment; filename=a.docx"),
        ("Content-Length", "12"),
    ]


def test_retry_after_headers_are_optional() -> None:
    """传入重试秒数时返回 Retry-After 头，否则返回空列表。"""
    assert retry_after_headers(3) == [("Retry-After", "3")]
    assert retry_after_headers(0) == []


def test_redirect_headers_prepend_location_and_keep_extra_headers() -> None:
    """重定向头应先发送 Location，再保留调用方附加的兼容响应头。"""
    assert redirect_headers("/admin", {"Set-Cookie": "a=b"}) == [
        ("Location", "/admin"),
        ("Set-Cookie", "a=b"),
    ]


def test_optional_set_cookie_headers_returns_none_when_absent() -> None:
    """可选 Cookie 头应在值为空时返回 None，有值时返回 Set-Cookie 列表。"""
    assert optional_set_cookie_headers("") is None
    assert optional_set_cookie_headers("a=b") == [("Set-Cookie", "a=b")]


def test_queued_upload_body_merges_task_info_and_optional_warnings() -> None:
    """上传成功响应体应包含任务 ID、queued 状态、入队信息和可选兼容警告。"""
    assert queued_upload_body("task-1", {"queued_at": 123}) == {
        "task_id": "task-1",
        "status": "queued",
        "queued_at": 123,
    }
    assert queued_upload_body("task-1", {"queued_at": 123}, ["warning"])["compatibility_warnings"] == ["warning"]


def test_queue_full_error_message_extracts_user_text_or_default() -> None:
    """队列满异常应提取冒号后的用户提示，无冒号时返回默认繁忙提示。"""
    assert queue_full_error_message(OverflowError("QUEUE_FULL: 请稍后")) == "请稍后"
    assert queue_full_error_message(OverflowError("busy")) == "服务器繁忙，请稍后再试"


def test_upload_preflight_errors_are_stable() -> None:
    """上传前置限制错误应返回稳定错误码、提示和状态码。"""
    assert upload_ip_banned_error() == ("IP_BANNED", "该 IP 已被禁止访问", 403)
    assert upload_limit_exceeded_error() == (
        "UPLOAD_LIMIT_EXCEEDED",
        "当前 IP 在该时间段内排版次数已达上限，请稍后再试",
        429,
    )
    assert upload_rate_limited_error() == ("RATE_LIMITED", "请求过于频繁，请稍后再试", 429)


def test_upload_transfer_errors_are_stable() -> None:
    """上传传输阶段错误应返回稳定错误码、提示和状态码。"""
    assert upload_file_too_large_error() == ("FILE_TOO_LARGE", "文件过大或无内容", 413)
    assert upload_timeout_error() == ("UPLOAD_TIMEOUT", "文件上传超时", 408)
    assert upload_failed_error() == ("UPLOAD_FAILED", "文件上传失败，请重试", 400)
    assert incomplete_upload_error() == ("INCOMPLETE_UPLOAD", "读取不完整", 400)
    assert queue_full_error(OverflowError("QUEUE_FULL: 请稍后")) == ("QUEUE_FULL", "请稍后", 503)
    assert internal_server_error() == ("INTERNAL_ERROR", "服务器处理失败，请稍后重试", 500)


def test_task_file_and_log_errors_are_stable() -> None:
    """任务状态、下载和日志接口错误应返回稳定错误码、提示和状态码。"""
    assert invalid_task_id_error() == ("INVALID_TASK_ID", "无效的任务 ID", 400)
    assert task_not_found_error() == ("TASK_NOT_FOUND", "任务不存在或已过期", 404)
    assert file_not_ready_error() == ("FILE_NOT_READY", "文件未就绪", 400)
    assert file_expired_error() == ("FILE_EXPIRED", "文件已过期", 410)
    assert log_not_found_error() == ("LOG_NOT_FOUND", "日志不存在", 404)
    assert log_not_found_error(expired=True) == ("LOG_NOT_FOUND", "日志不存在或已过期", 404)


def test_auth_error_body_uses_nested_error_contract() -> None:
    """认证接口错误响应应使用 ok=false 和嵌套 error 合同。"""
    assert auth_error_body("CODE", "message", field="username", reason="bad") == {
        "ok": False,
        "error": {"code": "CODE", "message": "message", "field": "username", "reason": "bad"},
    }


def test_json_error_body_selects_auth_or_legacy_contract() -> None:
    """JSON 错误体应按路由类型选择认证合同或旧接口合同。"""
    def legacy_error_body(code: str, message: str, *, field: str = "", reason: str = "") -> dict:
        """测试回调：传入错误字段，返回旧接口扁平错误体。"""
        return {"code": code, "error": message, "field": field, "reason": reason}

    assert json_error_body(
        auth_route=True,
        code="BAD",
        message="失败",
        field="username",
        legacy_error_body=legacy_error_body,
    ) == {"ok": False, "error": {"code": "BAD", "message": "失败", "field": "username"}}
    assert json_error_body(
        auth_route=False,
        code="BAD",
        message="失败",
        reason="invalid",
        legacy_error_body=legacy_error_body,
    ) == {"code": "BAD", "error": "失败", "field": "", "reason": "invalid"}
