from __future__ import annotations

from types import SimpleNamespace

from docxtool.web import app as web_app
from docxtool.web.handler import Handler
from docxtool.web.handler_dispatch import dispatch_delete, dispatch_get, dispatch_post, dispatch_put


class FakeHandler:
    """测试用 handler，记录分派调用和可配置的鉴权结果。"""

    def __init__(self, *, admin: bool = True, admin_post: bool = True, file_api: bool = True, preset: bool = True) -> None:
        self.calls: list[tuple[str, object]] = []
        self.admin = admin
        self.admin_post = admin_post
        self.file_api = file_api
        self.preset = preset

    def send_error(self, status: int) -> None:
        """传入 HTTP 状态码，记录错误响应并返回 None。"""
        self.calls.append(("send_error", status))

    def _record(self, name: str, value: object = "") -> None:
        """传入动作名称和值，追加到调用记录并返回 None。"""
        self.calls.append((name, value))

    def _require_admin(self, _parsed) -> bool:
        """传入已解析 URL，返回测试预设的管理员鉴权结果。"""
        self._record("require_admin")
        return self.admin

    def _require_admin_post(self, _parsed) -> bool:
        """传入已解析 URL，返回测试预设的管理员 POST 鉴权结果。"""
        self._record("require_admin_post")
        return self.admin_post

    def _require_file_api(self) -> bool:
        """无需传入数据，返回测试预设的文件 API 鉴权结果。"""
        self._record("require_file_api")
        return self.file_api

    def _require_preset_mutation(self, _parsed) -> bool:
        """传入已解析 URL，返回测试预设的模板变更鉴权结果。"""
        self._record("require_preset")
        return self.preset

    def _handle_status_route(self, task_id: str) -> None:
        """传入任务 ID，模拟状态路由 wrapper 并返回 None。"""
        if not self._require_file_api():
            return
        self._record("status", task_id)

    def _handle_download_route(self, file_id: str) -> None:
        """传入文件 ID，模拟下载路由 wrapper 并返回 None。"""
        if not self._require_file_api():
            return
        self._record("download", file_id)

    def _handle_log_route(self, parsed, task_id: str) -> None:
        """传入已解析 URL 和任务 ID，模拟旧日志入口的规范页跳转并返回 None。"""
        self._record("legacy_log", task_id)

    def _handle_upload_route(self) -> None:
        """无需传入数据，模拟上传路由 wrapper 并返回 None。"""
        if not self._require_file_api():
            return
        self._record("upload")

    def _handle_ban_route(self, parsed) -> None:
        """传入已解析 URL，模拟封禁路由 wrapper 并返回 None。"""
        if not self._require_admin_post(parsed):
            return
        self._record("ban")

    def _handle_preset_update_route(self, parsed, preset_id: str) -> None:
        """传入已解析 URL 和模板 ID，模拟 preset 更新 wrapper 并返回 None。"""
        if not self._require_preset_mutation(parsed):
            return
        self._record("preset_update", preset_id)

    def _handle_preset_delete_route(self, parsed, preset_id: str) -> None:
        """传入已解析 URL 和模板 ID，模拟 preset 删除 wrapper 并返回 None。"""
        if not self._require_preset_mutation(parsed):
            return
        self._record("preset_delete", preset_id)

    def _handle_admin_web(self, _parsed, section: str) -> None:
        """记录网页业务二级路由及其已匹配的模块标识。"""
        self._record("admin_web", section)

    def _handle_admin_wps_overview(self, _parsed) -> None:
        """记录 WPS 总览路由。"""
        self._record("wps_overview")

    def _handle_admin_wps_devices(self, _parsed) -> None:
        """记录 WPS 设备路由。"""
        self._record("wps_devices")

    def _handle_admin_wps_tasks(self, _parsed) -> None:
        """记录 WPS 任务路由。"""
        self._record("wps_tasks")

    def _handle_admin_wps_user_password_reset(self, _parsed, user_id: str) -> None:
        """记录 WPS 用户密码重置路由。"""
        self._record("wps_password_reset", user_id)

    def _handle_admin_wps_user_notification(self, _parsed, user_id: str) -> None:
        """记录 WPS 用户通知路由。"""
        self._record("wps_notification", user_id)

    def _handle_admin_wps_user_delete(self, _parsed, user_id: str) -> None:
        """记录 WPS 用户删除路由。"""
        self._record("wps_user_delete", user_id)

    def __getattr__(self, name: str):
        """传入未知处理方法名，返回记录调用的方法桩。"""
        if name.startswith("_handle_") or name.startswith("_serve_"):
            return lambda *args: self._record(name, args[0] if args else "")
        raise AttributeError(name)


