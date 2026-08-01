from __future__ import annotations

from types import SimpleNamespace

from docxtool.web.monitor_route_handlers import handle_monitor, handle_stats


class FakeHeaders(dict):
    """测试用 headers，继承 dict 以提供 get 方法。"""


class FakeHandler:
    """测试用 handler，记录 JSON、文本和跳转响应。"""

    def __init__(self) -> None:
        self.headers = FakeHeaders({"User-Agent": "pytest-agent"})
        self.client_address = ("127.0.0.1", 12345)
        self.responses: list[tuple[str, object]] = []

    def _json(self, payload: dict[str, object]) -> None:
        """传入 JSON payload，记录统计接口响应并返回 None。"""
        self.responses.append(("json", payload))

    def _text(self, body: str, mime: str) -> None:
        """传入正文和 MIME，记录 HTML 响应并返回 None。"""
        self.responses.append(("text", (body, mime)))

    def _redirect(self, target: str, extra_headers=None) -> None:
        """传入跳转地址和附加头，记录跳转响应并返回 None。"""
        self.responses.append(("redirect", (target, extra_headers or [])))


def test_handle_stats_requires_admin_before_querying() -> None:
    """统计接口未通过管理员鉴权时，不应执行统计查询。"""
    handler = FakeHandler()
    calls: list[str] = []

    handle_stats(
        handler,
        SimpleNamespace(query=""),
        require_admin=lambda _parsed: False,
        monitor_query_from=lambda _parsed: calls.append("query") or {},
        get_sql_stats=lambda _query: calls.append("stats") or {},
    )

    assert handler.responses == []
    assert calls == []


def test_handle_stats_sends_query_stats_json() -> None:
    """统计接口通过管理员鉴权后，应按监控查询发送统计 JSON。"""
    handler = FakeHandler()

    handle_stats(
        handler,
        SimpleNamespace(query="recent_page=2"),
        require_admin=lambda _parsed: True,
        monitor_query_from=lambda _parsed: {"recent_page": 2},
        get_sql_stats=lambda query: {"recent_page": query["recent_page"]},
    )

    assert handler.responses == [("json", {"recent_page": 2})]


def test_handle_monitor_renders_html_with_csrf_token() -> None:
    """监控页普通 session 路径应查询统计并渲染 HTML。"""
    handler = FakeHandler()

    handle_monitor(
        handler,
        SimpleNamespace(query=""),
        require_admin=lambda _parsed: True,
        admin_context_or_default=lambda: {"session": {"id": "s1"}},
        create_admin_session=lambda _agent, _ip: {"session_id": "new"},
        admin_cookie_header=lambda session_id: f"admin={session_id}",
        monitor_query_from=lambda _parsed: {"recent_page": 1},
        get_sql_stats=lambda query: {"recent_page": query["recent_page"]},
        monitor_html=lambda stats, csrf: f"{stats['recent_page']}:{csrf}",
        admin_csrf_token=lambda _parsed: "csrf-token",
    )

    assert handler.responses == [("text", ("1:csrf-token", "text/html"))]


def test_handle_monitor_refreshes_legacy_admin_session() -> None:
    """监控页 legacy token 路径应创建 session 并重定向回监控页。"""
    handler = FakeHandler()

    handle_monitor(
        handler,
        SimpleNamespace(query=""),
        require_admin=lambda _parsed: True,
        admin_context_or_default=lambda: {"legacy_token": "token"},
        create_admin_session=lambda agent, ip: {"session_id": f"{agent}:{ip}"},
        admin_cookie_header=lambda session_id: f"admin={session_id}",
        monitor_query_from=lambda _parsed: {"recent_page": 1},
        get_sql_stats=lambda _query: {"unused": True},
        monitor_html=lambda _stats, _csrf: "unused",
        admin_csrf_token=lambda _parsed: "csrf-token",
    )

    assert handler.responses == [
        ("redirect", ("/monitor", [("Set-Cookie", "admin=pytest-agent:127.0.0.1")]))
    ]
