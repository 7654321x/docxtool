from __future__ import annotations

from docxtool.web.responses import (
    auth_error_body,
    json_response_bytes,
    normalize_extra_headers,
    retry_after_headers,
    text_response_bytes,
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


def test_retry_after_headers_are_optional() -> None:
    """传入重试秒数时返回 Retry-After 头，否则返回空列表。"""
    assert retry_after_headers(3) == [("Retry-After", "3")]
    assert retry_after_headers(0) == []


def test_auth_error_body_uses_nested_error_contract() -> None:
    """认证接口错误响应应使用 ok=false 和嵌套 error 合同。"""
    assert auth_error_body("CODE", "message", field="username", reason="bad") == {
        "ok": False,
        "error": {"code": "CODE", "message": "message", "field": "username", "reason": "bad"},
    }
