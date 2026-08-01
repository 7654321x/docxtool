from __future__ import annotations

import json

from docxtool.web.handler_responses import (
    send_json_error_response,
    send_json_response,
    send_redirect_response,
    send_text_response,
)


class FakeWriter:
    """测试用写入器，传入 bytes 后累积到 data 字段并返回 None。"""

    def __init__(self) -> None:
        self.data = b""

    def write(self, data: bytes) -> None:
        """传入响应 bytes，追加保存到内存缓冲区并返回 None。"""
        self.data += data


class FakeHandler:
    """测试用 handler，记录发送状态、响应头和响应体。"""

    def __init__(self) -> None:
        self.status = 0
        self.headers: list[tuple[str, str]] = []
        self.ended = False
        self.wfile = FakeWriter()

    def send_response(self, status: int) -> None:
        """传入 HTTP 状态码，记录到 handler 并返回 None。"""
        self.status = status

    def send_header(self, key: str, value: str) -> None:
        """传入响应头名和值，记录到 headers 列表并返回 None。"""
        self.headers.append((key, value))

    def end_headers(self) -> None:
        """无需传入数据，标记响应头已经结束并返回 None。"""
        self.ended = True


def _legacy_error_body(code: str, message: str, *, field: str = "", reason: str = "") -> dict:
    """传入错误字段，返回旧接口扁平错误体供测试使用。"""
    return {"code": code, "error": message, "field": field, "reason": reason}


def test_send_redirect_response_writes_location_and_security_headers() -> None:
    """跳转响应发送器应写入 303、Location、附加头和安全头。"""
    handler = FakeHandler()

    send_redirect_response(
        handler,
        target="/monitor",
        extra_headers=[("Set-Cookie", "a=b")],
        security_headers=lambda: handler.send_header("X-Security", "1"),
    )

    assert handler.status == 303
    assert handler.headers == [("Location", "/monitor"), ("Set-Cookie", "a=b"), ("X-Security", "1")]
    assert handler.ended is True


def test_send_text_response_writes_utf8_body_and_headers() -> None:
    """文本响应发送器应写入 UTF-8 正文、CORS 头和安全头。"""
    handler = FakeHandler()

    send_text_response(
        handler,
        body="公文",
        mime="text/plain",
        status=201,
        cors_headers=lambda: handler.send_header("Access-Control-Allow-Origin", "*"),
        security_headers=lambda: handler.send_header("X-Security", "1"),
    )

    assert handler.status == 201
    assert ("Content-Type", "text/plain; charset=utf-8") in handler.headers
    assert ("Content-Length", str(len("公文".encode("utf-8")))) in handler.headers
    assert handler.wfile.data == "公文".encode("utf-8")


def test_send_json_response_writes_json_body_and_extra_headers() -> None:
    """JSON 响应发送器应写入 JSON 正文和调用方附加头。"""
    handler = FakeHandler()

    send_json_response(
        handler,
        obj={"name": "公文"},
        status=202,
        extra_headers=[("Set-Cookie", "a=b")],
        cors_headers=lambda: handler.send_header("Access-Control-Allow-Origin", "*"),
        security_headers=lambda: handler.send_header("X-Security", "1"),
    )

    assert handler.status == 202
    assert ("Content-Type", "application/json") in handler.headers
    assert ("Set-Cookie", "a=b") in handler.headers
    assert json.loads(handler.wfile.data.decode("utf-8")) == {"name": "公文"}


def test_send_json_error_response_selects_auth_or_legacy_contract() -> None:
    """JSON 错误响应发送器应按路由类型选择认证合同或旧接口合同。"""
    auth_handler = FakeHandler()
    legacy_handler = FakeHandler()

    send_json_error_response(
        auth_handler,
        auth_route=True,
        code="BAD",
        message="失败",
        status=400,
        field="username",
        retry_after=3,
        legacy_error_body=_legacy_error_body,
        cors_headers=lambda: None,
        security_headers=lambda: None,
    )
    send_json_error_response(
        legacy_handler,
        auth_route=False,
        code="BAD",
        message="失败",
        status=400,
        reason="invalid",
        legacy_error_body=_legacy_error_body,
        cors_headers=lambda: None,
        security_headers=lambda: None,
    )

    assert ("Retry-After", "3") in auth_handler.headers
    assert json.loads(auth_handler.wfile.data.decode("utf-8")) == {
        "ok": False,
        "error": {"code": "BAD", "message": "失败", "field": "username"},
    }
    assert json.loads(legacy_handler.wfile.data.decode("utf-8")) == {
        "code": "BAD",
        "error": "失败",
        "field": "",
        "reason": "invalid",
    }
