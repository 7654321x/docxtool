from __future__ import annotations

from types import SimpleNamespace

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
        """传入已解析 URL 和任务 ID，模拟日志路由 wrapper 并返回 None。"""
        if not self._require_admin(parsed):
            return
        self._record("log", task_id)

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

    def __getattr__(self, name: str):
        """传入未知处理方法名，返回记录调用的方法桩。"""
        if name.startswith("_handle_") or name.startswith("_serve_"):
            return lambda *args: self._record(name, args[0] if args else "")
        raise AttributeError(name)


def test_dispatch_get_calls_public_and_resource_handlers() -> None:
    """GET 分派应调用公开页面、资源路由和未知路径错误处理。"""
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
        ("require_admin", ""),
        ("log", "task-2"),
        ("send_error", 404),
    ]


def test_dispatch_get_stops_when_file_api_auth_fails() -> None:
    """GET 状态路由在文件 API 鉴权失败时不得继续调用状态处理。"""
    handler = FakeHandler(file_api=False)

    dispatch_get(handler, SimpleNamespace(), "/status/task-1")

    assert handler.calls == [("require_file_api", "")]


def test_dispatch_post_calls_auth_admin_and_preset_handlers() -> None:
    """POST 分派应调用认证、管理员动作和 preset 变更处理。"""
    parsed = SimpleNamespace()
    handler = FakeHandler()

    dispatch_post(handler, parsed, "/auth/login")
    dispatch_post(handler, parsed, "/ban")
    dispatch_post(handler, parsed, "/presets/user-template")
    dispatch_post(handler, parsed, "/missing")

    assert handler.calls == [
        ("_handle_auth_login", ""),
        ("require_admin_post", ""),
        ("ban", ""),
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
