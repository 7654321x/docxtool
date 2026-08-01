from __future__ import annotations

from types import SimpleNamespace

from docxtool.web.admin_route_handlers import handle_ban, handle_cleanup, handle_ip_detail, handle_limit, handle_unban


class FakeLogger:
    """测试用 logger，记录 warning/info 调用内容。"""

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def warning(self, message: str) -> None:
        """传入 warning 文本，记录日志级别和文本并返回 None。"""
        self.messages.append(("warning", message))

    def info(self, message: str) -> None:
        """传入 info 文本，记录日志级别和文本并返回 None。"""
        self.messages.append(("info", message))


class FakeHandler:
    """测试用 handler，提供管理员动作处理需要的最小方法。"""

    def __init__(self, params: dict | None = None, query_ip: str = "127.0.0.1") -> None:
        self.params = params or {}
        self.query_ip = query_ip
        self.responses: list[tuple[str, object]] = []

    def _query_ip(self, _parsed) -> str:
        """传入已解析 URL，返回测试预设 IP。"""
        return self.query_ip

    def _request_params(self, _parsed) -> dict:
        """传入已解析 URL，返回测试预设请求参数。"""
        return self.params

    def _admin_csrf_token(self, _parsed) -> str:
        """传入已解析 URL，返回测试 CSRF token。"""
        return "csrf-token"

    def _json_error(self, code: str, message: str, status: int) -> None:
        """传入错误码、提示和状态码，记录 JSON 错误响应。"""
        self.responses.append(("json_error", (code, message, status)))

    def _text(self, body: str, mime: str) -> None:
        """传入 HTML 正文和 MIME，记录文本响应。"""
        self.responses.append(("text", (body, mime)))

    def _redirect(self, target: str) -> None:
        """传入跳转地址，记录重定向响应。"""
        self.responses.append(("redirect", target))


def test_handle_ip_detail_renders_valid_ip_or_error() -> None:
    """IP 详情处理器应渲染合法 IP，并拒绝非法 IP。"""
    ok = FakeHandler(query_ip="127.0.0.1")
    bad = FakeHandler(query_ip="bad")

    handle_ip_detail(
        ok,
        SimpleNamespace(),
        is_ip=lambda value: value == "127.0.0.1",
        render_ip_detail_html=lambda ip, csrf: f"{ip}:{csrf}",
    )
    handle_ip_detail(
        bad,
        SimpleNamespace(),
        is_ip=lambda value: value == "127.0.0.1",
        render_ip_detail_html=lambda ip, csrf: f"{ip}:{csrf}",
    )

    assert ok.responses == [("text", ("127.0.0.1:csrf-token", "text/html"))]
    assert bad.responses == [("json_error", ("INVALID_IP", "无效的 IP", 400))]


def test_handle_ban_and_unban_validate_ip_and_redirect() -> None:
    """封禁和解封处理器应校验 IP、调用回调并跳转监控页。"""
    logger = FakeLogger()
    actions: list[tuple[str, object]] = []
    handler = FakeHandler({"ip": "127.0.0.1", "reason": "manual"})

    handle_ban(
        handler,
        SimpleNamespace(),
        is_ip=lambda value: value == "127.0.0.1",
        ban_ip=lambda ip, reason: actions.append(("ban", (ip, reason))),
        logger=logger,
    )
    handle_unban(
        handler,
        SimpleNamespace(),
        is_ip=lambda value: value == "127.0.0.1",
        unban_ip=lambda ip: actions.append(("unban", ip)),
        logger=logger,
    )

    assert actions == [("ban", ("127.0.0.1", "manual")), ("unban", "127.0.0.1")]
    assert handler.responses == [("redirect", "/monitor"), ("redirect", "/monitor")]
    assert [level for level, _ in logger.messages] == ["warning", "warning"]


def test_handle_ban_rejects_invalid_ip_before_callback() -> None:
    """封禁处理器遇到非法 IP 时应返回错误，不调用封禁回调。"""
    actions: list[str] = []
    handler = FakeHandler({"ip": "bad"})

    handle_ban(
        handler,
        SimpleNamespace(),
        is_ip=lambda _value: False,
        ban_ip=lambda _ip, _reason: actions.append("called"),
        logger=FakeLogger(),
    )

    assert actions == []
    assert handler.responses == [("json_error", ("INVALID_IP", "无效的 IP", 400))]


def test_handle_limit_saves_values_and_redirects() -> None:
    """上传限额处理器应解析表单参数、保存配置并跳转监控页。"""
    logger = FakeLogger()
    saved: list[tuple[bool, int, int]] = []
    handler = FakeHandler({"enabled": "1", "window_seconds": "60", "count": "7"})

    handle_limit(
        handler,
        SimpleNamespace(),
        default_window_seconds=3600,
        default_count=5,
        save_limit_settings=lambda enabled, window, count: saved.append((enabled, window, count)),
        logger=logger,
    )

    assert saved == [(True, 60, 7)]
    assert handler.responses == [("redirect", "/monitor")]
    assert logger.messages[0][0] == "warning"


def test_handle_cleanup_only_logs_and_redirects() -> None:
    """兼容清理处理器在永久保留策略下只记录日志并跳转。"""
    logger = FakeLogger()
    handler = FakeHandler()

    handle_cleanup(handler, logger=logger)

    assert handler.responses == [("redirect", "/monitor")]
    assert logger.messages == [("info", "[Cleaner] manual cleanup skipped: permanent file retention is enabled")]
