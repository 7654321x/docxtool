from __future__ import annotations

from types import SimpleNamespace

from docxtool.web.route_authorization import (
    require_admin,
    require_admin_post,
    require_file_api,
    require_preset_mutation,
    set_preset_mutation_context,
)


class FakeHandler:
    """测试用 handler，保存请求属性、兼容上下文和错误响应。"""

    def __init__(self) -> None:
        self.headers = {"Cookie": "c=1", "X-CSRF-Token": "csrf"}
        self.client_address = ("127.0.0.1", 9527)
        self.errors: list[tuple[str, object]] = []

    def _json_error_fields(self, error: tuple[str, str, int]) -> None:
        """传入稳定错误元组，记录字段错误响应并返回 None。"""
        self.errors.append(("fields", error))

    def _json_error(self, code: str, message: str, status: int) -> None:
        """传入错误码、提示和状态码，记录 JSON 错误响应并返回 None。"""
        self.errors.append(("json", (code, message, status)))


def test_require_admin_sets_context_and_rejects_unauthorized() -> None:
    """管理员鉴权辅助应写入上下文，并在未授权时发送原错误。"""
    parsed = SimpleNamespace(path="/monitor")
    handler = FakeHandler()

    ok = require_admin(
        handler,
        parsed,
        admin_request_context=lambda _parsed, _headers, _cookie: {"authorized": False},
        unauthorized_error=lambda: ("UNAUTHORIZED", "需要管理员权限", 403),
    )

    assert ok is False
    assert handler._admin_context == {"authorized": False}
    assert handler.errors == [("fields", ("UNAUTHORIZED", "需要管理员权限", 403))]


def test_require_admin_post_caches_params_and_checks_csrf() -> None:
    """管理员 POST 鉴权辅助应缓存请求参数，并执行 CSRF 校验。"""
    parsed = SimpleNamespace(path="/monitor/ban")
    handler = FakeHandler()

    ok = require_admin_post(
        handler,
        parsed,
        admin_request_context=lambda _parsed, _headers, _cookie: {"authorized": True, "csrf_token": "csrf"},
        unauthorized_error=lambda: ("UNAUTHORIZED", "需要管理员权限", 403),
        request_params=lambda _parsed: {"csrf_token": "csrf"},
        admin_post_csrf_allowed=lambda ctx, params, _headers: ctx["csrf_token"] == params["csrf_token"],
        csrf_invalid_error=lambda: ("CSRF_INVALID", "CSRF 校验失败", 403),
    )

    assert ok is True
    assert handler._request_params_cache == {"csrf_token": "csrf"}
    assert handler.errors == []


def test_require_admin_post_rejects_bad_csrf() -> None:
    """管理员 POST 鉴权辅助应在 CSRF 失败时发送稳定错误。"""
    handler = FakeHandler()

    ok = require_admin_post(
        handler,
        SimpleNamespace(path="/monitor/ban"),
        admin_request_context=lambda _parsed, _headers, _cookie: {"authorized": True},
        unauthorized_error=lambda: ("UNAUTHORIZED", "需要管理员权限", 403),
        request_params=lambda _parsed: {"csrf_token": "bad"},
        admin_post_csrf_allowed=lambda _ctx, _params, _headers: False,
        csrf_invalid_error=lambda: ("CSRF_INVALID", "CSRF 校验失败", 403),
    )

    assert ok is False
    assert handler.errors == [("fields", ("CSRF_INVALID", "CSRF 校验失败", 403))]


def test_set_preset_mutation_context_writes_legacy_fields() -> None:
    """preset 上下文写入辅助应保持旧 handler 属性兼容。"""
    handler = FakeHandler()

    set_preset_mutation_context(
        handler,
        {"owner_id": "owner", "cookie_header": "Set-Cookie: a", "public_only": False, "admin": True},
    )

    assert handler._preset_owner_id == "owner"
    assert handler._preset_cookie_header == "Set-Cookie: a"
    assert handler._preset_public_only is False
    assert handler._preset_admin is True


def test_require_preset_mutation_uses_admin_post_path() -> None:
    """preset 修改鉴权辅助遇到管理员上下文时，应复用管理员 POST 鉴权路径。"""
    handler = FakeHandler()
    calls: list[str] = []

    ok = require_preset_mutation(
        handler,
        SimpleNamespace(path="/api/presets"),
        admin_request_context=lambda _parsed, _headers, _cookie: {"authorized": True},
        require_admin_post=lambda _parsed: calls.append("admin_post") or True,
        anonymous_template_origin_allowed=lambda _headers: False,
        template_origin_error=lambda: ("ORIGIN", "来源不允许", 403),
        request_params=lambda _parsed: {},
        principal=lambda _headers, _client: {"owner_id": "anon"},
        auth_csrf_allowed=lambda _headers, _principal: False,
        user_csrf_error=lambda: ("CSRF", "CSRF", 403),
        preset_mutation_context=lambda *args, **kwargs: {
            "owner_id": "public",
            "cookie_header": "",
            "public_only": True,
            "admin": kwargs.get("admin", False),
        },
    )

    assert ok is True
    assert calls == ["admin_post"]
    assert handler._preset_admin is True


def test_require_preset_mutation_rejects_private_origin_before_body() -> None:
    """preset 私人模板路径应先校验来源，不允许时不读取参数。"""
    handler = FakeHandler()
    calls: list[str] = []

    ok = require_preset_mutation(
        handler,
        SimpleNamespace(path="/api/presets"),
        admin_request_context=lambda _parsed, _headers, _cookie: {"authorized": False},
        require_admin_post=lambda _parsed: True,
        anonymous_template_origin_allowed=lambda _headers: False,
        template_origin_error=lambda: ("ORIGIN", "来源不允许", 403),
        request_params=lambda _parsed: calls.append("params") or {},
        principal=lambda _headers, _client: {"owner_id": "anon"},
        auth_csrf_allowed=lambda _headers, _principal: True,
        user_csrf_error=lambda: ("CSRF", "CSRF", 403),
        preset_mutation_context=lambda *_args, **_kwargs: {},
    )

    assert ok is False
    assert calls == []
    assert handler.errors == [("fields", ("ORIGIN", "来源不允许", 403))]


def test_require_file_api_sends_proxy_error_when_denied() -> None:
    """文件 API 鉴权辅助应在失败时发送旧代理密钥错误。"""
    handler = FakeHandler()

    ok = require_file_api(handler, file_api_authorized=lambda _headers, _client: False)

    assert ok is False
    assert handler.errors == [("json", ("PROXY_REQUIRED", "缺少或无效的代理密钥", 403))]