def test_dispatch_get_calls_public_and_legacy_compatibility_handlers() -> None:
    """GET 分派应调用公开页面、资源路由、旧日志兼容入口和未知路径错误处理。"""
    parsed = SimpleNamespace()
    handler = FakeHandler()

    dispatch_get(handler, parsed, "/")
    dispatch_get(handler, parsed, "/status/task-1")
    dispatch_get(handler, parsed, "/log/task-2")
    dispatch_get(handler, parsed, "/missing")

    assert handler.calls == [
        ("_serve_html", ""),
        ("require_file_api", ""),
        ("status", "task-1"),
        ("legacy_log", "task-2"),
        ("send_error", 404),
    ]


def test_dispatch_get_stops_when_file_api_auth_fails() -> None:
    """GET 状态路由在文件 API 鉴权失败时不得继续调用状态处理。"""
    handler = FakeHandler(file_api=False)

    dispatch_get(handler, SimpleNamespace(), "/status/task-1")

    assert handler.calls == [("require_file_api", "")]


def test_dispatch_get_calls_workspace_secondary_routes_with_canonical_sections() -> None:
    handler = FakeHandler()
    parsed = SimpleNamespace()

    dispatch_get(handler, parsed, "/admin/web/logs")
    dispatch_get(handler, parsed, "/admin/wps")
    dispatch_get(handler, parsed, "/admin/wps/devices")
    dispatch_get(handler, parsed, "/admin/wps/tasks")

    assert handler.calls == [
        ("admin_web", "logs"),
        ("wps_overview", ""),
        ("wps_devices", ""),
        ("wps_tasks", ""),
    ]


def test_dispatch_post_calls_auth_admin_and_preset_handlers() -> None:
    """POST 分派应调用认证、管理员动作和 preset 变更处理。"""
    parsed = SimpleNamespace()
    handler = FakeHandler()

    dispatch_post(handler, parsed, "/auth/login")
    dispatch_post(handler, parsed, "/ban")
    dispatch_post(handler, parsed, "/admin/wps/users/wusr_1/password")
    dispatch_post(handler, parsed, "/admin/wps/users/wusr_1/notifications")
    dispatch_post(handler, parsed, "/admin/wps/users/wusr_1/delete")
    dispatch_post(handler, parsed, "/presets/user-template")
    dispatch_post(handler, parsed, "/missing")

    assert handler.calls == [
        ("_handle_auth_login", ""),
        ("require_admin_post", ""),
        ("ban", ""),
        ("wps_password_reset", "wusr_1"),
        ("wps_notification", "wusr_1"),
        ("wps_user_delete", "wusr_1"),
        ("require_preset", ""),
        ("preset_update", "user-template"),
        ("send_error", 404),
    ]


def test_dispatch_put_and_delete_respect_preset_auth() -> None:
    """PUT/DELETE 分派应在 preset 鉴权失败时停止业务处理。"""
    parsed = SimpleNamespace()
    denied = FakeHandler(preset=False)
    allowed = FakeHandler()

    dispatch_put(denied, parsed, "/presets/user-template")
    dispatch_delete(allowed, parsed, "/presets/user-template")

    assert denied.calls == [("require_preset", "")]
    assert allowed.calls == [("require_preset", ""), ("preset_delete", "user-template")]


