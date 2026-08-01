from __future__ import annotations

import pytest

from docxtool.web.preset_config import (
    normalize_template_id,
    normalize_template_name,
    preset_error_from_exception,
    preset_mutation_context,
    preset_row_to_dict,
    preset_template_origin_error,
    preset_user_csrf_error,
    validate_template_config,
)


def _core_defaults() -> dict:
    """无需传入数据，返回模板配置测试使用的核心功能默认值。"""
    return {
        "punctuation": {"enabled": False},
        "classification": {"enabled": True},
        "numbering": {"enabled": False},
        "page_number": {"enabled": True},
        "signature_block": {"mode": "without_seal"},
        "table_format": {"enabled": False},
        "cleanup": {"enabled": False},
    }


def test_normalize_template_name_trims_internal_whitespace() -> None:
    assert normalize_template_name("  我的   模板\t名称  ") == "我的 模板 名称"
    with pytest.raises(ValueError, match="TEMPLATE_NAME_REQUIRED"):
        normalize_template_name("   ")
    with pytest.raises(ValueError, match="TEMPLATE_NAME_TOO_LONG"):
        normalize_template_name("x" * 81)


def test_normalize_template_id_keeps_only_safe_characters() -> None:
    assert normalize_template_id("  abc/中文?..id  ") == "abc_..id"
    with pytest.raises(ValueError, match="TEMPLATE_ID_INVALID"):
        normalize_template_id("...")
    with pytest.raises(ValueError, match="TEMPLATE_ID_TOO_LONG"):
        normalize_template_id("x" * 81)


def test_validate_template_config_normalizes_page_styles_and_features() -> None:
    normalized = validate_template_config(
        {
            "schema_version": 1,
            "processing_mode": "smart",
            "page": {"lines_per_page": 22, "chars_per_line": 28},
            "punctuation": {"enabled": True, "mode": "safe"},
            "numbering": {"enabled": True},
        },
        core_feature_defaults=_core_defaults(),
    )

    assert normalized["schema_version"] == 1
    assert normalized["processing_mode"] == "smart"
    assert normalized["page"]["lines_per_page"] == 22
    assert normalized["page"]["chars_per_line"] == 28
    assert normalized["punctuation"]["enabled"] is True
    assert normalized["numbering"]["enabled"] is True
    assert normalized["classification"]["enabled"] is True
    assert normalized["classification"]["minimum_auto_format_confidence"] == 0.85
    assert normalized["styles"]


def test_validate_template_config_rejects_non_mapping() -> None:
    with pytest.raises(ValueError, match="TEMPLATE_CONFIG_INVALID"):
        validate_template_config([], core_feature_defaults=_core_defaults())  # type: ignore[arg-type]


def test_preset_row_to_dict_redacts_owner_and_optionally_parses_config() -> None:
    row = {
        "id": "tpl_demo",
        "name": "Demo",
        "is_system": 1,
        "is_default": 0,
        "visibility": "",
        "owner_id": "usr_secret",
        "config_json": '{"schema_version":1}',
    }

    without_config = preset_row_to_dict(row, include_config=False)
    with_config = preset_row_to_dict(row, include_config=True)

    assert without_config["is_system"] is True
    assert without_config["is_default"] is False
    assert without_config["visibility"] == "public"
    assert "owner_id" not in without_config
    assert "config_json" not in without_config
    assert with_config["config_json"] == {"schema_version": 1}


def test_preset_row_to_dict_uses_empty_config_on_invalid_json() -> None:
    data = preset_row_to_dict({"config_json": "{bad", "is_system": 0, "is_default": 0}, include_config=True)

    assert data["config_json"] == {}


def test_preset_error_from_exception_returns_code_message_and_status() -> None:
    """模板异常解析应返回稳定错误码、提示文本和 HTTP 状态码。"""
    assert preset_error_from_exception(ValueError("TEMPLATE_NAME_REQUIRED: 模板名称不能为空")) == (
        "TEMPLATE_NAME_REQUIRED",
        "模板名称不能为空",
        400,
    )


def test_preset_mutation_context_describes_admin_or_private_scope() -> None:
    """preset 变更上下文应区分管理员公共模板和用户私有模板。"""
    assert preset_mutation_context(admin=True) == {
        "owner_id": "",
        "cookie_header": "",
        "public_only": True,
        "admin": True,
    }
    assert preset_mutation_context("usr_1", "anon=cookie") == {
        "owner_id": "usr_1",
        "cookie_header": "anon=cookie",
        "public_only": False,
        "admin": False,
    }


def test_preset_mutation_csrf_errors_are_stable() -> None:
    """preset 变更来源和用户 CSRF 错误应返回稳定错误字段。"""
    assert preset_template_origin_error() == ("CSRF_INVALID", "模板请求来源校验失败", 403)
    assert preset_user_csrf_error() == ("CSRF_INVALID", "CSRF 校验失败", 403)
    assert preset_error_from_exception(ValueError("TEMPLATE_NOT_FOUND: 模板不存在")) == (
        "TEMPLATE_NOT_FOUND",
        "模板不存在",
        404,
    )
    assert preset_error_from_exception(ValueError("plain error")) == ("TEMPLATE_INVALID", "plain error", 400)
    assert preset_error_from_exception(ValueError("TEMPLATE_NOT_FOUND: 模板不存在"), not_found_status=400) == (
        "TEMPLATE_NOT_FOUND",
        "模板不存在",
        400,
    )
