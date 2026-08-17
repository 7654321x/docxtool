from __future__ import annotations

from docxtool.web.handler_lifecycle import (
    dispatch_http_method,
    handle_options,
    send_cors_headers,
    send_security_headers,
)


class FakeHandler:
    """测试用 handler，记录 HTTP 生命周期调用。"""

    def __init__(self, path: str = "/api/task/abc?x=1", origin: str = "https://example.test") -> None:
        self.path = path
        self.headers = {"Origin": origin}
        self.calls: list[tuple[str, object]] = []

    def send_header(self, key: str, value: str) -> None:
        """传入响应头名和值，记录发送的响应头。"""
        self.calls.append(("header", (key, value)))

    def send_response(self, status: int) -> None:
        """传入 HTTP 状态码，记录响应状态。"""
        self.calls.append(("status", status))

    def end_headers(self) -> None:
        """无需传入数据，记录响应头结束事件。"""
        self.calls.append(("end", None))


def test_send_security_headers_writes_all_headers() -> None:
    """安全头发送辅助应按构造回调顺序发送所有安全响应头。"""
    handler = FakeHandler()

    send_security_headers(handler, security_headers=lambda: [("X-A", "1"), ("X-B", "2")])

    assert handler.calls == [("header", ("X-A", "1")), ("header", ("X-B", "2"))]


def test_send_cors_headers_uses_request_origin() -> None:
    """CORS 发送辅助应把请求 Origin 传给 CORS 构造回调。"""
    handler = FakeHandler(origin="https://pages.example")

    send_cors_headers(
        handler,
        cors_headers_for_origin=lambda origin: {"Access-Control-Allow-Origin": origin},
    )

    assert handler.calls == [("header", ("Access-Control-Allow-Origin", "https://pages.example"))]


def test_handle_options_keeps_existing_response_order() -> None:
    """OPTIONS 处理辅助应保持 204、CORS、安全头、结束头的旧顺序。"""
    handler = FakeHandler()

    handle_options(
        handler,
        cors_headers=lambda: handler.calls.append(("cors", None)),
        security_headers=lambda: handler.calls.append(("security", None)),
    )

    assert handler.calls == [("status", 204), ("cors", None), ("security", None), ("end", None)]


def test_dispatch_http_method_parses_path_and_dispatches_route_path() -> None:
    """HTTP 方法分派辅助应解析 URL，并把规范化路径传给路由分派回调。"""
    handler = FakeHandler(path="/api/task/abc?x=1")
    calls: list[tuple[str, str]] = []

    dispatch_http_method(
        handler,
        route_path=lambda path: f"route:{path}",
        dispatch=lambda _handler, parsed, path: calls.append((parsed.query, path)),
        authorize=lambda path: path == "route:/api/task/abc",
    )

    assert calls == [("x=1", "route:/api/task/abc")]


def test_dispatch_http_method_stops_before_dispatch_when_gateway_denies() -> None:
    handler = FakeHandler(path="/wps-api/v1/auth/login")
    calls: list[str] = []

    dispatch_http_method(
        handler,
        route_path=lambda path: path,
        authorize=lambda path: calls.append(f"authorize:{path}") or False,
        dispatch=lambda *_args: calls.append("dispatch"),
    )

    assert calls == ["authorize:/wps-api/v1/auth/login"]
