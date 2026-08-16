import pytest

from docxtool.web import app as server
from docxtool.web.bootstrap import load_environment_config
from docxtool.web.config import (
    DEFAULT_ADMIN_CONSOLE_ORIGIN,
    DEFAULT_PUBLIC_FRONTEND_ORIGIN,
    cors_headers_for_request,
    display_frontend_origin,
    parse_admin_console_origin,
    parse_bool,
    parse_frontend_origin,
    parse_int_env,
    parse_strict_bool,
    resolve_admin_cookie_secure,
    resolve_cookie_secure,
)


def test_web_config_parse_helpers_are_stable() -> None:
    """配置解析函数传入字符串或环境映射时，应返回稳定的布尔和整数。"""
    assert parse_bool("true", False) is True
    assert parse_bool("false", True) is False
    assert parse_bool("unknown", True) is True
    assert parse_strict_bool("true", "PRODUCTION_MODE") is True
    assert parse_strict_bool("OFF", "PRODUCTION_MODE") is False
    with pytest.raises(ValueError, match="PRODUCTION_MODE"):
        parse_strict_bool("unknown", "PRODUCTION_MODE")
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


def test_local_admin_console_settings_require_a_matching_cookie_policy() -> None:
    """本地开发 HTTP 管理入口应使用独立且非 Secure 的管理员 Cookie 配置。"""
    assert parse_admin_console_origin("") == DEFAULT_ADMIN_CONSOLE_ORIGIN
    assert parse_admin_console_origin(" http://localhost:9527/ ") == "http://localhost:9527"
    assert resolve_admin_cookie_secure(
        "http://localhost:9527",
        "false",
        default=True,
        production_mode=False,
    ) is False


def test_direct_admin_console_origin_rejects_paths_and_secure_cookie_on_http() -> None:
    """管理入口只接受根 Origin，避免启动日志或 Cookie 配置指向无效地址。"""
    import pytest

    with pytest.raises(ValueError, match="must not include path"):
        parse_admin_console_origin("http://localhost:9527/admin/login")
    with pytest.raises(ValueError, match="ADMIN_COOKIE_SECURE"):
        resolve_admin_cookie_secure("http://localhost:9527", "true", default=True)
    with pytest.raises(ValueError, match="must use https"):
        parse_admin_console_origin("http://localhost:9527", production_mode=True)


def _load_security_config(monkeypatch, **overrides):
    values = {
        "PRODUCTION_MODE": "true",
        "FRONTEND_ORIGIN": "https://docxtool.pages.dev",
        "ADMIN_CONSOLE_ORIGIN": "https://docxtool.pages.dev",
        "COOKIE_SECURE": "true",
        "ADMIN_COOKIE_SECURE": "true",
        "TRUST_PROXY_HEADERS": "true",
    }
    values.update(overrides)
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return load_environment_config(lambda name, _default: f"test-{name}")


@pytest.mark.parametrize(("value", "expected"), [("true", True), ("false", False)])
def test_production_mode_uses_strict_boolean_configuration(monkeypatch, value, expected) -> None:
    """生产模式显式 true/false 时应保留真实语义，不依赖宽松默认值。"""
    config = _load_security_config(monkeypatch, PRODUCTION_MODE=value)

    assert config.production_mode is expected


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("PRODUCTION_MODE", "ture"),
        ("PRODUCTION_MODE", "abc"),
        ("TRUST_PROXY_HEADERS", "ture"),
        ("COOKIE_SECURE", "ture"),
        ("ADMIN_COOKIE_SECURE", "ture"),
    ),
)
def test_invalid_security_boolean_configuration_fails_fast(monkeypatch, name, value) -> None:
    """安全边界布尔配置拼写错误时必须指出变量名并中止启动。"""
    with pytest.raises(SystemExit, match=name):
        _load_security_config(monkeypatch, **{name: value})


def test_production_admin_origin_must_be_the_https_pages_origin(monkeypatch) -> None:
    """生产管理后台只能使用与 Pages 前端相同的 HTTPS Origin。"""
    with pytest.raises(SystemExit, match="ADMIN_CONSOLE_ORIGIN"):
        _load_security_config(monkeypatch, ADMIN_CONSOLE_ORIGIN="https://other.example")

    config = _load_security_config(monkeypatch)
    assert config.admin_console_origin == "https://docxtool.pages.dev"
    assert config.cookie_secure is True
    assert config.admin_cookie_secure is True


def test_cors_config_module_matches_app_facade() -> None:
    """CORS 新模块传入显式 origin 时，应与 web.app 兼容入口返回相同响应头。"""
    origin = "https://example.pages.dev"
    expected = cors_headers_for_request(origin, origin)

    assert server.cors_headers_for_request(origin, frontend_origin=origin) == expected
    assert expected["Access-Control-Allow-Origin"] == origin
    assert "X-CSRF-Token" in expected["Access-Control-Allow-Headers"]
