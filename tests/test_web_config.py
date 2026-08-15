from docxtool.web import app as server
from docxtool.web.config import (
    DEFAULT_ADMIN_CONSOLE_ORIGIN,
    DEFAULT_PUBLIC_FRONTEND_ORIGIN,
    cors_headers_for_request,
    display_frontend_origin,
    parse_admin_console_origin,
    parse_bool,
    parse_frontend_origin,
    parse_int_env,
    resolve_admin_cookie_secure,
    resolve_cookie_secure,
)


def test_web_config_parse_helpers_are_stable() -> None:
    """配置解析函数传入字符串或环境映射时，应返回稳定的布尔和整数。"""
    assert parse_bool("true", False) is True
    assert parse_bool("false", True) is False
    assert parse_bool("unknown", True) is True
    assert parse_int_env("COUNT", 3, {"COUNT": "8"}) == 8
    assert parse_int_env("COUNT", 3, {"COUNT": "bad"}) == 3


def test_frontend_origin_and_cookie_secure_helpers() -> None:
    """前端来源和 Cookie Secure 解析应只返回规范化结果或抛出配置错误。"""
    assert parse_frontend_origin(" https://example.pages.dev/ ") == "https://example.pages.dev"
    assert parse_frontend_origin("http://localhost:3000", production_mode=True) == "http://localhost:3000"
    assert resolve_cookie_secure("https://example.pages.dev") is True
    assert resolve_cookie_secure("http://localhost:3000") is False
    assert display_frontend_origin("") == DEFAULT_PUBLIC_FRONTEND_ORIGIN
    assert display_frontend_origin(" https://example.pages.dev/ ") == "https://example.pages.dev"


def test_direct_admin_console_settings_require_a_matching_cookie_policy() -> None:
    """直连 HTTP 管理入口应使用独立且非 Secure 的管理员 Cookie 配置。"""
    assert parse_admin_console_origin("") == DEFAULT_ADMIN_CONSOLE_ORIGIN
    assert parse_admin_console_origin(" http://43.133.167.18:8080/ ") == "http://43.133.167.18:8080"
    assert resolve_admin_cookie_secure(
        "http://43.133.167.18:8080",
        "false",
        default=True,
        production_mode=True,
    ) is False


def test_direct_admin_console_origin_rejects_paths_and_secure_cookie_on_http() -> None:
    """管理入口只接受根 Origin，避免启动日志或 Cookie 配置指向无效地址。"""
    import pytest

    with pytest.raises(ValueError, match="must not include path"):
        parse_admin_console_origin("http://43.133.167.18:8080/admin/login")
    with pytest.raises(ValueError, match="ADMIN_COOKIE_SECURE"):
        resolve_admin_cookie_secure("http://43.133.167.18:8080", "true", default=True)


def test_cors_config_module_matches_app_facade() -> None:
    """CORS 新模块传入显式 origin 时，应与 web.app 兼容入口返回相同响应头。"""
    origin = "https://example.pages.dev"
    expected = cors_headers_for_request(origin, origin)

    assert server.cors_headers_for_request(origin, frontend_origin=origin) == expected
    assert expected["Access-Control-Allow-Origin"] == origin
    assert "X-CSRF-Token" in expected["Access-Control-Allow-Headers"]