def test_legacy_admin_redirect_creates_session_before_dropping_legacy_token(monkeypatch) -> None:
    """旧 URL 的管理员令牌跳转前应换取 session，不能丢失后续页面的 CSRF 上下文。"""
    instance = object.__new__(Handler)
    instance.headers = {"User-Agent": "pytest"}
    instance.client_address = ("127.0.0.1", 9527)
    instance._require_admin = lambda _parsed: True
    instance._admin_context_or_default = lambda: {"legacy_token": True, "session": {}}
    responses: list[tuple[str, object]] = []
    instance._redirect = lambda target, extra_headers=None: responses.append((target, extra_headers))
    monkeypatch.setattr(
        web_app,
        "_create_admin_session",
        lambda agent, ip: {"session_id": f"{agent}:{ip}"},
    )
    monkeypatch.setattr(
        web_app,
        "_admin_cookie_header",
        lambda session_id: f"admin={session_id}",
    )

    Handler._redirect_legacy_admin_to_workspace(
        instance, SimpleNamespace(), "/admin/web/tasks?page=2"
    )

    assert responses == [
        (
            "/admin/web/tasks?page=2",
            [("Set-Cookie", "admin=pytest:127.0.0.1")],
        )
    ]


def test_workspace_entry_points_use_session_handoff_guard(monkeypatch) -> None:
    """首页和用户详情都必须先把 legacy token 换成管理员 session。"""
    instance = object.__new__(Handler)
    instance._require_admin = lambda _parsed: "legacy-only"
    instance._require_workspace_admin = lambda _parsed: "session-handoff"
    observed: list[object] = []

    monkeypatch.setattr(
        web_app,
        "_wps_admin_route_handle_workspace",
        lambda _handler, _parsed, **kwargs: observed.append(kwargs["require_admin"]),
    )
    monkeypatch.setattr(
        web_app,
        "_wps_admin_route_handle_user",
        lambda _handler, _parsed, _user_id, **kwargs: observed.append(kwargs["require_admin"]),
    )

    parsed = SimpleNamespace()
    Handler._handle_admin_workspace(instance, parsed)
    Handler._handle_admin_wps_user(instance, parsed, "wusr_1")

    assert [guard(parsed) for guard in observed] == ["session-handoff", "session-handoff"]


def test_workspace_session_handoff_preserves_allowed_deep_link_state(monkeypatch) -> None:
    """交接 session 时保留合法页面状态，但绝不把 legacy token 放回 Location。"""
    instance = object.__new__(Handler)
    instance.headers = {"User-Agent": "pytest"}
    instance.client_address = ("127.0.0.1", 9527)
    instance._require_admin = lambda _parsed: True
    instance._admin_context_or_default = lambda: {"legacy_token": True, "session": {}}
    responses: list[tuple[str, object]] = []
    instance._redirect = lambda target, extra_headers=None: responses.append((target, extra_headers))
    monkeypatch.setattr(
        web_app,
        "_create_admin_session",
        lambda _agent, _ip: {"session_id": "session"},
    )
    monkeypatch.setattr(web_app, "_admin_cookie_header", lambda _session_id: "admin=session")

    allowed = Handler._require_workspace_admin(
        instance,
        SimpleNamespace(
            path="/admin/wps/users/wusr_1",
            query="tab=security&page=2&token=legacy&next=https%3A%2F%2Fbad.example",
        ),
    )

    assert allowed is False
    assert responses == [
        (
            "/admin/wps/users/wusr_1?tab=security&page=2",
            [("Set-Cookie", "admin=session")],
        )
    ]


def test_canonical_web_detail_queries_dispatch_to_shared_detail_handlers(monkeypatch) -> None:
    """规范安全页和日志页带详情选择器时应进入共享壳的详情处理器。"""
    instance = object.__new__(Handler)
    instance._query_ip = lambda _parsed: "203.0.113.1"
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        web_app,
        "_protected_route_handle_admin",
        lambda _parsed, *, require_admin, action: calls.append(("ip", action.__name__)),
    )
    monkeypatch.setattr(
        web_app,
        "_protected_route_handle_admin_resource",
        lambda _parsed, resource_id, *, require_admin, action: calls.append(
            ("log", (resource_id, action.__name__))
        ),
    )

    Handler._handle_admin_web(instance, SimpleNamespace(query="ip=203.0.113.1"), "security")
    Handler._handle_admin_web(instance, SimpleNamespace(query="task_id=task-1"), "logs")

    assert calls == [
        ("ip", "_handle_ip_detail"),
        ("log", ("task-1", "_handle_log")),
    ]
