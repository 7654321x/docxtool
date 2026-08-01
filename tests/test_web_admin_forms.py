from __future__ import annotations

from docxtool.web.admin_forms import parse_admin_login_token, parse_form_body


def test_parse_form_body_returns_last_value_for_each_field() -> None:
    """管理员表单模块传入 URL 编码 bytes 后，应返回每个字段的最后一个值。"""
    parsed = parse_form_body(b"admin_token=old&admin_token=new&other=value")

    assert parsed == {"admin_token": "new", "other": "value"}


def test_parse_admin_login_token_accepts_current_and_legacy_field_names() -> None:
    """管理员登录 token 解析应兼容 admin_token 和旧 token 字段。"""
    assert parse_admin_login_token(b"admin_token=%20secret%20") == "secret"
    assert parse_admin_login_token(b"token=legacy-secret") == "legacy-secret"


def test_parse_admin_login_token_prefers_admin_token_over_legacy_token() -> None:
    """两个字段同时存在时，应优先使用当前 admin_token 字段。"""
    assert parse_admin_login_token(b"token=legacy&admin_token=current") == "current"


def test_parse_form_body_returns_empty_dict_for_empty_or_invalid_body() -> None:
    """空请求体或非 UTF-8 表单 bytes 应返回空字典而不抛出异常。"""
    assert parse_form_body(b"") == {}
    assert parse_form_body(b"\xff\xfe\xfd") == {}
    assert parse_admin_login_token(b"\xff\xfe\xfd") == ""
